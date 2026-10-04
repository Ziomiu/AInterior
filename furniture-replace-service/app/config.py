"""
Central configuration. Everything tunable lives here and is overridable via
environment variables (see .env.example). Kept deliberately flat so the rest of
the service never reaches for os.environ directly.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    device: str = Field("cuda", description="'cuda' or 'cpu'")
    service_api_key: str | None = Field(
        None, description="If set, /v1/* requires header X-Service-Key: <this>"
    )
    gpu_queue_url: str = ""
    gpu_queue_acquire_timeout_seconds: int = Field(900, ge=1)
    gpu_queue_heartbeat_seconds: int = Field(5, ge=1)
    # How long a heavy model may sit idle on the GPU before the reaper offloads it.
    model_idle_offload_seconds: int = 180
    max_queued_jobs: int = Field(16, ge=1)
    max_job_history: int = Field(128, ge=1)

    # A single data root keeps weights, results and catalog images together so a
    # single Docker volume persists everything (see docker-compose.yml).
    data_dir: Path = Path("./data")
    max_image_bytes: int = Field(20 * 1024 * 1024, ge=1)
    max_image_side: int = Field(4096, ge=1)
    max_image_pixels: int = Field(16_777_216, ge=1)

    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "catalog_products"

    # Segmentation: click-driven. The user clicks the object to replace and SAM
    # 2.1 returns its mask — no text prompts in the interactive path.
    sam2_model: str = "facebook/sam2.1-hiera-large"

    clip_model: str = "openai/clip-vit-base-patch32"
    clip_embed_dim: int = 512

    lama_model: str = "big-lama"  # resolved by simple-lama-inpainting
    brushnet_base_model: str = "runwayml/stable-diffusion-v1-5"
    brushnet_model: str = "data/weights/brushnet_random_mask"  # local checkpoint dir

    sd_inpaint_model: str = "stable-diffusion-v1-5/stable-diffusion-inpainting"
    sd_inpaint_variant: str | None = "fp16"
    prompt_inpaint_model: str | None = None
    ip_adapter_repo: str = "h94/IP-Adapter"
    ip_adapter_subfolder: str = "models"
    ip_adapter_weight: str = "ip-adapter_sd15.bin"

    default_ip_scale: float = 0.85
    default_steps: int = 30
    default_guidance_scale: float = 7.5
    inpaint_crop_padding: int = Field(0, ge=0, le=512)
    prompt_clean_first: bool = False

    @property
    def weights_dir(self) -> Path:
        return self.data_dir / "weights"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"

    @property
    def masks_dir(self) -> Path:
        return self.results_dir / "masks"

    @property
    def catalog_images_dir(self) -> Path:
        return self.data_dir / "catalog-images"

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.weights_dir,
            self.results_dir,
            self.masks_dir,
            self.catalog_images_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
