from contextlib import contextmanager
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class FakeSegmenter:
    def segment_points(self, image, points, labels):
        return self.mask, self.score


class FakeClip:
    def classify_object(self, image):
        return self.classify(image)


class SegmentContractTests(unittest.TestCase):
    def setUp(self):
        self.segmenter = FakeSegmenter()
        self.segmenter.mask = np.zeros((24, 32), dtype=np.uint8)
        self.segmenter.mask[4:16, 4:16] = 1
        self.segmenter.score = 0.93
        self.clip = FakeClip()
        self.classification = {
            "category": "chair", "label": "chair", "confidence": 0.8,
            "uncertain": False, "confidence_kind": "relative_clip_score",
        }
        self.clip.classify = Mock(return_value=self.classification)
        self.stages = []
        self.save = Mock()
        self.crop = Mock(return_value=Image.new("RGB", (12, 12), "white"))
        self.submitted = Mock(return_value=SimpleNamespace(id="segment-job", status="queued"))

        @contextmanager
        def use_model(name):
            yield self.segmenter if name == "segmenter" else self.clip

        modules = {}
        for name, path in (("app.schemas", "app/schemas.py"),
                           ("app.models.classification", "app/models/classification.py")):
            spec = importlib.util.spec_from_file_location(name, ROOT / path)
            module = importlib.util.module_from_spec(spec)
            modules[name] = module
            with patch.dict(sys.modules, modules):
                spec.loader.exec_module(module)
        self.schemas = modules["app.schemas"]
        self.categories = modules["app.models.classification"]
        modules.update({
            "app.config": SimpleNamespace(settings=SimpleNamespace(masks_dir=Path("/unused/masks"))),
            "app.gpu_queue": SimpleNamespace(ticket_id_from_request=lambda request: None),
            "app.jobs.queue": SimpleNamespace(job_queue=SimpleNamespace(submit=self.submitted), report_stage=self.stages.append),
            "app.models.manager": SimpleNamespace(model_manager=SimpleNamespace(use=use_model)),
            "app.models.matching": SimpleNamespace(ClipEmbedder=FakeClip),
            "app.models.segmentation": SimpleNamespace(Segmenter=FakeSegmenter),
            "app.utils.images": SimpleNamespace(
                load_rgb=lambda ref: Image.new("RGB", (32, 24)), mask_to_bbox=lambda mask: mask.getbbox(),
                save_png=self.save, crop_object_on_white=self.crop,
            ),
        })
        spec = importlib.util.spec_from_file_location("mocked_segment", ROOT / "app/api/segment.py")
        self.route = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.route)
        app = FastAPI()
        app.include_router(self.route.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()

    def execute(self, points=None):
        response = self.client.post("/v1/segment", json={
            "image": {"image_base64": "YWJj"}, "points": points or [{"x": 5, "y": 5}],
        })
        self.assertEqual(response.json(), {"job_id": "segment-job", "status": "queued"})
        return self.submitted.call_args.args[0]()

    def test_segment_preserves_sam_score_and_classifies_masked_crop(self):
        result = self.execute()
        self.assertEqual(result["classification"], self.classification)
        self.assertEqual(result["score"], 0.93)
        self.assertFalse(result["mask_review_required"])
        self.assertEqual(result["bbox"], [4, 4, 16, 16])
        self.clip.classify.assert_called_once_with(self.crop.return_value)
        self.assertEqual(self.stages, ["loading", "segmenting", "loading", "classifying", "saving"])
        self.save.assert_called_once()

    def test_classifier_failure_does_not_fail_segmentation(self):
        self.clip.classify.side_effect = RuntimeError("CLIP unavailable")
        with self.assertLogs("segment", level="ERROR"):
            result = self.execute()
        self.assertEqual(result["classification"], self.categories.unknown_classification())
        self.assertEqual(result["score"], 0.93)
        self.assertFalse(result["mask_review_required"])
        self.save.assert_called_once()

    def test_clip_loading_failure_does_not_fail_segmentation(self):
        use_model = self.route.model_manager.use

        def fail_clip_loading(name):
            if name == "clip":
                raise RuntimeError("CLIP cannot load")
            return use_model(name)

        with patch.object(self.route.model_manager, "use", side_effect=fail_clip_loading), \
             self.assertLogs("segment", level="ERROR"):
            result = self.execute()
        self.assertEqual(result["classification"], self.categories.unknown_classification())
        self.assertEqual(result["bbox"], [4, 4, 16, 16])
        self.save.assert_called_once()
        self.clip.classify.assert_not_called()

    def test_mask_review_for_score_and_coverage(self):
        for score, fill in ((0.69, False), (0.747, False), (0.849, False), (float("nan"), False), (0.93, True)):
            with self.subTest(score=score, fill=fill):
                mask = self.segmenter.mask.copy()
                if fill:
                    mask[:] = 1
                self.assertTrue(self.route._mask_review_required(mask, score, [(5, 5)], [1]))

    def test_clear_mask_at_review_threshold_can_be_ready(self):
        self.segmenter.score = 0.85
        self.assertFalse(self.execute()["mask_review_required"])

    def test_tiny_mask_requires_review_despite_click_agreement(self):
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[5, 5] = 1
        self.assertTrue(self.route._mask_review_required(mask, 0.99, [(5, 5)], [1]))

    def test_mask_review_for_click_disagreement(self):
        self.assertTrue(self.execute([{"x": 20, "y": 20}])["mask_review_required"])
        self.assertTrue(self.execute([
            {"x": 5, "y": 5}, {"x": 10, "y": 10, "label": 0},
        ])["mask_review_required"])
        self.assertFalse(self.execute([
            {"x": 5, "y": 5}, {"x": 20, "y": 20, "label": 0},
        ])["mask_review_required"])

    def test_empty_mask_skips_clip_and_requires_review(self):
        self.segmenter.mask[:] = 0
        result = self.execute()
        self.assertTrue(result["mask_review_required"])
        self.assertEqual(result["classification"], self.categories.unknown_classification())
        self.assertEqual(result["bbox"], [0, 0, 32, 24])
        self.clip.classify.assert_not_called()

    def test_job_schema_keeps_optional_live_stage(self):
        values = {"job_id": "segment-job", "status": "running", "created_at": 1, "updated_at": 2}
        self.assertIsNone(self.schemas.JobResponse(**values).stage)
        self.assertEqual(self.schemas.JobResponse(**values, stage="classifying").model_dump()["stage"], "classifying")

    def test_job_poll_endpoint_preserves_live_stage(self):
        values = {
            "job_id": "segment-job", "status": "running", "stage": "classifying",
            "created_at": 1, "updated_at": 2, "result": None, "error": None,
        }
        spec = importlib.util.spec_from_file_location("mocked_jobs", ROOT / "app/api/jobs.py")
        route = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "app.schemas": self.schemas,
            "app.jobs.queue": SimpleNamespace(job_queue=SimpleNamespace(
                get=lambda job_id: SimpleNamespace(as_dict=lambda: values),
            )),
        }):
            spec.loader.exec_module(route)
        app = FastAPI()
        app.include_router(route.router)
        with TestClient(app) as client:
            response = client.get("/v1/jobs/segment-job")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stage"], "classifying")
        self.assertIsNone(response.json()["result"])


if __name__ == "__main__":
    unittest.main()