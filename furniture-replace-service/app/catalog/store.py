"""
Catalog store — Qdrant wrapper.

Holds one CLIP vector per product plus its metadata payload. Swappable: nothing
outside this file knows the vector DB is Qdrant. Kept intentionally small — this
service is not the system of record for the catalog, it just needs fast visual
nearest-neighbour lookup over whatever products have been ingested.
"""
from __future__ import annotations

import logging
import threading

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from app.config import settings

logger = logging.getLogger("catalog")


class CatalogStore:
    def __init__(self) -> None:
        self.client = QdrantClient(url=settings.qdrant_url)
        self.collection = settings.qdrant_collection
        self._collection_ready = False
        self._collection_lock = threading.Lock()

    def ensure_collection(self) -> None:
        if self._collection_ready:
            return
        with self._collection_lock:
            if self._collection_ready:
                return
            existing = {c.name for c in self.client.get_collections().collections}
            if self.collection not in existing:
                logger.info(f"Creating Qdrant collection '{self.collection}'")
                self.client.create_collection(
                    collection_name=self.collection,
                    vectors_config=qmodels.VectorParams(
                        size=settings.clip_embed_dim,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name="category",
                    field_schema=qmodels.PayloadSchemaType.KEYWORD,
                )
            self._collection_ready = True

    def upsert(self, product_id: str, vector: np.ndarray, payload: dict) -> None:
        self.ensure_collection()
        self.client.upsert(
            collection_name=self.collection,
            points=[
                qmodels.PointStruct(
                    id=product_id,
                    vector=vector.tolist(),
                    payload=payload,
                )
            ],
        )

    def search(
        self, vector: np.ndarray, top_k: int, category_filter: str | None = None,
        product_ids: list[str] | None = None,
    ) -> list[dict]:
        if product_ids is not None and not product_ids:
            return []
        self.ensure_collection()
        must = []
        if category_filter:
            must.append(qmodels.FieldCondition(
                key="category",
                match=qmodels.MatchValue(value=category_filter),
            ))
        if product_ids is not None:
            must.append(qmodels.HasIdCondition(has_id=product_ids))
        flt = qmodels.Filter(must=must) if must else None
        hits = self.client.search(
            collection_name=self.collection,
            query_vector=vector.tolist(),
            limit=top_k,
            query_filter=flt,
        )
        out = []
        for h in hits:
            payload = dict(h.payload or {})
            payload["product_id"] = str(h.id)
            payload["similarity"] = float(h.score)  # cosine similarity, 0..1
            out.append(payload)
        return out

    def get(self, product_id: str) -> dict | None:
        self.ensure_collection()
        recs = self.client.retrieve(self.collection, ids=[product_id], with_payload=True)
        if not recs:
            return None
        payload = dict(recs[0].payload or {})
        payload["product_id"] = str(recs[0].id)
        return payload

    def list_all(self, limit: int = 200) -> list[dict]:
        self.ensure_collection()
        points, _ = self.client.scroll(
            self.collection, limit=limit, with_payload=True, with_vectors=False
        )
        out = []
        for p in points:
            payload = dict(p.payload or {})
            payload["product_id"] = str(p.id)
            payload["similarity"] = 1.0
            out.append(payload)
        return out


catalog_store = CatalogStore()
