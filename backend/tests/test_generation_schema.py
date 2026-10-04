import unittest
from pydantic import ValidationError

from schemas.generation import TextToImageRequest


class TextToImageSchemaTests(unittest.TestCase):
    def valid_request(self, **overrides):
        values = {
            "model_version": "xl",
            "prompt": "accessible exhibition interior",
            "negative_prompt": "text, watermark",
            "guidance_scale": 7,
            "width": 1024,
            "height": 512,
            "seed": 1,
        }
        return {**values, **overrides}


    def test_accepts_360_panorama_dimensions(self):
        request = TextToImageRequest(**self.valid_request())

        self.assertEqual((request.width, request.height), (1024, 512))


    def test_rejects_unsupported_dimensions(self):
        for dimension in (0, 63, 65, 1088):
            with self.subTest(dimension=dimension), self.assertRaises(ValidationError):
                TextToImageRequest(**self.valid_request(width=dimension))


    def test_rejects_prompts_over_limit(self):
        with self.assertRaises(ValidationError):
            TextToImageRequest(**self.valid_request(prompt="x" * 2001))


if __name__ == "__main__":
    unittest.main()