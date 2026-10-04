"""
ModelManager — single most important file in this service.

Problem it solves: SAM 3 (~8GB), BrushNet+SD1.5 (~8GB), and IP-Adapter+SD1.5 (~8GB)
do not fit on the reference hardware (8-24GB VRAM) at the same time. Reloading a
model from disk on every request is also unacceptable (multi-second cold load).

Solution: every model's weights are loaded from disk exactly ONCE, into CPU RAM,
at first use. From then on this manager only ever moves tensors between CPU and
GPU (~0.3-0.5s for these model sizes), never touches disk again. At most one
"heavy" model sits on the GPU at any moment. Light models (CLIP) stay GPU-resident
permanently since they're cheap and used on almost every request.

This works because the job queue (see app/jobs/queue.py) processes one job at a
time — there is never a concurrent request for two different heavy models, so
"one heavy model on GPU" is not a bottleneck, it's just correctly matching the
architecture to the hardware.
"""
from __future__ import annotations

import gc
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import torch

from app.config import settings

logger = logging.getLogger("model_manager")

# Models that are cheap enough to stay on GPU permanently once loaded.
LIGHT_MODELS = {"clip"}

# Models that share GPU budget — only one of these is resident on GPU at a time.
HEAVY_MODELS = {"sam3", "sam2", "lama", "brushnet", "ip_adapter"}


@dataclass
class ManagedModel:
    name: str
    loader: Callable[[], object]          # builds the model on CPU, called once
    to_device_fn: Callable[[object, str], object]  # moves an already-built model to a device
    instance: object | None = None
    device: str = "not_loaded"            # "not_loaded" | "cpu" | "gpu"
    last_used: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelManager:
    """
    Usage:
        with model_manager.use("brushnet") as pipe:
            result = pipe(...)
    Everything else (loading, swapping, VRAM bookkeeping) happens automatically.
    """

    def __init__(self) -> None:
        self._registry: dict[str, ManagedModel] = {}
        self._gpu_lock = threading.Lock()   # only one heavy model moves at a time
        self._current_heavy_on_gpu: str | None = None
        self.device = settings.device if torch.cuda.is_available() else "cpu"
        if settings.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA requested but not available — falling back to CPU. "
                            "Inference will be dramatically slower.")

    def register(self, name: str, loader: Callable[[], object],
                 to_device_fn: Callable[[object, str], object]) -> None:
        """Register a model without loading it. Loading is deferred to first use."""
        self._registry[name] = ManagedModel(name=name, loader=loader, to_device_fn=to_device_fn)

    def _ensure_loaded_on_cpu(self, m: ManagedModel) -> None:
        if m.instance is None:
            logger.info(f"[{m.name}] cold load from disk (first use)...")
            t0 = time.time()
            m.instance = m.loader()  # loader is expected to build on CPU
            m.device = "cpu"
            logger.info(f"[{m.name}] loaded in {time.time() - t0:.1f}s (resident on CPU)")

    def _evict_current_heavy(self) -> None:
        if self._current_heavy_on_gpu is None:
            return
        prev = self._registry[self._current_heavy_on_gpu]
        with prev.lock:
            if prev.device == "gpu" and prev.instance is not None:
                logger.info(f"[{prev.name}] moving GPU -> CPU to free VRAM")
                prev.instance = prev.to_device_fn(prev.instance, "cpu")
                prev.device = "cpu"
                torch.cuda.empty_cache()
        self._current_heavy_on_gpu = None

    def use(self, name: str):
        return _ModelContext(self, name)

    def _acquire(self, name: str):
        m = self._registry.get(name)
        if m is None:
            raise KeyError(f"Model '{name}' is not registered")

        with m.lock:
            self._ensure_loaded_on_cpu(m)

            if name in LIGHT_MODELS:
                if m.device != "gpu" and self.device == "cuda":
                    m.instance = m.to_device_fn(m.instance, self.device)
                    m.device = "gpu"
                m.last_used = time.time()
                return m.instance

            with self._gpu_lock:
                if self._current_heavy_on_gpu != name:
                    self._evict_current_heavy()
                    if self.device == "cuda":
                        logger.info(f"[{name}] moving CPU -> GPU")
                        t0 = time.time()
                        m.instance = m.to_device_fn(m.instance, self.device)
                        m.device = "gpu"
                        logger.info(f"[{name}] on GPU in {time.time() - t0:.2f}s")
                    self._current_heavy_on_gpu = name
                m.last_used = time.time()
                return m.instance

    def status(self) -> list[dict]:
        out = []
        for m in self._registry.values():
            out.append({
                "name": m.name,
                "resident_on": m.device,
                "last_used_seconds_ago": (
                    round(time.time() - m.last_used, 1) if m.instance is not None else None
                ),
            })
        return out

    def vram_stats(self) -> dict:
        if not torch.cuda.is_available():
            return {"vram_allocated_mb": None, "vram_reserved_mb": None}
        return {
            "vram_allocated_mb": round(torch.cuda.memory_allocated() / 1e6, 1),
            "vram_reserved_mb": round(torch.cuda.memory_reserved() / 1e6, 1),
        }

    def idle_reaper_tick(self) -> None:
        """
        Called periodically (see app/main.py startup task). Offloads the
        currently-resident heavy model if it's been idle past the configured
        threshold, freeing VRAM during quiet periods without any request
        having to pay for it.
        """
        if self._current_heavy_on_gpu is None:
            return
        m = self._registry[self._current_heavy_on_gpu]
        if time.time() - m.last_used > settings.model_idle_offload_seconds:
            logger.info(f"[{m.name}] idle for >{settings.model_idle_offload_seconds}s — offloading")
            with self._gpu_lock:
                self._evict_current_heavy()


class _ModelContext:
    def __init__(self, manager: ModelManager, name: str):
        self.manager = manager
        self.name = name
        self.instance = None

    def __enter__(self):
        self.instance = self.manager._acquire(self.name)
        return self.instance

    def __exit__(self, exc_type, exc, tb):
        # Deliberately a no-op: the model stays on GPU after use so back-to-back
        # requests for the same model (the common case — e.g. several /replace
        # calls with mode=prompt in a row) don't pay the swap cost every time.
        # Eviction only happens when a *different* heavy model is requested,
        # or via the idle reaper after a quiet period.
        gc.collect()
        return False


# Module-level singleton — imported by app.main and app.api.*
model_manager = ModelManager()
