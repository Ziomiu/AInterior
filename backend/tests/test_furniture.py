import base64
import hashlib
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def authenticate():
    raise HTTPException(401, "Authentication required")


collection = SimpleNamespace(
    find_one=AsyncMock(), update_one=AsyncMock(), insert_one=AsyncMock(), create_index=AsyncMock(),
)
with patch.dict(sys.modules, {
    "database.mongo": SimpleNamespace(db={
        "furniture_jobs": collection, "generated_images": collection,
        "furniture_products": collection, "gpu_queue_state": collection,
    }),
    "utils.auth_helpers": SimpleNamespace(get_current_user=authenticate),
}):
    from controllers import furniture


def fixture_image():
    output = BytesIO()
    Image.new("RGB", (32, 24)).save(output, "PNG")
    return base64.b64encode(output.getvalue()).decode()


class FurnitureTests(unittest.TestCase):
    def setUp(self):
        self.user = {"_id": ObjectId()}
        self.app = FastAPI()
        self.app.include_router(furniture.furniture_router, prefix="/furniture")
        self.app.dependency_overrides[authenticate] = lambda: self.user
        self.client = TestClient(self.app)
        self.jobs = SimpleNamespace(
            find_one=AsyncMock(return_value=None), update_one=AsyncMock(),
            insert_one=AsyncMock(), create_index=AsyncMock(),
        )
        self.images = SimpleNamespace(find_one=AsyncMock(return_value=None), update_one=AsyncMock())
        self.products = SimpleNamespace(find_one=AsyncMock(return_value=None), insert_one=AsyncMock(), update_one=AsyncMock())
        self.new_ticket = AsyncMock(return_value="test-ticket")
        self.cancel_ticket = AsyncMock()
        self.patches = [patch.object(furniture, "jobs_collection", self.jobs), patch.object(furniture, "images_collection", self.images), patch.object(furniture, "products_collection", self.products)]
        self.patches.extend([
            patch.object(furniture, "_new_gpu_ticket", self.new_ticket),
            patch.object(furniture, "_cancel_gpu_ticket", self.cancel_ticket),
        ])
        for item in self.patches:
            item.start()

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()

    def test_authentication_is_required(self):
        self.app.dependency_overrides.clear()
        self.assertEqual(self.client.get("/furniture/health").status_code, 401)

    def test_foreign_job_is_not_fetched_from_service(self):
        job_id = uuid4()
        with patch.object(furniture, "_service", AsyncMock()) as service:
            response = self.client.get(f"/furniture/jobs/{job_id}")
        self.assertEqual(response.status_code, 404)
        self.jobs.find_one.assert_awaited_once_with({"_id": str(job_id), "user_id": self.user["_id"]})
        service.assert_not_awaited()

    def test_catalog_does_not_expose_foreign_reference_images(self):
        self.products.find_one.return_value = {"user_id": ObjectId()}
        with patch.object(furniture, "_service", AsyncMock(return_value={"products": [{
            "product_id": str(uuid4()), "image_url": f"/catalog-images/{uuid4().hex}.png",
        }]})), patch.object(furniture, "_asset", AsyncMock()) as asset:
            response = self.client.get("/furniture/products")
        self.assertEqual(response.json(), {"products": []})
        asset.assert_not_awaited()

    def test_segment_tracks_owner_and_does_not_store_input_image(self):
        job_id = str(uuid4())
        with patch.object(furniture, "_service", AsyncMock(return_value={"job_id": job_id})) as service:
            response = self.client.post("/furniture/segment", json={
                "image": fixture_image(), "points": [{"x": 5, "y": 5}],
            })
        self.assertEqual(response.status_code, 200)
        self.new_ticket.assert_awaited_once_with(self.user["_id"], "segment")
        self.assertEqual(service.await_args.kwargs["gpu_ticket_id"], "test-ticket")
        record = self.jobs.insert_one.call_args.args[0]
        self.assertEqual(record["user_id"], self.user["_id"])
        self.assertEqual(record["dimensions"], [32, 24])
        self.assertNotIn("image", record)

    def test_unknown_reference_is_not_public(self):
        with patch.object(furniture, "_service", AsyncMock(return_value={"products": [{
            "product_id": str(uuid4()), "image_url": f"/catalog-images/{uuid4().hex}.png",
        }]})), patch.object(furniture, "_asset", AsyncMock()) as asset:
            response = self.client.get("/furniture/products")
        self.assertEqual(response.json(), {"products": []})
        asset.assert_not_awaited()

    def test_explicit_shared_product_is_visible(self):
        self.products.find_one.return_value = {"shared": True}
        with patch.object(furniture, "_service", AsyncMock(return_value={"products": [{
            "product_id": str(uuid4()), "image_url": f"/catalog-images/{uuid4().hex}.png",
        }]})), patch.object(furniture, "_asset", AsyncMock(return_value="image")):
            response = self.client.get("/furniture/products")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["products"]), 1)

    def test_ingest_rejects_mismatched_service_identifier(self):
        with patch.object(furniture, "_service", AsyncMock(return_value={"product_id": str(uuid4())})):
            response = self.client.post("/furniture/products", json={
                "image": fixture_image(), "name": "chair", "category": "armchair",
            })
        self.assertEqual(response.status_code, 502)

    def test_ingest_rejects_missing_service_identifier(self):
        with patch.object(furniture, "_service", AsyncMock(return_value={})):
            response = self.client.post("/furniture/products", json={
                "image": fixture_image(), "name": "chair", "category": "armchair",
            })
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.products.insert_one.call_args.args[0]["status"], "pending")
        self.products.update_one.assert_not_awaited()

    def test_ingest_marks_only_matching_reference_ready(self):
        async def service(method, path, **kwargs):
            return {"product_id": UUID(kwargs["json"]["product_id"]).hex}

        with patch.object(furniture, "_service", AsyncMock(side_effect=service)) as service_call:
            response = self.client.post("/furniture/products", json={
                "image": fixture_image(), "name": "chair", "category": "armchair",
            })
        self.assertEqual(response.status_code, 200)
        self.new_ticket.assert_awaited_once_with(self.user["_id"], "catalog-ingest")
        self.assertEqual(service_call.await_args.kwargs["gpu_ticket_id"], "test-ticket")
        self.assertGreaterEqual(service_call.await_args.kwargs["timeout"], 1020)
        product_id = self.products.insert_one.call_args.args[0]["_id"]
        self.assertEqual(response.json()["product_id"], product_id)
        self.products.update_one.assert_awaited_once_with(
            {"_id": product_id, "user_id": self.user["_id"]}, {"$set": {"status": "ready"}},
        )

    def test_pending_reference_is_not_visible_even_to_owner(self):
        self.products.find_one.return_value = {"user_id": self.user["_id"], "status": "pending"}
        with patch.object(furniture, "_service", AsyncMock(return_value={"products": [{
            "product_id": str(uuid4()), "image_url": f"/catalog-images/{uuid4().hex}.png",
        }]})), patch.object(furniture, "_asset", AsyncMock()) as asset:
            response = self.client.get("/furniture/products")
        self.assertEqual(response.json(), {"products": []})
        asset.assert_not_awaited()

    def test_catalog_skips_foreign_products_before_applying_visible_limit(self):
        self.products.find_one.side_effect = [{"user_id": ObjectId()}] * 20 + [{"user_id": self.user["_id"]}]
        rows = [{"product_id": str(uuid4()), "image_url": f"/catalog-images/{uuid4().hex}.png"} for _ in range(21)]
        with patch.object(furniture, "_service", AsyncMock(return_value={"products": rows})) as service, \
             patch.object(furniture, "_asset", AsyncMock(return_value="image")) as asset:
            response = self.client.get("/furniture/products")
        self.assertEqual(len(response.json()["products"]), 1)
        service.assert_awaited_once_with("GET", "/v1/catalog/products", params={"limit": 200})
        asset.assert_awaited_once()

    def test_untrusted_result_path_is_rejected(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {"_id": job_id, "user_id": self.user["_id"], "operation": "segment", "status": "running"}
        with patch.object(furniture, "_service", AsyncMock(return_value={
            "status": "done", "result": {"mask_url": "/results/../../secret.png"},
        })):
            response = self.client.get(f"/furniture/jobs/{job_id}")
        self.assertEqual(response.status_code, 502)

    def test_live_known_stages_are_persisted_and_returned(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "operation": "replace", "status": "running",
        }
        for stage in sorted(furniture._KNOWN_STAGES - {"done", "failed"}):
            with self.subTest(stage=stage), patch.object(furniture, "_service", AsyncMock(return_value={
                "status": "running", "stage": stage,
            })), patch.object(furniture, "_asset", AsyncMock()) as asset:
                response = self.client.get(f"/furniture/jobs/{job_id}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["stage"], stage)
                self.assertIsNone(response.json()["result"])
                self.jobs.update_one.assert_awaited_with(
                    {"_id": job_id, "user_id": self.user["_id"]},
                    {"$set": {"status": "running", "stage": stage}},
                )
                asset.assert_not_awaited()

    def test_missing_or_unknown_stage_is_optional(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "operation": "segment", "status": "running",
        }
        for upstream in ({"status": "running"}, {"status": "running", "stage": "unexpected"},
                         {"status": "running", "stage": ["loading"]}, {"status": "running", "stage": None}):
            with self.subTest(upstream=upstream), patch.object(furniture, "_service", AsyncMock(return_value=upstream)):
                response = self.client.get(f"/furniture/jobs/{job_id}")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("stage", response.json())
                self.assertEqual(self.jobs.update_one.await_args.args[1], {"$set": {"status": "running"}})

    def test_segment_optional_classification_and_review_are_preserved(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "operation": "segment", "status": "running",
        }
        classification = {
            "category": "chair", "label": "chair", "confidence": 0.61,
            "uncertain": False, "confidence_kind": "relative_clip_score",
        }
        for review in (False, True):
            service_result = {
                "mask_url": f"/results/masks/{uuid4().hex}.png", "bbox": [4, 4, 16, 16], "score": 0.93,
                "classification": classification, "mask_review_required": review,
            }
            with self.subTest(review=review), patch.object(furniture, "_service", AsyncMock(return_value={
                "status": "done", "stage": "done", "result": service_result,
            })), patch.object(furniture, "_asset", AsyncMock(return_value="mask")):
                response = self.client.get(f"/furniture/jobs/{job_id}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["stage"], "done")
                self.assertEqual(response.json()["result"], {
                    "mask": "mask", "bbox": [4, 4, 16, 16], "score": 0.93,
                    "classification": classification, "mask_review_required": review,
                })
                self.assertEqual(self.jobs.update_one.await_args.args[1]["$set"]["service_result"], service_result)

    def test_legacy_segment_results_do_not_require_optional_fields(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "operation": "segment", "status": "done",
            "service_result": {"mask_url": f"/results/masks/{uuid4().hex}.png", "bbox": [0, 0, 8, 8], "score": 0.9},
        }
        with patch.object(furniture, "_asset", AsyncMock(return_value="mask")), \
             patch.object(furniture, "_service", AsyncMock()) as service:
            response = self.client.get(f"/furniture/jobs/{job_id}")
        self.assertEqual(response.json()["result"], {"mask": "mask", "bbox": [0, 0, 8, 8], "score": 0.9})
        self.assertNotIn("stage", response.json())
        service.assert_not_awaited()

    def test_failed_job_returns_persisted_terminal_stage(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "operation": "replace", "status": "running",
        }
        with patch.object(furniture, "_service", AsyncMock(return_value={
            "status": "failed", "stage": "failed", "error": "inference failed",
        })):
            response = self.client.get(f"/furniture/jobs/{job_id}")
        self.assertEqual(response.json()["stage"], "failed")
        self.assertEqual(response.json()["error"], "inference failed")
        self.assertIsNone(response.json()["result"])

    def test_save_uses_stable_id_and_insert_only_upsert(self):
        job_id, gallery_id = str(uuid4()), ObjectId()
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "operation": "replace", "status": "done",
            "dimensions": [32, 24], "gallery_id": gallery_id,
            "metadata": {"mode": "prompt", "quality": "balanced", "seed": 42},
            "service_result": {"result_url": f"/results/{uuid4().hex}.png"},
        }
        with patch.object(furniture, "_asset", AsyncMock(return_value=fixture_image())):
            first = self.client.post(f"/furniture/jobs/{job_id}/save")
            second = self.client.post(f"/furniture/jobs/{job_id}/save")
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["image_id"], str(gallery_id))
        for call in self.images.update_one.call_args_list:
            self.assertEqual(call.args[0], {"_id": gallery_id, "user_id": self.user["_id"]})
            self.assertIn("$setOnInsert", call.args[1])
            self.assertTrue(call.kwargs["upsert"])

    def test_replace_requires_an_owned_mask_job(self):
        with patch.object(furniture, "_service", AsyncMock()) as service:
            response = self.client.post("/furniture/replace", json={
                "image": fixture_image(), "mask_job_id": str(uuid4()), "prompt": "red chair",
            })
        self.assertEqual(response.status_code, 404)
        service.assert_not_awaited()

    def test_mask_cannot_be_reused_on_different_photo_of_same_size(self):
        job_id = str(uuid4())
        self.jobs.find_one.return_value = {
            "_id": job_id, "user_id": self.user["_id"], "status": "done", "operation": "segment",
            "dimensions": [32, 24], "image_hash": hashlib.sha256(b"another-photo").hexdigest(),
            "service_result": {"mask_url": f"/results/masks/{uuid4().hex}.png"},
        }
        response = self.client.post("/furniture/replace", json={
            "image": fixture_image(), "mask_job_id": job_id, "prompt": "chair",
        })
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()