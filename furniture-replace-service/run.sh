#!/usr/bin/env bash
# Start furniture-replace-service alongside the main AInterior stack.
#
# It is fully independent (own ports 8000 + 6333, own weight cache under ./data),
# and only shares the physical GPU with the main stack. Safe to run at the same
# time as the ComfyUI stack — just keep an eye on VRAM if you generate on both.
#
# Usage:
#   ./run.sh              # build + start in the background
#   ./run.sh --prefetch   # ... then pre-download all model weights (~10-13 GB)
#   ./run.sh --logs       # start and follow logs
#   ./run.sh down         # stop this service (leaves the main stack untouched)

set -euo pipefail
cd "$(dirname "$0")"

if [[ "${1:-}" == "down" ]]; then
  docker compose down
  echo "furniture-replace-service stopped."
  exit 0
fi

command -v docker >/dev/null || { echo "ERROR: docker not found"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: 'docker compose' plugin not found"; exit 1; }

if ! docker info 2>/dev/null | grep -qi nvidia; then
  echo "WARNING: NVIDIA container runtime not detected. GPU inference may be unavailable."
  echo "         (The main stack already uses the GPU, so this is usually fine to ignore"
  echo "          if nvidia-smi works on the host.)"
fi

[[ -f .env ]] || { cp .env.example .env; echo "Created .env from .env.example"; }
mkdir -p data/weights data/results data/catalog-images data/raw data/cutouts

echo "Building & starting furniture-replace + qdrant …"
docker compose up -d --build

echo
echo "Waiting for the API to answer on http://localhost:8000/v1/health …"
for _ in $(seq 1 30); do
  if curl -sf http://localhost:8000/v1/health >/dev/null 2>&1; then
    echo "  ✓ up"
    break
  fi
  sleep 2
done

if [[ "${1:-}" == "--prefetch" ]]; then
  echo
  echo "Pre-downloading model weights (this is a one-time ~10-13 GB download) …"
  docker compose run --rm furniture-replace python scripts/prefetch_models.py
fi

echo
echo "─────────────────────────────────────────────────────────────"
echo "  Test console : http://localhost:8000/"
echo "  Health       : http://localhost:8000/v1/health"
echo "  Qdrant UI    : http://localhost:6333/dashboard"
echo "─────────────────────────────────────────────────────────────"
echo "  Next: build a furniture library — see README §Build the library"
echo

if [[ "${1:-}" == "--logs" ]]; then
  docker compose logs -f furniture-replace
fi
