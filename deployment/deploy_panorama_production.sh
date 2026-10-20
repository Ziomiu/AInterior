#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

if [[ ${1:-} != --apply && ${1:-} != --check ]]; then
  printf '%s\n' \
    'Usage: bash deploy_panorama_production.sh --check | --apply' \
    'Operator-only panorama rollout on biomobi. --check makes no deployment changes.' \
    '--apply saves rollback configuration and updates only backend, frontend and ComfyUI.' \
    'No git pull, image build/pull, database changes, volume deletion or service-key rotation.' \
    'Do not use bash -x: the deployment preserves private runtime configuration.'
  exit 0
fi

PROD=/home/magisterka/AInterior
LAB=/home/lzegar/ainterior-public-lab-20261020-01
SAVED=/home/lzegar/ainterior-backups/20261019-115406
PROJECT=praca-inzynierska
FILES=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RELEASE=""

fail() {
  printf 'STOP: %s\n' "$*" >&2
  exit 1
}
report_failure() {
  local status=$1 line=$2
  printf 'STOP: panorama deployment failed at line %s (exit %s).\n' "$line" "$status" >&2
  if [[ -n "$RELEASE" ]]; then
    printf 'Private release/rollback directory: %s\n' "$RELEASE" >&2
  fi
  printf 'Do not rerun blindly. No database volumes have been removed.\n' >&2
  exit "$status"
}
trap 'report_failure "$?" "$LINENO"' ERR

[[ $(hostname) == biomobi ]] || fail 'Run this on biomobi, not the laptop.'
for executable in docker jq curl cp install cmp; do
  command -v "$executable" >/dev/null || fail "Missing command: $executable"
done
for file in \
  "$PROD/docker-compose-production.yml" "$SAVED/manual-override.yml" \
  "$LAB/backend/controllers/model.py" "$LAB/backend/schemas/generation.py" "$LAB/backend/utils/panorama.py" \
  "$LAB/frontend/dist/index.html" "$LAB/comfyui/custom_nodes/ainterior_panorama/__init__.py" \
  "$LAB/models/checkpoints/RealVisXL_V4.0.safetensors" \
  "$LAB/models/checkpoints/Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors" \
  "$LAB/models/upscale_models/RealESRGAN_x4plus.pth" \
  "$FILES/docker-compose.panorama-production.yml" "$FILES/comfy-production-paths.yml" "$FILES/nginx.production.conf"; do
  [[ -s "$file" ]] || fail "Missing rollout input: $file"
done
for service in backend frontend comfyui; do
  container="$PROJECT-$service-1"
  [[ $(docker inspect --format '{{.State.Running}}' "$container") == true ]] || fail "Not running: $container"
  actual=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container")
  [[ "$actual" == "$PROD/docker-compose-production.yml,$SAVED/manual-override.yml" ]] || fail "Compose files changed for $container; review the new configuration before deploying."
done
docker exec "$PROJECT-backend-1" python -c '
import os
import httpx
from dotenv import load_dotenv
load_dotenv()
key = os.getenv("FURNITURE_SERVICE_KEY")
assert key, "Production GPU queue key is unavailable"
response = httpx.get("http://127.0.0.1:5555/internal/gpu-queue/status", headers={"X-Service-Key": key}, timeout=15)
response.raise_for_status()
state = response.json()
assert not state.get("active") and not state.get("queue"), "Drain production GPU jobs before deployment"
print("Production GPU queue is idle")
'
docker exec "$PROJECT-comfyui-1" curl -fsS http://127.0.0.1:8188/queue \
  | jq -e '(.queue_running | length) == 0 and (.queue_pending | length) == 0' >/dev/null
curl -fsS --max-time 15 http://127.0.0.1:8190/queue \
  | jq -e '(.queue_running | length) == 0 and (.queue_pending | length) == 0' >/dev/null
runtime=$(docker exec "$PROJECT-backend-1" python -c '
import json
import os
from database.mongo import db, MONGO_URL
print(json.dumps({"key": os.environ["FURNITURE_SERVICE_KEY"], "database": db.name, "mongo_url": MONGO_URL}))
')
export FURNITURE_SERVICE_KEY=$(jq -er '.key | select(length > 0)' <<< "$runtime")
export PROD_DB=$(jq -er '.database | select(length > 0 and . != "ainterior_replacement_lab")' <<< "$runtime")
export PROD_MONGO_URL=$(jq -er '.mongo_url | select(length > 0)' <<< "$runtime")
export PANORAMA_FRONTEND_IMAGE=$(docker inspect --format '{{.Image}}' "$PROJECT-frontend-1")
export PANORAMA_BACKEND_IMAGE=$(docker inspect --format '{{.Image}}' "$PROJECT-backend-1")
export PANORAMA_COMFYUI_IMAGE=$(docker inspect --format '{{.Image}}' "$PROJECT-comfyui-1")
PANORAMA_RELEASE="$LAB" docker compose --project-directory "$PROD" -p "$PROJECT" \
  -f "$PROD/docker-compose-production.yml" -f "$SAVED/manual-override.yml" \
  -f "$FILES/docker-compose.panorama-production.yml" config --quiet
if [[ $1 == --check ]]; then
  printf 'Rollout inputs and queues are ready. No deployment changes were made.\n'
  exit 0
fi

RELEASE="$HOME/ainterior-releases/panorama-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RELEASE/backend/controllers" "$RELEASE/backend/schemas" "$RELEASE/backend/utils" \
  "$RELEASE/custom_nodes/ainterior_panorama" "$RELEASE/models/checkpoints" "$RELEASE/models/upscale_models"
printf 'Preparing private release: %s\n' "$RELEASE"
for file in controllers/model.py schemas/generation.py utils/panorama.py; do
  install -m 644 "$LAB/backend/$file" "$RELEASE/backend/$file"
done
cp -R --no-preserve=ownership "$LAB/frontend/dist" "$RELEASE/frontend"
install -m 644 "$LAB/comfyui/custom_nodes/ainterior_panorama/__init__.py" "$RELEASE/custom_nodes/ainterior_panorama/__init__.py"
for checkpoint in RealVisXL_V4.0.safetensors Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors; do
  cp --reflink=auto "$LAB/models/checkpoints/$checkpoint" "$RELEASE/models/checkpoints/$checkpoint"
done
cp --reflink=auto "$LAB/models/upscale_models/RealESRGAN_x4plus.pth" "$RELEASE/models/upscale_models/RealESRGAN_x4plus.pth"
for file in docker-compose.panorama-production.yml comfy-production-paths.yml nginx.production.conf; do
  install -m 644 "$FILES/$file" "$RELEASE/$file"
done
if [[ -f "$PROD/.env" ]]; then
  install -m 600 "$PROD/.env" "$RELEASE/compose.env"
else
  touch "$RELEASE/compose.env"
fi
printf '\nFURNITURE_SERVICE_KEY=' >> "$RELEASE/compose.env"
printf '%s\nPROD_DB=%s\nPROD_MONGO_URL=%s\nPANORAMA_RELEASE=%s\n' \
  "$FURNITURE_SERVICE_KEY" "$PROD_DB" "$PROD_MONGO_URL" "$RELEASE" >> "$RELEASE/compose.env"
unset runtime
export PANORAMA_RELEASE="$RELEASE"
for service in frontend backend comfyui; do
  image=$(docker inspect --format '{{.Image}}' "$PROJECT-$service-1")
  printf 'PANORAMA_%s_IMAGE=%s\n' "${service^^}" "$image" >> "$RELEASE/compose.env"
  docker tag "$image" "ainterior-panorama-rollback-$service:$(basename "$RELEASE")"
done
base() {
  docker compose --project-directory "$PROD" -p "$PROJECT" --env-file "$RELEASE/compose.env" \
    -f "$PROD/docker-compose-production.yml" -f "$SAVED/manual-override.yml" "$@"
}
updated() {
  docker compose --project-directory "$PROD" -p "$PROJECT" --env-file "$RELEASE/compose.env" \
    -f "$PROD/docker-compose-production.yml" -f "$SAVED/manual-override.yml" \
    -f "$RELEASE/docker-compose.panorama-production.yml" "$@"
}
base config --format json > "$RELEASE/before.json"
jq --arg frontend "$(docker inspect --format '{{.Image}}' "$PROJECT-frontend-1")" \
  --arg backend "$(docker inspect --format '{{.Image}}' "$PROJECT-backend-1")" \
  --arg comfyui "$(docker inspect --format '{{.Image}}' "$PROJECT-comfyui-1")" \
  '.services.frontend.image=$frontend | .services.backend.image=$backend | .services.comfyui.image=$comfyui' \
  "$RELEASE/before.json" > "$RELEASE/rollback.json"
updated config --quiet
updated config --format json > "$RELEASE/active.json"
cmp -s \
  <(jq -S 'del(.services.frontend,.services.backend,.services.comfyui)' "$RELEASE/before.json") \
  <(jq -S 'del(.services.frontend,.services.backend,.services.comfyui)' "$RELEASE/active.json") \
  || fail 'An unrelated service configuration changed; no services have been restarted.'
printf 'Stopping only the idle isolated lab services.\n'
docker compose -f "$LAB/deployment/docker-compose.lab.yml" stop comfyui backend frontend
printf 'Updating production ComfyUI and backend, then frontend.\n'
updated up -d --no-deps --no-build --pull never --wait --wait-timeout 180 comfyui backend
updated up -d --no-deps --no-build --pull never --wait --wait-timeout 180 frontend
curl -fsS --max-time 15 -o /dev/null http://127.0.0.1/
printf '\nPanorama rollout applied. Private release: %s\n' "$RELEASE"
printf 'Keep compose.env, active.json and rollback.json private; they contain runtime secrets.\n'
printf 'Rollback only the three app services with:\n'
printf 'docker compose --project-directory %q -p %q -f %q up -d --no-deps --no-build --pull never comfyui backend frontend\n' \
  "$PROD" "$PROJECT" "$RELEASE/rollback.json"