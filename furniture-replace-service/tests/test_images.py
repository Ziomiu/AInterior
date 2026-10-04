import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        super().__init__(detail)


def load_images(root):
    source = Path(__file__).resolve().parents[1] / "app/utils/images.py"
    spec = importlib.util.spec_from_file_location("images_under_test", source)
    module = importlib.util.module_from_spec(spec)
    settings = SimpleNamespace(
        results_dir=root / "results", catalog_images_dir=root / "catalog-images",
        max_image_bytes=32, max_image_side=4096, max_image_pixels=16_777_216,
    )
    image_api = SimpleNamespace(open=Mock(), DecompressionBombError=RuntimeError)
    with patch.dict(sys.modules, {
        "numpy": Mock(), "requests": Mock(),
        "fastapi": SimpleNamespace(HTTPException=HTTPException),
        "PIL": SimpleNamespace(Image=image_api, ImageOps=Mock()),
        "app.config": SimpleNamespace(settings=settings),
        "app.schemas": SimpleNamespace(ImageRef=Mock()),
    }):
        spec.loader.exec_module(module)
    return module


class ImageSafetyTests(unittest.TestCase):
    def test_traversal_cannot_escape_result_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            module = load_images(Path(directory))
            with self.assertRaises(HTTPException) as error:
                module._load_url("/results/../outside.png")
            self.assertEqual(error.exception.status_code, 403)
            module.Image.open.assert_not_called()

    def test_symlink_cannot_escape_result_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results").mkdir()
            (root / "outside.png").touch()
            (root / "results/link.png").symlink_to(root / "outside.png")
            module = load_images(root)
            with self.assertRaises(HTTPException) as error:
                module._load_url("/results/link.png")
            self.assertEqual(error.exception.status_code, 403)

    def test_oversized_base64_is_rejected_before_decode(self):
        module = load_images(Path("/tmp"))
        with self.assertRaises(HTTPException) as error:
            module._decode_base64("A" * 100)
        self.assertEqual(error.exception.status_code, 413)
        module.Image.open.assert_not_called()

    def test_oversized_dimensions_are_rejected_before_pixel_decode(self):
        module = load_images(Path("/tmp"))
        image = Mock(size=(5000, 100))
        module.Image.open.return_value = image
        ref = SimpleNamespace(image_base64="YWJj", image_url=None)
        with self.assertRaises(HTTPException) as error:
            module._resolve(ref)
        self.assertEqual(error.exception.status_code, 413)
        image.load.assert_not_called()
        image.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()