import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from schemas.generation import PanoramaRequest
from utils.panorama import PANORAMA_MODELS, available_panorama_models, build_panorama_workflow


class PanoramaTests(unittest.TestCase):
    def test_inventory_only_offers_installed_compatible_checkpoints(self):
        inventory = available_panorama_models([
            "stable-diffusion-xl.safetensors", "juggernaut-inpainting.safetensors",
            "RealVisXL_V4.0.safetensors",
        ])
        self.assertEqual([profile["id"] for profile in inventory], ["realvisxl-v4", "sdxl-base"])
        self.assertEqual(available_panorama_models([]), [])

    def test_each_profile_builds_a_native_resolution_workflow_without_mutating_template(self):
        template_path = Path(__file__).resolve().parents[1] / "workflows_api/txt2img.json"
        template = json.loads(template_path.read_text())
        original = json.dumps(template)
        for model_id, profile in PANORAMA_MODELS.items():
            with self.subTest(model=model_id):
                workflow = build_panorama_workflow(template, model_id, "  Exhibition room  ", "stairs", 42)
                self.assertEqual(workflow["4"]["inputs"]["ckpt_name"], profile["checkpoint"])
                self.assertEqual(workflow["5"]["inputs"], {
                    "width": profile.get("width", 1536),
                    "height": profile.get("height", 768), "batch_size": 1,
                })
                self.assertEqual(workflow["3"]["inputs"]["sampler_name"], "dpmpp_2m")
                self.assertEqual(workflow["3"]["inputs"]["scheduler"], "karras")
                self.assertEqual(workflow["3"]["inputs"]["seed"], 42)
                self.assertIn("equirectangular projection", workflow["6"]["inputs"]["text"])
                self.assertTrue(workflow["6"]["inputs"]["text"].endswith("Exhibition room"))
                self.assertTrue(workflow["7"]["inputs"]["text"].endswith("stairs"))
        self.assertEqual(json.dumps(template), original)

    def test_installed_legacy_text_to_image_models_are_selectable_at_bounded_2_to_1_sizes(self):
        inventory = available_panorama_models([
            "stable-diffusion-1-5.safetensors", "stable-diffusion-2-1.ckpt",
            "dreamCreationVirtual3DECommerce_v10.safetensors", "sd-v1-5-inpainting.safetensors",
        ])
        self.assertEqual([profile["id"] for profile in inventory], ["sd-1.5", "sd-2.1", "dreamcreation"])
        self.assertEqual([(profile["width"], profile["height"]) for profile in inventory], [
            (768, 384), (1024, 512), (768, 384),
        ])

    def test_request_rejects_blank_brief_and_unbounded_seed(self):
        for changes in ({"brief": "   "}, {"brief": "x" * 1501}, {"seed": -1}, {"seed": 2**32}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                PanoramaRequest(**({"model_id": "sdxl-base", "brief": "room", "seed": 42} | changes))

    def test_high_adds_seam_repair_and_wrap_padded_learned_upscale_for_every_model(self):
        template = json.loads((Path(__file__).resolve().parents[1] / "workflows_api/txt2img.json").read_text())
        for model_id in PANORAMA_MODELS:
            with self.subTest(model=model_id):
                draft = build_panorama_workflow(template, model_id, "room", "", 42)
                high = build_panorama_workflow(template, model_id, "room", "", 42, "high")
                self.assertEqual(draft["9"]["inputs"]["images"], ["8", 0])
                self.assertEqual(high["5"], draft["5"])
                self.assertEqual(high["9"]["inputs"]["images"], ["28", 0])
                self.assertEqual(high["22"]["inputs"]["latent_image"], ["21", 0])
                self.assertEqual(high["26"]["inputs"]["image"], ["24", 0])
                self.assertEqual(high["28"]["inputs"]["width"], 4096)
                self.assertEqual(high["28"]["inputs"]["height"], 2048)

    def test_quality_is_bounded_and_defaults_to_draft(self):
        payload = {"model_id": "sdxl-base", "brief": "room", "seed": 42}
        self.assertEqual(PanoramaRequest(**payload).quality, "draft")
        self.assertEqual(PanoramaRequest(**payload, quality="high").quality, "high")
        with self.assertRaises(ValidationError):
            PanoramaRequest(**payload, quality="8k")