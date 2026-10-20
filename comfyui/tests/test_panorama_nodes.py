import importlib.util
from pathlib import Path
import unittest

import torch


module_path = Path(__file__).resolve().parents[1] / "custom_nodes/ainterior_panorama/__init__.py"
spec = importlib.util.spec_from_file_location("panorama_nodes", module_path)
nodes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nodes)


class PanoramaNodeTests(unittest.TestCase):
    def test_shift_and_mask_cover_original_join(self):
        image = torch.rand(2, 128, 256, 3)
        shifted, mask = nodes.PanoramaSeam().prepare(image)
        torch.testing.assert_close(shifted, torch.roll(image, 128, dims=2))
        self.assertEqual(mask.shape, (2, 128, 256))
        self.assertTrue(torch.all(mask[:, :, 128] == 1))
        self.assertTrue(torch.all(mask[:, :, :96] == 0))
        self.assertTrue(torch.all(mask[:, :, 161:] == 0))
        self.assertTrue(torch.any((mask > 0) & (mask < 1)))

    def test_identity_repair_roundtrips_with_correct_horizontal_padding(self):
        image = torch.rand(1, 128, 256, 3)
        shifted, mask = nodes.PanoramaSeam().prepare(image)
        padded, = nodes.PanoramaWrap().restore(shifted, shifted, mask)
        torch.testing.assert_close(padded[:, :, 32:-32], image)
        torch.testing.assert_close(padded[:, :, :32], image[:, :, -32:])
        torch.testing.assert_close(padded[:, :, -32:], image[:, :, :32])
        enlarged = padded.repeat_interleave(4, dim=1).repeat_interleave(4, dim=2)
        cropped, = nodes.PanoramaUnpad().crop(enlarged, image)
        self.assertEqual(cropped.shape, (1, 512, 1024, 3))
        torch.testing.assert_close(cropped, image.repeat_interleave(4, dim=1).repeat_interleave(4, dim=2))

    def test_repair_preserves_pixels_outside_mask(self):
        image = torch.rand(1, 128, 256, 3)
        shifted, mask = nodes.PanoramaSeam().prepare(image)
        padded, = nodes.PanoramaWrap().restore(shifted, torch.ones_like(shifted), mask)
        restored = torch.roll(padded[:, :, 32:-32], 128, dims=2)
        torch.testing.assert_close(restored[mask == 0], shifted[mask == 0])

    def test_crop_rejects_wrong_aspect_ratio(self):
        with self.assertRaises(ValueError):
            nodes.PanoramaUnpad().crop(torch.zeros(1, 128, 1024, 3), torch.zeros(1, 128, 256, 3))