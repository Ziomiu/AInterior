from contextlib import ExitStack
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("torch") and importlib.util.find_spec("fastapi"),
                     "Run API smoke tests inside the service image")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        directory = cls.stack.enter_context(tempfile.TemporaryDirectory())
        cls.stack.enter_context(patch.dict(os.environ, {"DATA_DIR": directory}))
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from fastapi.testclient import TestClient
        import app.main as service
        cls.service = service
        cls.stack.enter_context(patch.object(service.catalog_store, "ensure_collection"))
        cls.client = cls.stack.enter_context(TestClient(service.app))

    @classmethod
    def tearDownClass(cls):
        cls.service.settings.service_api_key = None
        cls.stack.close()
        sys.path.pop(0)

    def tearDown(self):
        self.service.settings.service_api_key = None

    def test_fresh_data_directory_starts_and_health_responds(self):
        response = self.client.get("/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.service.settings.results_dir.is_dir())
        self.assertEqual(len(response.json()["models"]), 6)
        self.assertIn("sam2_model", response.json()["inference_config"])
        self.assertNotIn("service_api_key", response.json()["inference_config"])

    def test_invalid_service_key_returns_401_not_500(self):
        self.service.settings.service_api_key = "unit-test-key"
        self.assertEqual(self.client.get("/v1/health").status_code, 401)
        self.assertEqual(self.client.get("/v1/health", headers={"X-Service-Key": "wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/v1/health", headers={"X-Service-Key": "unit-test-key"}).status_code, 200)

    def test_invalid_steps_rejected_before_image_loading(self):
        response = self.client.post("/v1/replace", json={
            "image": {"image_base64": "YWJj"}, "mask": {"image_base64": "YWJj"},
            "mode": "prompt", "prompt": "chair", "steps": 0,
        })
        self.assertEqual(response.status_code, 422)

    def test_catalog_identifier_cannot_be_a_file_path(self):
        response = self.client.post("/v1/catalog/products", json={
            "image": {"image_base64": "YWJj"}, "name": "chair", "category": "chair",
            "product_id": "../../outside",
        })
        self.assertEqual(response.status_code, 422)

    def test_zero_guidance_is_not_replaced_by_default(self):
        import app.api.replace as route
        inpainter = Mock(return_value=(Mock(), Mock()))
        submitted = Mock(return_value=SimpleNamespace(id="test-job", status="queued"))
        with patch.object(route, "load_rgb"), patch.object(route, "load_mask"), \
               patch.object(route, "mask_to_bbox", return_value=(0, 0, 32, 24)), \
             patch.object(route.job_queue, "submit", submitted), \
             patch.object(route, "run_prompt_replace", inpainter), patch.object(route, "save_png"):
            response = self.client.post("/v1/replace", json={
                "image": {"image_base64": "YWJj"}, "mask": {"image_base64": "YWJj"},
                "mode": "prompt", "prompt": "chair", "steps": 1, "guidance_scale": 0,
            })
            self.assertEqual(response.status_code, 200)
            submitted.call_args.args[0]()
            self.assertEqual(inpainter.call_args.args[-1], 0)

    def test_single_stage_does_not_save_a_cleaned_image(self):
        import app.api.replace as route
        submitted = Mock(return_value=SimpleNamespace(id="test-job", status="queued"))
        with patch.object(route, "load_rgb"), patch.object(route, "load_mask"), \
               patch.object(route, "mask_to_bbox", return_value=(0, 0, 32, 24)), \
             patch.object(route.job_queue, "submit", submitted), \
             patch.object(route, "run_prompt_replace", return_value=(Mock(), None)), \
             patch.object(route, "save_png") as save:
            response = self.client.post("/v1/replace", json={
                "image": {"image_base64": "YWJj"}, "mask": {"image_base64": "YWJj"},
                "mode": "prompt", "prompt": "chair", "steps": 1,
            })
            self.assertEqual(response.status_code, 200)
            result = submitted.call_args.args[0]()
            self.assertIsNone(result["stage1_url"])
            save.assert_called_once()

    def test_empty_mask_is_rejected_before_queuing(self):
        import app.api.replace as route
        with patch.object(route, "load_rgb"), patch.object(route, "load_mask"), \
             patch.object(route, "mask_to_bbox", return_value=None), \
             patch.object(route.job_queue, "submit") as submitted:
            response = self.client.post("/v1/replace", json={
                "image": {"image_base64": "YWJj"}, "mask": {"image_base64": "YWJj"},
                "mode": "prompt", "prompt": "chair",
            })
        self.assertEqual(response.status_code, 400)
        submitted.assert_not_called()


if __name__ == "__main__":
    unittest.main()