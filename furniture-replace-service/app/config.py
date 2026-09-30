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

    # ── Runtime ──────────────────────────────────────────────────────────────
    device: str = Field("cuda", description="'cuda' or 'cpu'")
    service_api_key: str | None = Field(
        None, description="If set, /v1/* requires header X-Service-Key: <this>"
    )
    # How long a heavy model may sit idle on the GPU before the reaper offloads it.
    model_idle_offload_seconds: int = 180

    # ── Storage ──────────────────────────────────────────────────────────────
    # A single data root keeps weights, results and catalog images together so a
    # single Docker volume persists everything (see docker-compose.yml).
    data_dir: Path = Path("./data")

    # ── Vector DB ────────────────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "catalog_products"

    # ── Model ids ────────────────────────────────────────────────────────────
    # Segmentation: click-driven. The user clicks the object to replace and SAM
    # 2.1 returns its mask — no text prompts in the interactive path.
    sam2_model: str = "facebook/sam2.1-hiera-large"

    # Matching: CLIP embeddings, cosine-searched in Qdrant.
    clip_model: str = "openai/clip-vit-base-patch32"
    clip_embed_dim: int = 512

    # Replace / prompt mode (two-stage): LaMa cleans the region, BrushNet paints
    # the new object with strong background preservation.
    lama_model: str = "big-lama"  # resolved by simple-lama-inpainting
    brushnet_base_model: str = "runwayml/stable-diffusion-v1-5"
    brushnet_model: str = "data/weights/brushnet_random_mask"  # local checkpoint dir

    # Replace / reference mode: SD1.5-inpainting + IP-Adapter for exact-product
    # fidelity from a catalog photo.
    sd_inpaint_model: str = "runwayml/stable-diffusion-inpainting"
    ip_adapter_repo: str = "h94/IP-Adapter"
    ip_adapter_subfolder: str = "models"
    ip_adapter_weight: str = "ip-adapter_sd15.bin"

    # ── Inference defaults ───────────────────────────────────────────────────
    default_ip_scale: float = 0.85
    default_steps: int = 30
    default_guidance_scale: float = 7.5

    # ── Derived paths (created on startup) ───────────────────────────────────
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
