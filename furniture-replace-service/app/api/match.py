"""POST /v1/match — CLIP + Qdrant nearest products. Synchronous (fast, <200ms)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.catalog.store import catalog_store
from app.gpu_queue import gpu_slot, ticket_id_from_request
from app.models.manager import model_manager
from app.models.matching import ClipEmbedder
from app.schemas import MatchRequest, MatchResult, ProductMatch
from app.utils.images import crop_object_on_white, load_mask, load_rgb

router = APIRouter(prefix="/v1", tags=["match"])


@router.post("/match", response_model=MatchResult)
def match(req: MatchRequest, request: Request) -> MatchResult:
    gpu_ticket_id = ticket_id_from_request(request)
    image = load_rgb(req.image)
    mask = load_mask(req.mask, size=image.size)

    # CLIP should describe the object, not the room — isolate it on white first.
    crop = crop_object_on_white(image, mask)

    with gpu_slot(gpu_ticket_id):
        with model_manager.use("clip") as clip:
            assert isinstance(clip, ClipEmbedder)
            vector = clip.embed_image(crop)

    try:
        hits = catalog_store.search(vector, req.top_k, req.category_filter, req.product_ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Catalog search failed: {exc}") from exc

    matches = [
        ProductMatch(
            product_id=h["product_id"],
            name=h.get("name", "unknown"),
            category=h.get("category", "unknown"),
            price=h.get("price"),
            currency=h.get("currency", "PLN"),
            image_url=h.get("image_url", ""),
            similarity=round(h["similarity"], 4),
        )
        for h in hits
    ]
    return MatchResult(matches=matches)
