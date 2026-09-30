"""
Pre-download every runtime weight so the first real request isn't slow.

Runs each model's CPU loader once, which triggers all Hub/GitHub/torch-hub
downloads into the mounted caches (HF_HOME / TORCH_HOME under data/weights/).
Nothing is moved to the GPU here — this is purely a disk warm-up.

Run inside the container so the deps + cache volume are present:
    docker compose run --rm furniture-replace python scripts/prefetch_models.py
"""
from __future__ import annotations

import logging
import time

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("prefetch")


def _step(name: str, fn) -> None:
    t0 = time.time()
    logger.info("↓ %s …", name)
    try:
        fn()
        logger.info("  ✓ %s (%.0fs)", name, time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("  ✗ %s failed: %s", name, exc)


def main() -> int:
    from app.models.inpainting import _load_brushnet, _load_ip_adapter, _load_lama
    from app.models.matching import _load_clip
    from app.models.segmentation import _load_segmenter

    _step("SAM 2.1 (segmentation)", _load_segmenter)
    _step("CLIP (matching)", _load_clip)
    _step("LaMa (prompt stage 1)", _load_lama)
    _step("BrushNet / SD1.5-inpaint (prompt stage 2)", _load_brushnet)
    _step("SD1.5-inpaint + IP-Adapter (reference)", _load_ip_adapter)

    logger.info("Done. Weights cached under data/weights/ — first request is now warm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
