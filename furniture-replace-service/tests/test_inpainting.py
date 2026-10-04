import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load_inpainting():
    source = Path(__file__).resolve().parents[1] / "app/models/inpainting.py"
    spec = importlib.util.spec_from_file_location("inpainting_under_test", source)
    module = importlib.util.module_from_spec(spec)
    torch = SimpleNamespace(
        dtype=object, float16="fp16", float32="fp32",
        cuda=SimpleNamespace(is_available=lambda: False),
    )
    config = SimpleNamespace(settings=SimpleNamespace(
        device="cpu", sd_inpaint_model="test-inpaint-model", sd_inpaint_variant="fp16",
        inpaint_crop_padding=64,
        prompt_inpaint_model=None,
    ))
    with patch.dict(sys.modules, {
        "torch": torch, "PIL": SimpleNamespace(Image=Mock()),
        "app.config": config, "app.models.manager": SimpleNamespace(model_manager=Mock()),
    }):
        spec.loader.exec_module(module)
    return module


class PromptInpainterTests(unittest.TestCase):
    def test_stock_diffusers_falls_back_to_sd15(self):
        module = load_inpainting()
        diffusers = ModuleType("diffusers")
        diffusers.AutoPipelineForInpainting = Mock()
        with patch.dict(sys.modules, {"diffusers": diffusers}):
            inpainter = module._load_brushnet()
        self.assertEqual(inpainter.backend, "sd15")
        inpainter.pipe.enable_attention_slicing.assert_not_called()
        diffusers.AutoPipelineForInpainting.from_pretrained.assert_called_once_with(
            "test-inpaint-model", torch_dtype="fp32",
            variant="fp16", use_safetensors=True,
            safety_checker=None, requires_safety_checker=False,
        )

    def test_inpaint_maps_arguments_and_returns_image(self):
        module = load_inpainting()
        pipe = Mock(return_value=SimpleNamespace(images=["generated"]))
        inpainter = module.PromptInpainter(pipe, "sd15")
        image = SimpleNamespace(width=768, height=512)
        result = inpainter.inpaint(
            image=image, mask="mask", prompt="chair", negative_prompt="blur",
            steps=12, guidance=6.0, generator="generator",
        )
        self.assertEqual(result, "generated")
        pipe.assert_called_once_with(
            image=image, mask_image="mask", width=768, height=512, prompt="chair", negative_prompt="blur",
            num_inference_steps=12, guidance_scale=6.0, generator="generator",
            padding_mask_crop=64,
        )

    def test_prompt_model_override_leaves_reference_model_unchanged(self):
        module = load_inpainting()
        module.settings.prompt_inpaint_model = "test-sdxl-model"
        diffusers = ModuleType("diffusers")
        diffusers.AutoPipelineForInpainting = Mock()
        with patch.dict(sys.modules, {"diffusers": diffusers}):
            module._load_brushnet()
        self.assertEqual(diffusers.AutoPipelineForInpainting.from_pretrained.call_args.args[0], "test-sdxl-model")
        self.assertEqual(module.settings.sd_inpaint_model, "test-inpaint-model")

    def test_crop_can_be_disabled_for_comparison(self):
        module = load_inpainting()
        module.settings.inpaint_crop_padding = 0
        pipe = Mock(return_value=SimpleNamespace(images=["generated"]))
        module.PromptInpainter(pipe, "sd15").inpaint(
            image=SimpleNamespace(width=768, height=512), mask="mask", prompt="chair",
            negative_prompt=None, steps=12, guidance=6.0, generator="generator",
        )
        self.assertNotIn("padding_mask_crop", pipe.call_args.kwargs)

    def test_device_swap_preserves_wrapper(self):
        module = load_inpainting()
        pipe = Mock()
        inpainter = module.PromptInpainter(pipe, "sd15")
        self.assertIs(inpainter.to("cuda"), inpainter)
        pipe.to.assert_called_once_with("cuda")


if __name__ == "__main__":
    unittest.main()