# Furniture Replacement Service

Standalone microservice: **segment → match to catalog → replace** for interior photos.
Built independent of the rest of the AInterior repo — talks to it only over HTTP.

Distilled from the 6-month research phase report. This document is the implementation
brief: what's already decided, what the architecture looks like, and how to plug this
into the main system later. Everything below is a *decision*, not an option to reconsider
mid-build — the research phase already answered these questions.

---

## 1. What the research phase settled

| Question | Answer | Why |
|---|---|---|
| Segmentation | **SAM 3** (text prompts), SAM 2.1 fallback (clicks) | SAM 3 removes the need for user clicks — automatic concept detection |
| Generic replacement (text prompt) | **LaMa → BrushNet**, two-stage | SSIM 0.919 / LPIPS 0.116 — best of 5 approaches benchmarked |
| Exact-product replacement (catalog photo) | **IP-Adapter** on SD1.5 Inpainting, `ip_scale≈0.85` | Text prompts don't reproduce a *specific* product reliably; image conditioning does |
| Catalog matching | **CLIP embeddings + Qdrant** | Standard, fast, swappable vector DB |
| Generation engine | **`diffusers` directly**, no ComfyUI | ComfyUI is a GUI tool, not a production dependency — adds latency and a JSON-workflow layer for no benefit here |
| AInterior's current inpainting | Broken (SSIM 0.744, worst of all 5) | Known `diffusers` SDXL+ControlNet channel-dimension conflict |

This service does **not** try to fix AInterior's existing pipeline. It's a clean, separate
implementation that AInterior's backend calls over HTTP once it's ready.

---

## 2. Architecture

```
                     ┌─────────────────────────────────────────┐
                     │         furniture-replace-service        │
                     │                                          │
  HTTP  ──────────►  │  FastAPI ──► JobQueue (1 worker, 1 GPU)  │ ──► results/ (static files)
                     │                   │                      │
                     │                   ▼                      │
                     │            ModelManager                  │
                     │   (single active heavy model on GPU,     │
                     │    swaps in/out, others parked on CPU)   │
                     │                                          │
                     │   SAM3 / SAM2.1 · CLIP · LaMa · BrushNet │
                     │   · IP-Adapter+SD1.5                     │
                     └─────────────────────────────────────────┘
                                   │
                                   ▼
                          Qdrant (catalog vectors)
```

**Why a job queue instead of handling requests synchronously.**
Inference takes 2–15 seconds per stage. Blocking an HTTP request for that long is
fine for a demo, bad for anything else. Every heavy operation (`segment`, `replace`)
returns a `job_id` immediately; the client polls `GET /v1/jobs/{id}`. `match` is fast
(CLIP forward pass + vector search, <200ms) and stays synchronous.

**Why one worker, not a concurrent pool.**
There's one GPU. Running two heavy models concurrently on it doesn't parallelize —
it thrashes VRAM and both jobs get slower. A single sequential worker is not a
limitation here, it's the correct design for the hardware. If this ever needs to
scale, the fix is more *replica containers* behind a load balancer, each with its
own GPU — not more threads fighting over one.

**Why models move between CPU and GPU instead of all loading at once.**
VRAM budget on the reference hardware (8–24GB) can't hold SAM 3 (~8GB) + BrushNet
(~8GB) + IP-Adapter/SD1.5 (~8GB) simultaneously on the low end. `ModelManager` keeps
every model's weights resident in **CPU RAM** after first load (so no disk re-read,
~0.3–0.5s to move to GPU) and only ever has **one heavy generative model on GPU**
at a time. CLIP stays GPU-resident always — it's <1GB and used on almost every
request. This is the single most important performance decision in this service;
see `app/models/manager.py`.

---

## 3. API surface

| Endpoint | Sync/Async | Purpose |
|---|---|---|
| `POST /v1/segment` | async → job | Find furniture in an image (text concepts or click point) |
| `POST /v1/match` | sync | Given a crop/mask, return top-K catalog products by visual similarity |
| `POST /v1/replace` | async → job | Replace masked region — `mode: "prompt"` or `mode: "reference"` |
| `GET /v1/jobs/{id}` | sync | Poll job status / result |
| `POST /v1/catalog/products` | sync | Ingest a catalog product (image + metadata) into Qdrant |
| `GET /v1/health` | sync | Model residency + VRAM usage |

Full request/response shapes: `app/schemas.py`.

---

## 4. Integration with AInterior — deliberately loose coupling

This service does not import AInterior code, share its database, or assume its
storage layer. Three ways an image reaches this service, all supported:

1. **Multipart upload** — AInterior's backend proxies the user's file straight through.
2. **`image_url`** — AInterior gives a fetchable URL (its own GridFS/S3/CDN); this
   service downloads it. Zero coupling to how AInterior stores files.
3. **`image_base64`** — for small images or quick testing.

Results are written to `results/<job_id>.png` and served as static files
(`GET /results/<job_id>.png`). AInterior's backend fetches that URL and re-uploads
to its own storage if it wants persistence — this service is not the system of record.

Auth: an optional `X-Service-Key` header, checked against `SERVICE_API_KEY` in
config. Real auth (JWT passthrough from AInterior's gateway) is an integration-phase
decision, not this service's problem — it just needs *a* gate for now.

**Docker**: this service is one container + one Qdrant container. Add both to the
main `docker-compose.yml` as additional services on the same network, or run this
`docker-compose.yml` standalone during development and merge later — either works,
nothing here assumes it owns the compose file.

---

## 5. What "done" looks like for this first pass

- [ ] `docker compose up` starts the service + Qdrant cleanly
- [ ] `POST /v1/segment` with `mode=text` returns labeled masks for a test photo
- [ ] `POST /v1/catalog/products` × ~30 products builds a usable Qdrant collection
- [ ] `POST /v1/match` returns sensible top-5 for a masked sofa
- [ ] `POST /v1/replace` (`mode=prompt`) runs LaMa→BrushNet and returns a result
- [ ] `POST /v1/replace` (`mode=reference`) runs IP-Adapter and visibly resembles the source product photo
- [ ] `GET /v1/health` shows correct model swapping (only one heavy model resident at a time)
- [ ] `frontend/index.html` exercises the whole flow manually, end to end

---

## 6. Run it

```bash
cp .env.example .env          # adjust paths / GPU device if needed
docker compose up --build
open frontend/index.html      # or serve it: python -m http.server -d frontend 8080
```

First request after a cold start is slow (model weights load from disk into CPU RAM
once). Every request after that only pays the CPU→GPU swap cost, not disk I/O.
