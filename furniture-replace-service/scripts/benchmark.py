from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import time

import numpy as np
import requests
from PIL import Image, ImageOps

from app.utils.images import dilate_mask

logger = logging.getLogger("benchmark")


def gpu_sample() -> dict | None:
    try:
        output = subprocess.check_output([
            "nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits", "--id=0",
        ], text=True, timeout=3)
        used, free, utilization = [int(value.strip()) for value in output.strip().split(",")]
        return {"used_mib": used, "free_mib": free, "utilization_percent": utilization}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def image_ref(image: Image.Image) -> dict:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {"image_base64": base64.b64encode(buffer.getvalue()).decode("ascii")}


def poll_job(session, api: str, job_id: str, timeout: float, samples: list | None = None) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if samples is not None:
            sample = gpu_sample()
            if sample is not None:
                samples.append(sample)
        response = session.get(f"{api}/v1/jobs/{job_id}", timeout=30)
        response.raise_for_status()
        job = response.json()
        if job["status"] == "done":
            return job["result"]
        if job["status"] == "failed":
            raise RuntimeError(f"Job {job_id} failed: {job.get('error')}")
        time.sleep(0.25)
    raise TimeoutError(f"Client stopped waiting for {job_id}; server inference is not cancelled")


def submit(session, api: str, route: str, payload: dict, timeout: float) -> tuple[dict, dict]:
    started = time.perf_counter()
    response = session.post(f"{api}/v1/{route}", json=payload, timeout=60)
    response.raise_for_status()
    samples = []
    result = poll_job(session, api, response.json()["job_id"], timeout, samples)
    elapsed = round(time.perf_counter() - started, 3)
    health = session.get(f"{api}/v1/health", timeout=30)
    health.raise_for_status()
    measurement = {"wall_seconds": elapsed, "health": health.json()}
    if samples:
        measurement["gpu_sampled_peak_mib"] = max(sample["used_mib"] for sample in samples)
        measurement["gpu_sampled_min_free_mib"] = min(sample["free_mib"] for sample in samples)
    return result, measurement


def fetch_image(session, api: str, path: str) -> Image.Image:
    if not path.startswith(("/results/", "/catalog-images/")):
        raise ValueError("Expected a service-local image path")
    response = session.get(f"{api}{path}", timeout=30)
    response.raise_for_status()
    with Image.open(io.BytesIO(response.content)) as image:
        return image.copy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repeatable API/GPU smoke benchmark")
    parser.add_argument("image", type=Path)
    parser.add_argument("--point", nargs=2, type=int, action="append", required=True, metavar=("X", "Y"))
    parser.add_argument("--product", type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--prompt", default="a red velvet lounge chair, photorealistic, matching the room perspective")
    parser.add_argument("--steps", nargs="+", type=int, default=[12, 20])
    parser.add_argument("--modes", nargs="+", choices=["prompt", "reference"], default=["prompt", "reference"])
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--output", type=Path, default=Path("data/results/benchmark"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.repeat < 1 or any(not 1 <= steps <= 80 for steps in args.steps):
        raise ValueError("repeat must be positive and steps must be in 1..80")
    args.output.mkdir(parents=True, exist_ok=True)
    api = args.api.rstrip("/")
    session = requests.Session()
    key = os.environ.get("SERVICE_API_KEY")
    if key:
        session.headers["X-Service-Key"] = key
    report = {"fixture": str(args.image), "point": args.point, "runs": [],
              "prompt": args.prompt, "steps": args.steps, "modes": args.modes,
              "catalog_fixture": "provided product" if args.product else "same-scene crop: smoke test only"}
    try:
        response = session.get(f"{api}/v1/health", timeout=30)
        response.raise_for_status()
        report["health_before"] = response.json()
        with Image.open(args.image) as source:
            original = ImageOps.exif_transpose(source).convert("RGB")
        original.save(args.output / "original.png")
        reference = image_ref(original)
        for iteration in range(args.repeat):
            segmentation, measurement = submit(session, api, "segment", {
                "image": reference, "points": [{"x": point[0], "y": point[1], "label": 1} for point in args.point],
            }, args.timeout)
            report["runs"].append({"operation": "segment", "iteration": iteration + 1,
                                   **measurement, "result": segmentation})
            logger.info("segment %s: %.3fs", iteration + 1, measurement["wall_seconds"])
        mask = fetch_image(session, api, segmentation["mask_url"]).convert("L")
        mask.save(args.output / "mask.png")
        if not mask.getbbox():
            raise RuntimeError("Segmentation returned an empty mask")
        if args.product:
            with Image.open(args.product) as source:
                product = ImageOps.exif_transpose(source).convert("RGB")
        else:
            product = Image.composite(original, Image.new("RGB", original.size, "white"), mask).crop(mask.getbbox())
        product.save(args.output / "product.png")
        started = time.perf_counter()
        response = session.post(f"{api}/v1/catalog/products", json={
            "image": image_ref(product), "name": "benchmark chair", "category": "benchmark",
        }, timeout=args.timeout)
        response.raise_for_status()
        product_id = response.json()["product_id"]
        report["ingest_seconds"] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        response = session.post(f"{api}/v1/match", json={
            "image": reference, "mask": {"image_url": segmentation["mask_url"]},
            "top_k": 5, "category_filter": "benchmark",
        }, timeout=args.timeout)
        response.raise_for_status()
        report["match_seconds"] = round(time.perf_counter() - started, 3)
        report["matches"] = response.json()
        outside = np.array(dilate_mask(mask, iterations=6)) <= 127
        baseline = np.array(original)
        for mode in args.modes:
            for steps in args.steps:
                for iteration in range(args.repeat):
                    result, measurement = submit(session, api, "replace", {
                        "image": reference, "mask": {"image_url": segmentation["mask_url"]},
                        "mode": mode, "prompt": args.prompt, "product_id": product_id,
                        "steps": steps,
                    }, args.timeout)
                    generated = fetch_image(session, api, result["result_url"]).convert("RGB")
                    filename = f"{mode}_{steps}_{iteration + 1}.png"
                    generated.save(args.output / filename)
                    if generated.size != original.size:
                        raise RuntimeError("Generated image has unexpected dimensions")
                    changed = int(np.any(np.array(generated) != baseline, axis=2)[outside].sum())
                    report["runs"].append({"operation": mode, "steps": steps, "iteration": iteration + 1,
                                           **measurement, "outside_mask_pixels_changed": changed,
                                           "filename": filename, "result": result})
                    logger.info("%s steps=%s run=%s: %.3fs, changed background pixels=%s",
                                mode, steps, iteration + 1, measurement["wall_seconds"], changed)
                    if result.get("stage1_url"):
                        cleaned = fetch_image(session, api, result["stage1_url"])
                        cleaned.save(args.output / f"stage1_{steps}_{iteration + 1}.png")
                    if changed:
                        raise RuntimeError("Background preservation check failed")
        response = session.get(f"{api}/v1/health", timeout=30)
        response.raise_for_status()
        report["health_after"] = response.json()
        return 0
    except Exception as exc:
        report["error"] = str(exc)
        logger.exception("Benchmark failed")
        return 1
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(main())