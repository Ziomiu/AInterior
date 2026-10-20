import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from controllers import model
from utils.auth_helpers import get_current_user


class PanoramaAPITests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(model.models, prefix="/model")
        self.app.dependency_overrides[get_current_user] = lambda: {"_id": "lab-user"}
        self.client = TestClient(self.app)
        self.payload = {"model_id": "realvisxl-v4", "brief": "Exhibition interior", "seed": 42}

    def tearDown(self):
        self.client.close()

    def test_inventory_and_generation_require_authentication(self):
        self.app.dependency_overrides.clear()
        self.assertIn(self.client.get("/model/panorama/models").status_code, (401, 403))
        self.assertIn(self.client.post("/model/generate/panorama", json=self.payload).status_code, (401, 403))

    def test_unknown_profile_is_rejected_without_accessing_comfyui(self):
        with patch.object(model, "_panorama_inventory", AsyncMock()) as inventory:
            response = self.client.post("/model/generate/panorama", json=self.payload | {"model_id": "../unsafe"})
        self.assertEqual(response.status_code, 422)
        inventory.assert_not_awaited()

    def test_missing_checkpoint_is_rejected_before_generation(self):
        with patch.object(model, "_panorama_inventory", AsyncMock(return_value=[])), patch.object(
            model, "get_image", AsyncMock()
        ) as generate:
            response = self.client.post("/model/generate/panorama", json=self.payload)
        self.assertEqual(response.status_code, 503)
        generate.assert_not_awaited()

    def test_generation_uses_shared_gpu_path_and_saves_profile_metadata(self):
        with patch.object(model, "_panorama_inventory", AsyncMock(return_value=[{"id": "realvisxl-v4"}])), patch.object(
            model, "get_image", AsyncMock(return_value="image-data")
        ) as generate, patch.object(model, "save_image_record", AsyncMock()) as save:
            response = self.client.post("/model/generate/panorama", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"image": "image-data"})
        workflow, user_id, operation = generate.await_args.args
        self.assertEqual((user_id, operation), ("lab-user", "panorama"))
        self.assertEqual(workflow["5"]["inputs"]["width"], 1536)
        self.assertEqual(workflow["4"]["inputs"]["ckpt_name"], "RealVisXL_V4.0.safetensors")
        self.assertEqual(save.await_args.kwargs["metadata"]["mode"], "panorama")
        self.assertEqual(save.await_args.kwargs["metadata"]["seed"], 42)

    def test_inventory_filters_comfyui_checkpoints(self):
        payload = {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [[
            "RealVisXL_V4.0.safetensors", "juggernaut-inpainting.safetensors",
        ]]}}}}
        with patch.object(model.httpx, "AsyncClient") as client_type:
            client_type.return_value.__aenter__.return_value.get = AsyncMock(return_value=httpx.Response(
                200, json=payload, request=httpx.Request("GET", "http://comfy.test/object_info")
            ))
            response = self.client.get("/model/panorama/models")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([profile["id"] for profile in response.json()["models"]], ["realvisxl-v4"])

    def test_legacy_profiles_use_selected_checkpoint_and_save_actual_dimensions(self):
        for model_id, checkpoint, dimensions in (
            ("sd-1.5", "stable-diffusion-1-5.safetensors", (768, 384)),
            ("sd-2.1", "stable-diffusion-2-1.ckpt", (1024, 512)),
            ("dreamcreation", "dreamCreationVirtual3DECommerce_v10.safetensors", (768, 384)),
        ):
            with self.subTest(model=model_id), patch.object(
                model, "_panorama_inventory", AsyncMock(return_value=[{"id": model_id}])
            ), patch.object(model, "get_image", AsyncMock(return_value="image-data")) as generate, patch.object(
                model, "save_image_record", AsyncMock()
            ) as save:
                response = self.client.post("/model/generate/panorama", json=self.payload | {"model_id": model_id})
                self.assertEqual(response.status_code, 200)
                workflow = generate.await_args.args[0]
                self.assertEqual(workflow["4"]["inputs"]["ckpt_name"], checkpoint)
                metadata = save.await_args.kwargs["metadata"]
                self.assertEqual(metadata["model"], model_id)
                self.assertEqual((metadata["width"], metadata["height"]), dimensions)

    def test_malformed_inventory_returns_service_unavailable(self):
        with patch.object(model.httpx, "AsyncClient") as client_type:
            client_type.return_value.__aenter__.return_value.get = AsyncMock(return_value=httpx.Response(
                200, json={"unexpected": []}, request=httpx.Request("GET", "http://comfy.test/object_info")
            ))
            response = self.client.get("/model/panorama/models")
        self.assertEqual(response.status_code, 503)

    def test_high_requires_installed_processing_before_queueing(self):
        with patch.object(model, "_panorama_inventory", AsyncMock(return_value=[{"id": "realvisxl-v4"}])), patch.object(
            model, "_panorama_high_available", AsyncMock(return_value=False)
        ), patch.object(model, "get_image", AsyncMock()) as generate:
            response = self.client.post("/model/generate/panorama", json=self.payload | {"quality": "high"})
        self.assertEqual(response.status_code, 503)
        generate.assert_not_awaited()

    def test_high_saves_final_dimensions_and_uses_extended_gpu_job_timeout(self):
        with patch.object(model, "_panorama_inventory", AsyncMock(return_value=[{"id": "realvisxl-v4"}])), patch.object(
            model, "_panorama_high_available", AsyncMock(return_value=True)
        ), patch.object(model, "get_image", AsyncMock(return_value="4k-data")) as generate, patch.object(
            model, "save_image_record", AsyncMock()
        ) as save:
            response = self.client.post("/model/generate/panorama", json=self.payload | {"quality": "high"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(generate.await_args.kwargs, {"generation_timeout": 900.0})
        self.assertEqual(generate.await_args.args[0]["9"]["inputs"]["images"], ["28", 0])
        metadata = save.await_args.kwargs["metadata"]
        self.assertEqual((metadata["width"], metadata["height"]), (4096, 2048))
        self.assertEqual((metadata["base_width"], metadata["base_height"]), (1536, 768))
        self.assertEqual(metadata["quality"], "high")
        self.assertTrue(metadata["seam_repair"])