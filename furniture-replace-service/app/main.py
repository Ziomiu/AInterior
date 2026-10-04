from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import catalog, health, jobs, match, replace, segment
from app.catalog.store import catalog_store
from app.config import settings
from app.jobs.queue import job_queue
from app.models.inpainting import register_inpainting_models
from app.models.manager import model_manager
from app.models.matching import register_matching_model
from app.models.segmentation import register_segmentation_models

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")


async def _idle_reaper_loop():
    """Periodically offloads an idle heavy model from GPU. See ModelManager.idle_reaper_tick."""
    while True:
        await asyncio.sleep(30)
        await asyncio.to_thread(model_manager.idle_reaper_tick)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()

    # Registration only — no weights load from disk here. Loading is deferred to
    # first use of each model (see ModelManager), so the service starts in ~1s
    # regardless of how many models it knows about.
    register_segmentation_models()
    register_matching_model()
    register_inpainting_models()
    logger.info(f"Models registered. Device: {model_manager.device}")

    try:
        catalog_store.ensure_collection()
    except Exception as exc:  # noqa: BLE001 — Qdrant may not be up yet during local dev
        logger.warning(f"Qdrant not reachable at startup ({exc}). "
                       f"Catalog endpoints will retry lazily.")

    job_queue.start()
    reaper_task = asyncio.create_task(_idle_reaper_loop())

    yield

    reaper_task.cancel()
    await job_queue.stop()


app = FastAPI(
    title="Furniture Replacement Service",
    description="Segment (click) -> match to catalog -> replace, for interior photos.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def check_service_key(request: Request, call_next):
    if settings.service_api_key and request.url.path.startswith("/v1"):
        key = request.headers.get("X-Service-Key")
        if not secrets.compare_digest((key or "").encode(), settings.service_api_key.encode()):
            return JSONResponse(status_code=401, content={"detail": "Missing or invalid X-Service-Key header"})
    return await call_next(request)


app.include_router(segment.router)
app.include_router(match.router)
app.include_router(replace.router)
app.include_router(catalog.router)
app.include_router(jobs.router)
app.include_router(health.router)

app.mount("/results", StaticFiles(directory=str(settings.results_dir), check_dir=False), name="results")
app.mount("/catalog-images", StaticFiles(directory=str(settings.catalog_images_dir), check_dir=False), name="catalog-images")
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
