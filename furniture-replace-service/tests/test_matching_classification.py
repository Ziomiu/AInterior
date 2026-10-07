import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class Tensor:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def norm(self, p, dim, keepdim):
        return np.linalg.norm(self.values, ord=p, axis=dim, keepdims=keepdim)

    def __truediv__(self, denominator):
        return Tensor(self.values / denominator)

    def __getitem__(self, index):
        return Tensor(self.values[index])

    def cpu(self):
        return self

    def numpy(self):
        return self.values


class MatchingClassificationTests(unittest.TestCase):
    def setUp(self):
        category_spec = importlib.util.spec_from_file_location(
            "mocked_categories", ROOT / "app/models/classification.py",
        )
        self.categories = importlib.util.module_from_spec(category_spec)
        category_spec.loader.exec_module(self.categories)
        spec = importlib.util.spec_from_file_location("mocked_matching", ROOT / "app/models/matching.py")
        self.matching = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "torch": SimpleNamespace(inference_mode=lambda: lambda function: function),
            "app.config": SimpleNamespace(settings=SimpleNamespace()),
            "app.models.manager": SimpleNamespace(model_manager=Mock()),
            "app.models.classification": self.categories,
        }):
            spec.loader.exec_module(self.matching)
        self.processor = Mock(return_value=SimpleNamespace(to=Mock(return_value={})))
        count = len(self.categories.CLASSIFICATION_LABELS)
        self.model = Mock()
        self.model.get_text_features.return_value = Tensor(np.eye(count) * 2)
        self.model.get_image_features.return_value = Tensor(np.eye(count)[[0]] * 3)
        self.embedder = self.matching.ClipEmbedder(self.model, self.processor)
        self.image = Image.new("RGB", (8, 8))

    def test_normalized_text_cache_survives_device_change(self):
        first = self.embedder.classify_object(self.image)
        self.embedder.to("cpu")
        second = self.embedder.classify_object(self.image)
        self.assertEqual(first["category"], "chair")
        self.assertEqual(second, first)
        self.model.get_text_features.assert_called_once()
        self.assertEqual(self.model.get_image_features.call_count, 2)
        text_calls = [call for call in self.processor.call_args_list if "text" in call.kwargs]
        self.assertEqual(len(text_calls), 1)
        self.assertEqual(text_calls[0].kwargs["text"], [
            f"a photo of a {label}" for label in self.categories.CLASSIFICATION_LABELS
        ])
        np.testing.assert_allclose(self.embedder._category_text_features, np.eye(len(self.categories.CLASSIFICATION_LABELS)))

    def test_catchall_uses_unknown_contract(self):
        count = len(self.categories.CLASSIFICATION_LABELS)
        index = self.categories.CLASSIFICATION_LABELS.index("other object")
        self.model.get_image_features.return_value = Tensor(np.eye(count)[[index]])
        self.assertEqual(self.embedder.classify_object(self.image)["category"], "unknown")


if __name__ == "__main__":
    unittest.main()