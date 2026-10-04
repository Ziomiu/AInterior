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


if __name__ == "__main__":
    unittest.main()