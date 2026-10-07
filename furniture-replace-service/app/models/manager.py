"""
ModelManager — single most important file in this service.

Problem it solves: the segmenter (Grounding DINO + SAM 2.1), BrushNet+SD1.5, and
IP-Adapter+SD1.5 don't comfortably fit on the reference hardware (8-24GB VRAM) at
the same time. Reloading a model from disk on every request is also unacceptable
(multi-second cold load).

Models load lazily and use a bounded, least-recently-used heavy-model cache.
Evicted models reload from disk on their next use. At most one heavy model sits
on the GPU at any moment. CLIP stays outside the heavy-model cache. Actual load
and transfer costs depend on the model and available host memory.

This works because the job queue (app/jobs/queue.py) processes one job at a time
— there is never a concurrent request for two different heavy models, so "one
heavy model on GPU" is not a bottleneck, it's correctly matching the architecture
to the hardware.
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

# Models cheap enough to stay on GPU permanently once loaded.
LIGHT_MODELS = {"clip"}

# Models that share GPU budget — only one of these is resident on GPU at a time.
HEAVY_MODELS = {"segmenter", "lama", "brushnet", "ip_adapter", "prompt_quality"}


@dataclass
class ManagedModel:
    name: str
    loader: Callable[[], object]                     # builds the model on CPU, called once
    to_device_fn: Callable[[object, str], object]    # moves an already-built model to a device
    instance: object | None = None
    device: str = "not_loaded"                       # "not_loaded" | "cpu" | "gpu"
    last_used: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelManager:
    """
    Usage:
        with model_manager.use("brushnet") as pipe:
            result = pipe(...)
    Loading, swapping and VRAM bookkeeping happen automatically.
    """

    def __init__(self) -> None:
        self._registry: dict[str, ManagedModel] = {}
        self._inference_lock = threading.Lock()
        self._gpu_lock = threading.Lock()  # only one heavy model moves at a time
        self._current_heavy_on_gpu: str | None = None
        self.device = "cuda" if (settings.device == "cuda" and torch.cuda.is_available()) else "cpu"
        if settings.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA requested but not available — falling back to CPU. "
                           "Inference will be dramatically slower.")

    def register(self, name: str, loader: Callable[[], object],
                 to_device_fn: Callable[[object, str], object]) -> None:
        """Register a model without loading it. Loading is deferred to first use."""
        self._registry[name] = ManagedModel(name=name, loader=loader, to_device_fn=to_device_fn)

    def _ensure_loaded_on_cpu(self, m: ManagedModel) -> None:
        if m.instance is None:
            self._make_cache_room(m.name)
            logger.info(f"[{m.name}] cold load from disk (first use)...")
            t0 = time.time()
            m.instance = m.loader()  # loader builds on CPU
            m.device = "cpu"
            logger.info(f"[{m.name}] loaded in {time.time() - t0:.1f}s (resident on CPU)")

    def _make_cache_room(self, name: str) -> None:
        if name not in HEAVY_MODELS:
            return
        loaded = [model for model in self._registry.values()
                  if model.name in HEAVY_MODELS and model.instance is not None and model.name != name]
        while len(loaded) >= settings.max_loaded_heavy_models:
            oldest = min(loaded, key=lambda model: model.last_used)
            if self._current_heavy_on_gpu == oldest.name:
                self._evict_current_heavy()
            with oldest.lock:
                oldest.instance = None
                oldest.device = "not_loaded"
            loaded.remove(oldest)
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info(f"[{oldest.name}] released to bound host memory")

    def _evict_current_heavy(self) -> None:
        if self._current_heavy_on_gpu is None:
            return
        prev = self._registry[self._current_heavy_on_gpu]
        with prev.lock:
            if prev.device == "gpu" and prev.instance is not None:
                logger.info(f"[{prev.name}] moving GPU -> CPU to free VRAM")
                prev.instance = prev.to_device_fn(prev.instance, "cpu")
                prev.device = "cpu"
                if torch.cuda.is_available():
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
                "backend": getattr(m.instance, "backend", None),
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
        Called periodically (app/main.py). Offloads the currently-resident heavy
        model if it's been idle past the configured threshold, freeing VRAM
        during quiet periods without any request having to pay for it.
        """
        if not self._inference_lock.acquire(blocking=False):
            return
        try:
            if self._current_heavy_on_gpu is None:
                return
            m = self._registry[self._current_heavy_on_gpu]
            if time.time() - m.last_used > settings.model_idle_offload_seconds:
                logger.info(f"[{m.name}] idle for >{settings.model_idle_offload_seconds}s — offloading")
                with self._gpu_lock:
                    self._evict_current_heavy()
        finally:
            self._inference_lock.release()


class _ModelContext:
    def __init__(self, manager: ModelManager, name: str):
        self.manager = manager
        self.name = name
        self.instance = None

    def __enter__(self):
        self.manager._inference_lock.acquire()
        try:
            self.instance = self.manager._acquire(self.name)
            return self.instance
        except BaseException:
            self.manager._inference_lock.release()
            raise

    def __exit__(self, exc_type, exc, tb):
        # Deliberately keeps the model on GPU after use so back-to-back requests
        # for the same model don't pay the swap cost. Eviction happens only when a
        # different heavy model is requested, or via the idle reaper.
        self.manager._inference_lock.release()
        return False


model_manager = ModelManager()
