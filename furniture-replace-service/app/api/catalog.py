"""Catalog ingestion + listing. Builds the Qdrant collection this service searches."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.catalog.store import catalog_store
from app.config import settings
from app.models.manager import model_manager
from app.models.matching import ClipEmbedder
from app.schemas import (
    CatalogListResponse,
    ProductIngestRequest,
    ProductIngestResponse,
    ProductMatch,
)
from app.utils.images import load_rgb, save_png

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


@router.post("/products", response_model=ProductIngestResponse)
async def ingest_product(req: ProductIngestRequest) -> ProductIngestResponse:
    image = load_rgb(req.image)
    product_id = req.product_id or uuid.uuid4().hex

    # Persist the product image so /match and /replace (reference mode) can serve
    # and re-read it as a local static file.
    save_png(image, settings.catalog_images_dir / f"{product_id}.png")
    image_url = f"/catalog-images/{product_id}.png"

    with model_manager.use("clip") as clip:
        assert isinstance(clip, ClipEmbedder)
        vector = clip.embed_image(image)

    try:
        catalog_store.upsert(
            product_id,
            vector,
            payload={
                "name": req.name,
                "category": req.category,
                "price": req.price,
                "currency": req.currency,
                "image_url": image_url,
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Qdrant upsert failed: {exc}") from exc

    return ProductIngestResponse(product_id=product_id, indexed=True, image_url=image_url)


@router.get("/products", response_model=CatalogListResponse)
async def list_products(limit: int = 200) -> CatalogListResponse:
    rows = catalog_store.list_all(limit=limit)
    products = [
        ProductMatch(
            product_id=r["product_id"],
            name=r.get("name", "unknown"),
            category=r.get("category", "unknown"),
            price=r.get("price"),
            currency=r.get("currency", "PLN"),
            image_url=r.get("image_url", ""),
            similarity=1.0,
        )
        for r in rows
    ]
    return CatalogListResponse(products=products, count=len(products))
