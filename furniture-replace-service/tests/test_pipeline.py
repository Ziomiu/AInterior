import asyncio
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("numpy") and importlib.util.find_spec("PIL"), "Requires imaging dependencies")
class CompositeTests(unittest.TestCase):
    def test_edge_blending_preserves_every_pixel_outside_mask(self):
        import numpy as np
        from PIL import Image

        spec = importlib.util.spec_from_file_location("pipeline_under_test", Path(__file__).resolve().parents[1] / "app/pipeline.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "torch": Mock(), "app.config": SimpleNamespace(settings=Mock()),
            "app.jobs.queue": SimpleNamespace(report_stage=Mock()),
            "app.models.manager": SimpleNamespace(model_manager=Mock()),
            "app.utils.images": SimpleNamespace(dilate_mask=Mock()),
        }):
            spec.loader.exec_module(module)
        original = Image.new("RGB", (32, 24), (20, 30, 40))
        generated = Image.new("RGB", (32, 24), (200, 210, 220))
        mask_array = np.zeros((24, 32), dtype=np.uint8)
        mask_array[6:18, 8:24] = 255
        result = np.array(module._composite(original, generated, Image.fromarray(mask_array), edge_blend=2))
        self.assertTrue(np.array_equal(result[mask_array == 0], np.array(original)[mask_array == 0]))
        self.assertGreater(result[6, 8, 0], 20)
        self.assertLess(result[6, 8, 0], 200)
        self.assertGreater(result[12, 16, 0], 190)


class PipelineStageTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.image = Image.new("RGB", (32, 24), "white")
        self.mask = Image.new("L", (32, 24), 255)
        self.stages = []
        self.loaded = []
        self.settings = SimpleNamespace(prompt_clean_first=True, inpaint_crop_padding=0, default_ip_scale=0.6, results_dir=Path("/unused"))

        def cleaning(*args):
            self.assertEqual(self.stages[-1], "cleaning")
            return self.image

        def generating(**kwargs):
            self.assertEqual(self.stages[-1], "generating")
            return self.image

        def reference(**kwargs):
            return SimpleNamespace(images=[generating(**kwargs)])

        self.models = {
            "lama": Mock(side_effect=cleaning),
            "brushnet": SimpleNamespace(inpaint=Mock(side_effect=generating)),
            "prompt_quality": SimpleNamespace(inpaint=Mock(side_effect=generating)),
            "ip_adapter": Mock(side_effect=reference),
        }

        @contextmanager
        def use_model(name):
            self.assertEqual(self.stages[-1], "loading")
            self.loaded.append(name)
            yield self.models[name]

        spec = importlib.util.spec_from_file_location("pipeline_stages", Path(__file__).resolve().parents[1] / "app/pipeline.py")
        self.pipeline = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "torch": Mock(), "app.config": SimpleNamespace(settings=self.settings),
            "app.jobs.queue": SimpleNamespace(report_stage=self.stages.append),
            "app.models.manager": SimpleNamespace(model_manager=SimpleNamespace(use=use_model, device="cpu")),
            "app.utils.images": SimpleNamespace(dilate_mask=lambda mask, iterations: mask),
        }):
            spec.loader.exec_module(self.pipeline)
        original_composite = self.pipeline._composite

        def composite(*args):
            self.assertEqual(self.stages[-1], "compositing")
            return original_composite(*args)

        self.pipeline._composite = composite

    def test_prompt_cleaning_quality_generation_and_composite_boundaries(self):
        final, cleaned = self.pipeline.run_prompt_replace(self.image, self.mask, "chair", None, 1, 1, quality="quality")
        self.assertEqual(self.stages, ["loading", "cleaning", "loading", "generating", "compositing"])
        self.assertEqual(self.loaded, ["lama", "prompt_quality"])
        self.assertIs(cleaned, self.image)
        self.assertEqual(final.size, self.image.size)

    def test_single_stage_has_no_cleaning_stage(self):
        self.settings.prompt_clean_first = False
        final, cleaned = self.pipeline.run_prompt_replace(self.image, self.mask, "chair", None, 1, 1)
        self.assertEqual(self.stages, ["loading", "generating", "compositing"])
        self.assertEqual(self.loaded, ["brushnet"])
        self.assertIsNone(cleaned)
        self.assertEqual(final.size, self.image.size)

    def test_reference_loading_generation_and_composite_boundaries(self):
        final = self.pipeline.run_reference_replace(self.image, self.mask, self.image, 0.5, 1, 1)
        self.assertEqual(self.stages, ["loading", "generating", "compositing"])
        self.assertEqual(self.loaded, ["ip_adapter"])
        self.assertEqual(final.size, self.image.size)

    def test_replace_reports_saving_before_each_disk_write(self):
        root = Path(__file__).resolve().parents[1]
        schema_spec = importlib.util.spec_from_file_location("app.schemas", root / "app/schemas.py")
        schemas = importlib.util.module_from_spec(schema_spec)
        with patch.dict(sys.modules, {"app.schemas": schemas}):
            schema_spec.loader.exec_module(schemas)
        submitted = Mock(return_value=SimpleNamespace(id="replace-job", status="queued"))

        def save(*args):
            self.assertEqual(self.stages[-1], "saving")

        saved = Mock(side_effect=save)
        route_spec = importlib.util.spec_from_file_location("replace_stages", root / "app/api/replace.py")
        route = importlib.util.module_from_spec(route_spec)
        with patch.dict(sys.modules, {
            "app.schemas": schemas,
            "app.config": SimpleNamespace(settings=self.settings),
            "app.gpu_queue": SimpleNamespace(ticket_id_from_request=lambda request: None),
            "app.jobs.queue": SimpleNamespace(job_queue=SimpleNamespace(submit=submitted), report_stage=self.stages.append),
            "app.catalog.store": SimpleNamespace(catalog_store=SimpleNamespace(get=lambda product_id: {"image_url": "/catalog-images/test.png"})),
            "app.pipeline": SimpleNamespace(run_prompt_replace=Mock(return_value=(self.image, self.image)), run_reference_replace=Mock(return_value=self.image)),
            "app.utils.images": SimpleNamespace(
                load_rgb=lambda ref: self.image, load_mask=lambda ref, size: self.mask,
                mask_to_bbox=lambda mask: mask.getbbox(), save_png=saved,
            ),
        }):
            route_spec.loader.exec_module(route)
        for mode in ("prompt", "reference"):
            with self.subTest(mode=mode):
                self.stages.clear()
                saved.reset_mock()
                req = schemas.ReplaceRequest(
                    image={"image_base64": "YWJj"}, mask={"image_base64": "YWJj"}, mode=mode,
                    prompt="chair", product_id="00000000-0000-0000-0000-000000000001", steps=1, guidance_scale=0,
                )
                response = asyncio.run(route.replace(req, None))
                self.assertEqual(response["status"], "queued")
                result = submitted.call_args.args[0]()
                expected_count = 2 if mode == "prompt" else 1
                self.assertEqual(saved.call_count, expected_count)
                self.assertEqual(self.stages, ["saving"] * expected_count)
                self.assertEqual(result["stage1_url"] is None, mode == "reference")


if __name__ == "__main__":
    unittest.main()