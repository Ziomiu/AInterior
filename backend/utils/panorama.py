import copy

PANORAMA_UPSCALER = "RealESRGAN_x4plus.pth"


PANORAMA_MODELS = {
    "realvisxl-v4": {
        "label": "RealVisXL V4 - realistic interiors",
        "checkpoint": "RealVisXL_V4.0.safetensors",
        "guidance_scale": 5.0,
    },
    "juggernaut-xl-v9": {
        "label": "Juggernaut XL V9 - architectural detail",
        "checkpoint": "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
        "guidance_scale": 5.5,
    },
    "sdxl-base": {
        "label": "SDXL Base - general purpose",
        "checkpoint": "stable-diffusion-xl.safetensors",
        "guidance_scale": 5.0,
    },
    "sd-1.5": {
        "label": "Stable Diffusion 1.5",
        "checkpoint": "stable-diffusion-1-5.safetensors",
        "guidance_scale": 7.0,
        "width": 768,
        "height": 384,
    },
    "sd-2.1": {
        "label": "Stable Diffusion 2.1",
        "checkpoint": "stable-diffusion-2-1.ckpt",
        "guidance_scale": 7.0,
        "width": 1024,
        "height": 512,
    },
    "dreamcreation": {
        "label": "DreamCreation Virtual 3D",
        "checkpoint": "dreamCreationVirtual3DECommerce_v10.safetensors",
        "guidance_scale": 7.0,
        "width": 768,
        "height": 384,
    },
}

PANORAMA_PROMPT = (
    "equirectangular projection, full 360 degree panorama, immersive architectural interior, "
    "continuous room wrapping around the camera, camera at eye level in the center of the room, "
    "straight continuous horizon through the middle, ceiling above, floor below, "
    "left and right edges connect, coherent perspective, realistic materials, natural lighting"
)
PANORAMA_NEGATIVE = (
    "text, watermark, border, frame, collage, split screen, tiny planet, fisheye lens, "
    "tilted horizon, distorted architecture, warped walls, duplicated furniture, blurry, low quality"
)


def available_panorama_models(checkpoints):
    return [
        {
            "id": model_id, "label": profile["label"],
            "width": profile.get("width", 1536), "height": profile.get("height", 768),
        }
        for model_id, profile in PANORAMA_MODELS.items()
        if profile["checkpoint"] in checkpoints
    ]


def build_panorama_workflow(template, model_id, brief, negative_prompt, seed, quality="draft"):
    if quality not in ("draft", "high"):
        raise ValueError("Unknown panorama quality")
    profile = PANORAMA_MODELS[model_id]
    workflow = copy.deepcopy(template)
    workflow["4"]["inputs"]["ckpt_name"] = profile["checkpoint"]
    workflow["3"]["inputs"].update({
        "seed": seed, "steps": 32, "cfg": profile["guidance_scale"],
        "sampler_name": "dpmpp_2m", "scheduler": "karras",
    })
    workflow["5"]["inputs"].update({
        "width": profile.get("width", 1536), "height": profile.get("height", 768), "batch_size": 1,
    })
    workflow["6"]["inputs"]["text"] = f"{PANORAMA_PROMPT}. {brief.strip()}"
    workflow["7"]["inputs"]["text"] = f"{PANORAMA_NEGATIVE}, {negative_prompt.strip()}"
    if quality == "high":
        workflow.update({
            "20": {"class_type": "AInteriorPanoramaSeam", "inputs": {"image": ["8", 0]}},
            "21": {"class_type": "VAEEncodeForInpaint", "inputs": {
                "pixels": ["20", 0], "mask": ["20", 1], "vae": ["4", 2], "grow_mask_by": 0,
            }},
            "22": {"class_type": "KSampler", "inputs": {
                **workflow["3"]["inputs"], "latent_image": ["21", 0], "steps": 20, "denoise": 0.6,
            }},
            "23": {"class_type": "VAEDecode", "inputs": {"samples": ["22", 0], "vae": ["4", 2]}},
            "24": {"class_type": "AInteriorPanoramaWrap", "inputs": {
                "original": ["20", 0], "repaired": ["23", 0], "mask": ["20", 1],
            }},
            "25": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": PANORAMA_UPSCALER}},
            "26": {"class_type": "ImageUpscaleWithModel", "inputs": {
                "upscale_model": ["25", 0], "image": ["24", 0],
            }},
            "27": {"class_type": "AInteriorPanoramaUnpad", "inputs": {
                "image": ["26", 0], "reference": ["8", 0],
            }},
            "28": {"class_type": "ImageScale", "inputs": {
                "image": ["27", 0], "width": 4096, "height": 2048,
                "upscale_method": "lanczos", "crop": "disabled",
            }},
        })
        workflow["9"]["inputs"]["images"] = ["28", 0]
    return workflow