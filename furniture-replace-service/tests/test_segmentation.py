import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class ReadOnlyPredictor:
    def __init__(self):
        self.model = Mock()
        self.reset_predictor = Mock()

    @property
    def device(self):
        return self.model.device


def load_segmentation():
    source = Path(__file__).resolve().parents[1] / "app/models/segmentation.py"
    spec = importlib.util.spec_from_file_location("segmentation_under_test", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "torch": SimpleNamespace(inference_mode=lambda: lambda fn: fn),
        "numpy": Mock(), "PIL": SimpleNamespace(Image=Mock()),
        "app.config": SimpleNamespace(settings=Mock()),
        "app.models.manager": SimpleNamespace(model_manager=Mock()),
    }):
        spec.loader.exec_module(module)
    return module


class FakeMasks:
    def __init__(self, masks):
        self.masks = masks

    def __getitem__(self, indices):
        index, point_y, point_x = indices
        return self.masks[index][point_y][point_x]


class SegmenterTests(unittest.TestCase):
    def test_negative_click_overrides_higher_iou(self):
        masks = FakeMasks([[[1, 1]], [[1, 0]]])
        result = load_segmentation()._best_mask_index(masks, [0.99, 0.8], [(0, 0), (1, 0)], [1, 0])
        self.assertEqual(result, 1)

    def test_iou_breaks_equal_click_agreement(self):
        masks = FakeMasks([[[1, 0]], [[1, 0]]])
        result = load_segmentation()._best_mask_index(masks, [0.7, 0.9], [(0, 0), (1, 0)], [1, 0])
        self.assertEqual(result, 1)

    def test_device_swap_does_not_write_predictor_property(self):
        predictor = ReadOnlyPredictor()
        segmenter = load_segmentation().Segmenter(predictor)
        self.assertIs(segmenter.to("cuda"), segmenter)
        predictor.model.to.assert_called_once_with("cuda")
        predictor.reset_predictor.assert_not_called()

    def test_offload_clears_cached_image_features(self):
        predictor = ReadOnlyPredictor()
        segmenter = load_segmentation().Segmenter(predictor)
        segmenter.to("cpu")
        predictor.model.to.assert_called_once_with("cpu")
        predictor.reset_predictor.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()