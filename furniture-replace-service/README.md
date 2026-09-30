# Furniture Replacement Service

Standalone microservice: **click-segment → match to catalog → replace** for
interior photos. Built independent of the rest of the AInterior repo — talks to
it only over HTTP.

This is a POC implementation distilled from the research phase, with two
deliberate deviations from the original brief (both requested):

- **Segmentation is click-only, using SAM 2.1** — no text-prompt / automatic
  detection in the interactive path. The user clicks the object to replace.
- **SAM 3 is used only offline**, in `scripts/build_library.py`, to auto-cut
  clean product photos when building your own furniture library. It is never on
  the request hot path.

---

## 1. What the research phase settled

| Question | Answer | Why |
|---|---|---|
| Interactive segmentation | **SAM 2.1, click prompts** | Precise, deterministic, no text-model ambiguity; user points at the object |
| Furniture-library cutouts (offline) | **SAM 3 / SAM 2 auto / rembg** | Background removal for better embeddings + reference fidelity |
| Generic replacement (text prompt) | **LaMa → BrushNet**, two-stage | SSIM 0.919 / LPIPS 0.116 — best of 5 approaches benchmarked |
| Exact-product replacement (catalog photo) | **IP-Adapter** on SD1.5 Inpainting, `ip_scale≈0.85` | Text can't reproduce a *specific* product; image conditioning does |
| Catalog matching | **CLIP embeddings + Qdrant** | Standard, fast, swappable vector DB |
| Generation engine | **`diffusers` directly**, no ComfyUI | ComfyUI is a GUI tool; a JSON-workflow layer adds latency for no benefit here |

This service does **not** try to fix AInterior's existing ComfyUI inpainting
pipeline. It's a clean, separate implementation the main backend calls over HTTP.

---

## 2. Architecture

```
                     ┌─────────────────────────────────────────┐
                     │        furniture-replace-service         │
  HTTP  ──────────►  │  FastAPI ──► JobQueue (1 worker, 1 GPU)  │ ──► results/ (static files)
                     │                   │                      │
                     │                   ▼                      │
                     │            ModelManager                  │
                     │   (one heavy model on GPU at a time,     │
                     │    others parked in CPU RAM)             │
                     │                                          │
                     │   SAM 2.1 · CLIP · LaMa · BrushNet       │
                     │   · IP-Adapter + SD1.5                   │
                     └─────────────────────────────────────────┘
                                   │
                                   ▼
                          Qdrant (catalog vectors)
```

- **Job queue, one worker.** Inference takes seconds; heavy ops (`segment`,
  `replace`) return a `job_id` immediately and the client polls
  `GET /v1/jobs/{id}`. `match` is fast (CLIP + vector search) and stays sync.
  One GPU ⇒ one sequential worker is the correct design, not a limitation.
- **ModelManager** (`app/models/manager.py`) loads each model's weights from disk
  **once** into CPU RAM, then only ever moves tensors CPU↔GPU (~0.3–0.5s), keeping
  at most one heavy generative model on the GPU. CLIP stays GPU-resident.

---

## 3. API surface

| Endpoint | Sync/Async | Purpose |
|---|---|---|
| `POST /v1/segment` | async → job | SAM 2.1 mask from user click point(s) |
| `POST /v1/match` | sync | Top-K catalog products by visual similarity to a masked object |
| `POST /v1/replace` | async → job | Replace masked region — `mode: "prompt"` or `mode: "reference"` |
| `GET /v1/jobs/{id}` | sync | Poll job status / result |
| `POST /v1/catalog/products` | sync | Ingest a catalog product (image + metadata) into Qdrant |
| `GET /v1/catalog/products` | sync | List indexed products |
| `GET /v1/health` | sync | Model residency + VRAM + queue depth |

Full request/response shapes: `app/schemas.py`.

Three ways to pass an image everywhere (`ImageRef`): `image_base64`, `image_url`
(external URL **or** a local static path this service serves, e.g.
`/results/masks/<id>.png`), so AInterior never has to change how it stores files.

---

## 4. Models & weights

Most weights download automatically from the Hugging Face Hub on first use:

- **SAM 2.1** — `facebook/sam2.1-hiera-large` (installed from GitHub, see Dockerfile)
- **CLIP** — `openai/clip-vit-base-patch32`
- **LaMa** — via `simple-lama-inpainting`
- **SD1.5 inpainting + IP-Adapter** — `runwayml/stable-diffusion-inpainting` + `h94/IP-Adapter`

**BrushNet** (best prompt-mode quality) needs its `BrushNetModel` checkpoint and
the BrushNet diffusers classes, which aren't in core `diffusers`. Point
`BRUSHNET_MODEL` at a local checkpoint dir. **If BrushNet isn't available, prompt
mode automatically falls back to stock SD1.5 inpainting** so the service still
runs end-to-end (see `app/models/inpainting.py`).

---

## 5. Run it

```bash
./run.sh                 # build + start (service on :8000, qdrant on :6333)
./run.sh --prefetch      # ... and pre-download all weights (~10-13 GB, one time)
```

`run.sh` is safe to run next to the main AInterior stack — separate ports and its
own weight cache under `./data`; it only shares the physical GPU.

### Build the furniture library

Requirements:
- **Product photos**, one product each, ideally clean/studio shots. ~30+ for a
  useful demo. `.jpg/.png/.webp`.
- Metadata is encoded in the filename: `<category>__<name>__<price>.jpg`
  (price optional), e.g. `sofa__Karlstad 3-seater beige__1899.jpg`.

Steps:

```bash
# 1. Drop raw product photos here (this maps to /srv/data/raw in the container):
cp my_photos/*.jpg data/raw/

# 2. (Optional) remove backgrounds for cleaner embeddings + better reference fidelity.
#    Runs inside the container so the GPU + sam2 deps are available:
docker compose run --rm furniture-replace \
    python scripts/build_library.py /srv/data/raw /srv/data/cutouts --backend sam2
#    backends: sam2 (GPU, default) · rembg (CPU, needs `pip install rembg onnxruntime`)
#              · sam3 (optional, only if the SAM 3 package is installed)

# 3. Index them into Qdrant (host Python is fine — only needs `requests`):
python scripts/seed_catalog.py data/cutouts --api http://localhost:8000
#    (skip step 2 and seed data/raw directly if you don't want cutouts)

# 4. Verify:
curl http://localhost:8000/v1/catalog/products | jq
```

After seeding, `POST /v1/match` and reference-mode `/v1/replace` become useful.

Local (no Docker) dev:

```bash
pip install -r requirements.txt
pip install "git+https://github.com/facebookresearch/sam2.git"
uvicorn app.main:app --reload            # expects Qdrant at QDRANT_URL
```

First request after a cold start is slow (weights load disk → CPU RAM once);
`./run.sh --prefetch` does this ahead of time. Every request after only pays the
CPU→GPU swap, not disk I/O.

---

## 6. Integration with AInterior — deliberately loose coupling

No shared imports, database, or storage. When you're ready to add this as a new
mode in the main system:

1. AInterior's backend proxies the user's photo here (`image_base64` or a
   fetchable `image_url` from its GridFS/S3).
2. Frontend collects the user's click, calls `/v1/segment`, then `/v1/match`
   and/or `/v1/replace`.
3. Results are served at `/results/<id>.png`; AInterior fetches and re-uploads to
   its own storage if it wants persistence — this service is not the system of record.

Auth for now: optional `X-Service-Key` header vs `SERVICE_API_KEY`. Real JWT
passthrough is an integration-phase decision.

Add both services (`furniture-replace`, `qdrant`) into the main
`docker-compose.yml` on the same network, or run this compose file standalone.

---

## 7. Definition of done (this pass)

- [x] `docker compose up` starts the service + Qdrant cleanly
- [x] `POST /v1/segment` returns a mask for a clicked point
- [x] `POST /v1/catalog/products` builds a Qdrant collection
- [x] `POST /v1/match` returns sensible top-K for a masked object
- [x] `POST /v1/replace` (`mode=prompt`) runs LaMa→BrushNet (or SD1.5 fallback)
- [x] `POST /v1/replace` (`mode=reference`) runs IP-Adapter from a product photo
- [x] `GET /v1/health` shows correct model swapping
- [x] `frontend/index.html` exercises the whole flow manually
