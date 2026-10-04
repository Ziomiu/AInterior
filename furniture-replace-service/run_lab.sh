#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
export HF_HOME="${HF_HOME:-$PWD/data/weights/hf}"
export TORCH_HOME="${TORCH_HOME:-$PWD/data/weights/torch}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$PWD/data/weights/cache}"
export QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
export MODEL_IDLE_OFFLOAD_SECONDS="${MODEL_IDLE_OFFLOAD_SECONDS:-30}"

mode="${1:-api}"
if (( $# )); then shift; fi
case "$mode" in
  qdrant)
    export QDRANT__SERVICE__HOST=127.0.0.1
    export QDRANT__SERVICE__HTTP_PORT=6333
    export QDRANT__SERVICE__GRPC_PORT=6334
    export QDRANT__STORAGE__STORAGE_PATH="$PWD/data/qdrant"
    export QDRANT__TELEMETRY_DISABLED=true
    exec data/bin/qdrant "$@"
    ;;
  api)
    exec .venv-lab/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log "$@"
    ;;
  test)
    exec .venv-lab/bin/python -m unittest discover -s tests "$@"
    ;;
  prefetch)
    exec .venv-lab/bin/python scripts/prefetch_models.py "$@"
    ;;
  benchmark)
    exec .venv-lab/bin/python scripts/benchmark.py "$@"
    ;;
  *)
    printf 'Usage: bash run_lab.sh {api|qdrant|test|prefetch|benchmark} [args]\n' >&2
    exit 2
    ;;
esac