import torch


class PanoramaSeam:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "prepare"
    CATEGORY = "AInterior/panorama"

    def prepare(self, image):
        width = image.shape[2]
        shifted = torch.roll(image, width // 2, dims=2)
        distance = (torch.arange(width, device=image.device) - width // 2).abs()
        radius = max(32, width // 16)
        mask = ((radius - distance).float() / max(8, radius // 4)).clamp(0, 1)
        mask = mask[None, None, :].expand(image.shape[0], image.shape[1], width)
        return shifted, mask


class PanoramaWrap:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"original": ("IMAGE",), "repaired": ("IMAGE",), "mask": ("MASK",)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "restore"
    CATEGORY = "AInterior/panorama"

    def restore(self, original, repaired, mask):
        blended = torch.lerp(original, repaired, mask.unsqueeze(-1).to(original))
        image = torch.roll(blended, -(original.shape[2] // 2), dims=2)
        return (torch.cat((image[:, :, -32:], image, image[:, :, :32]), dim=2),)


class PanoramaUnpad:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",), "reference": ("IMAGE",)}}

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "crop"
    CATEGORY = "AInterior/panorama"

    def crop(self, image, reference):
        original_width = reference.shape[2]
        scale, remainder = divmod(image.shape[2], original_width + 64)
        if remainder or scale < 1 or image.shape[1] != reference.shape[1] * scale:
            raise ValueError("Upscaler must preserve the padded panorama aspect ratio")
        border = 32 * scale
        return (image[:, :, border:-border],)


NODE_CLASS_MAPPINGS = {
    "AInteriorPanoramaSeam": PanoramaSeam,
    "AInteriorPanoramaWrap": PanoramaWrap,
    "AInteriorPanoramaUnpad": PanoramaUnpad,
}