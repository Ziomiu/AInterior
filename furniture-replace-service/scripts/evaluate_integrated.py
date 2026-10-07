from __future__ import annotations

import argparse
import base64
import binascii
from collections import defaultdict
from datetime import datetime, timezone
from io import BytesIO
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


SERVICE_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = SERVICE_ROOT / "data" / "results"
TERMINAL_STATUSES = {"done", "failed"}
KNOWN_STATUSES = {"queued", "running", *TERMINAL_STATUSES}
KNOWN_STAGES = {
    "queued", "waiting_for_gpu", "preparing", "loading", "segmenting",
    "classifying", "cleaning", "generating", "compositing", "saving", "done", "failed",
}
LIMITATIONS = [
    "Fixtures and masks are not human approved; measurements do not guarantee visual quality.",
    "Reference trials use the explicit private product, not a source crop; catalog fidelity is not proven.",
    "First/subsequent profile trials are cold/warm candidates, not verified model residency states.",
    "VRAM is sampled runner-local board memory, not process allocation or guaranteed transient peak.",
    "A forwarded API may use a different GPU; runner-local nvidia-smi does not measure that remote board.",
    "Only observed status/stage transitions are recorded; no percentage or unseen stages are inferred.",
    "Timeout or transport failure stops this runner but does not cancel server-side GPU work.",
    "Staging account/job/product data remains on the server; no production accounts are used.",
]


class EvaluationError(RuntimeError):
    pass


class ApiError(EvaluationError):
    def __init__(self, method: str, route: str, status: int | None):
        self.status = status
        super().__init__(f"{method} {route}: HTTP {status}" if status else
                         f"{method} {route}: transport failure; server work may still be running")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class BackendClient:
    def __init__(self, api: str, timeout: float):
        self.api = api.rstrip("/")
        self.timeout = timeout
        self.token: str | None = None
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method: str, route: str, payload: dict | None = None) -> dict:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.api + route, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(100 * 1024 * 1024 + 1)
            if len(raw) > 100 * 1024 * 1024:
                raise EvaluationError("Backend response exceeds the runner size limit")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise EvaluationError("Expected a JSON object from the backend")
            return result
        except HTTPError as exc:
            status = exc.code
            exc.close()
            raise ApiError(method, route, status) from None
        except (URLError, TimeoutError, OSError):
            raise ApiError(method, route, None) from None
        except (ValueError, UnicodeError):
            raise EvaluationError("Backend returned invalid JSON; response body omitted") from None

    def create_account(self) -> dict:
        email = f"integrated-{secrets.token_hex(12)}@example.com"
        password = secrets.token_urlsafe(32)
        registration = self.request("POST", "/auth/register", {
            "first_name": "Integrated", "last_name": "Evaluation", "email": email,
            "password": password, "role": "user",
        })
        login = self.request("POST", "/auth/login", {"email": email, "password": password})
        token = login.get("access_token")
        if not isinstance(token, str) or not token:
            raise EvaluationError("Login response did not contain an access token")
        self.token = token
        return {"email": email, "user_id": registration.get("user_id")}


def scene_spec(value: str) -> tuple[str, Path, int, int]:
    try:
        source, coordinate_x, coordinate_y = value.rsplit(":", 2)
        name, separator, path = source.partition(":")
        if not separator or not path or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError
        coordinates = int(coordinate_x), int(coordinate_y)
        if min(coordinates) < 0:
            raise ValueError
        return name, Path(path), *coordinates
    except ValueError:
        raise argparse.ArgumentTypeError("Use NAME:PATH:X:Y with a safe name and nonnegative pixel coordinates") from None


def mask_spec(value: str) -> tuple[str, Path]:
    name, separator, path = value.partition(":")
    if not separator or not path:
        raise argparse.ArgumentTypeError("Use NAME:PATH for an optional corrected mask")
    return name, Path(path)


def png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    content = buffer.getvalue()
    if len(content) > 5 * 1024 * 1024:
        raise EvaluationError("Normalized PNG exceeds the backend's 5 MB image limit")
    return content


def load_original(path: Path) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    if max(image.size) > 4096 or image.width * image.height > 16_777_216:
        raise EvaluationError("Fixture exceeds the backend image dimension limit")
    return image


def decode_asset(encoded: str, path: Path) -> Image.Image:
    try:
        content = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(content)) as source:
            source.load()
            image = source.copy()
    except (binascii.Error, ValueError, TypeError, OSError):
        raise EvaluationError("Backend returned an invalid base64 image") from None
    path.write_bytes(content)
    return image


def binary_mask(mask: Image.Image, size: tuple[int, int]) -> Image.Image:
    if mask.size != size:
        raise EvaluationError("Mask dimensions differ from the EXIF-oriented original")
    selected = mask.convert("L").point([0] * 128 + [255] * 128)
    if selected.getbbox() is None:
        raise EvaluationError("Mask is empty after the service's >127 threshold")
    return selected


def preservation_check(original: Image.Image, generated: Image.Image,
                       mask: Image.Image, growth: int) -> dict:
    if generated.size != original.size:
        raise EvaluationError("Generated image dimensions differ from the original; not resized")
    if not 0 <= growth <= 32:
        raise EvaluationError("Mask growth must be in 0..32")
    selected = binary_mask(mask, original.size)
    expanded = selected.filter(ImageFilter.MaxFilter(2 * growth + 1)) if growth else selected
    outside = ImageOps.invert(expanded)
    difference = ImageChops.difference(original.convert("RGB"), generated.convert("RGB"))
    red, green, blue = difference.split()
    any_channel = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    changed = any_channel.point([0] + [255] * 255)
    changed_outside = ImageChops.multiply(changed, outside).histogram()[255]
    outside_pixels = outside.histogram()[255]
    return {
        "method": "Exact RGB equality outside >127 mask expanded by square MaxFilter(2*growth+1)",
        "mask_growth": growth, "outside_pixels": outside_pixels,
        "outside_mask_pixels_changed": changed_outside,
        "outside_equal": changed_outside == 0,
        "meaningful_outside_region": outside_pixels > 0,
        "passed": changed_outside == 0 and outside_pixels > 0,
    }


def save_overlay(original: Image.Image, mask: Image.Image, path: Path) -> None:
    tint = Image.blend(original, Image.new("RGB", original.size, (20, 170, 240)), 0.4)
    Image.composite(tint, original, mask).save(path)


def contact_sheet(items: list[tuple[str, Path]], path: Path) -> None:
    cell_width, cell_height, columns = 360, 290, 3
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, source_path) in enumerate(items):
        origin_x = index % columns * cell_width
        origin_y = index // columns * cell_height
        with Image.open(source_path) as source:
            thumbnail = ImageOps.contain(source.convert("RGB"), (cell_width - 16, cell_height - 45))
        sheet.paste(thumbnail, (origin_x + (cell_width - thumbnail.width) // 2, origin_y + 8))
        draw.text((origin_x + 8, origin_y + cell_height - 32), label, fill="black")
    sheet.save(path)


def sample_vram(gpu_id: int) -> dict | None:
    try:
        response = subprocess.run([
            "nvidia-smi", f"--id={gpu_id}", "--query-gpu=index,uuid,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ], check=True, capture_output=True, text=True, timeout=2)
        index, board_uuid, used, free = (part.strip() for part in response.stdout.strip().split(","))
        return {"gpu_index": int(index), "gpu_uuid": board_uuid,
                "used_mib": int(used), "free_mib": int(free)}
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def submit_and_poll(client: BackendClient, route: str, payload: dict,
                    measurement: dict, args: argparse.Namespace) -> dict:
    started = time.monotonic()
    measurement.update({"status": "submitting", "status_stages": [], "vram_samples": [],
                        "vram_unavailable_samples": 0, "server_elapsed_seconds": None})
    try:
        submitted = client.request("POST", route, payload)
        job_id = str(UUID(submitted["job_id"]))
        measurement["job_id"] = job_id
        measurement["post_seconds"] = round(time.monotonic() - started, 4)
        measurement["status_stages"].append({"elapsed_wall_seconds": measurement["post_seconds"],
                                             "status": submitted.get("status"), "stage": None})
        while time.monotonic() - started < args.timeout:
            interval_started = time.monotonic()
            sample = sample_vram(args.gpu_id)
            if sample is None:
                measurement["vram_unavailable_samples"] += 1
            else:
                measurement["vram_samples"].append({
                    "elapsed_wall_seconds": round(time.monotonic() - started, 4), **sample,
                })
            job = client.request("GET", f"/furniture/jobs/{job_id}")
            status = job.get("status")
            if status not in KNOWN_STATUSES:
                raise EvaluationError("Backend returned an unknown job status")
            stage = job.get("stage") if job.get("stage") in KNOWN_STAGES else None
            previous = measurement["status_stages"][-1]
            if (status, stage) != (previous["status"], previous["stage"]):
                measurement["status_stages"].append({
                    "elapsed_wall_seconds": round(time.monotonic() - started, 4),
                    "status": status, "stage": stage,
                })
                print(f"{measurement['label']}: {status}" + (f" / {stage}" if stage else ""), flush=True)
            measurement["status"] = status
            if status == "failed":
                raise EvaluationError("Backend job failed; server error text intentionally omitted")
            if status == "done":
                result = job.get("result")
                if not isinstance(result, dict):
                    raise EvaluationError("Completed job has no result object")
                measurement["server_elapsed_seconds"] = result.get("elapsed_seconds")
                return result
            time.sleep(max(0, args.poll_interval - (time.monotonic() - interval_started)))
        raise EvaluationError("Polling timed out; do not start another GPU job until server work is checked")
    finally:
        measurement["post_and_poll_wall_seconds"] = round(time.monotonic() - started, 4)
        samples = measurement["vram_samples"]
        measurement["vram_observed_peak_mib"] = max((row["used_mib"] for row in samples), default=None)
        measurement["vram_observed_min_free_mib"] = min((row["free_mib"] for row in samples), default=None)


def expect_not_found(client: BackendClient, method: str, route: str) -> dict:
    try:
        client.request(method, route)
    except ApiError as exc:
        return {"method": method, "route": route, "status": exc.status, "passed": exc.status == 404}
    return {"method": method, "route": route, "status": 200, "passed": False}


def default_prompt(classification: object) -> str:
    category = classification.get("category") if isinstance(classification, dict) else None
    categories = {
        "chair": "armchair", "armchair": "armchair", "sofa": "sofa", "couch": "sofa",
        "bench": "bench", "stool": "stool", "ottoman": "ottoman", "bed": "bed",
    }
    furniture = categories.get(str(category).lower(), "furniture")
    return (f"blue upholstered {furniture}, realistic fabric, matching the original object scale, "
            "room perspective, lighting and contact shadows")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measured integrated staging HTTP evaluation; no quality guarantee")
    parser.add_argument("--api", default="http://127.0.0.1:5556", help="Loopback backend URL, optionally an existing tunnel")
    parser.add_argument("--scene", type=scene_spec, action="append", required=True, metavar="NAME:PATH:X:Y")
    parser.add_argument("--mask", type=mask_spec, action="append", default=[], metavar="NAME:PATH",
                        help="Optional corrected mask in original pixel dimensions; otherwise use binary SAM mask")
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 42])
    parser.add_argument("--profiles", nargs="+", choices=["balanced", "quality"], default=["balanced", "quality"])
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--prompt", help="Common replacement prompt; otherwise blue upholstery adapted to classification")
    parser.add_argument("--mask-growth", type=int, default=6)
    parser.add_argument("--edge-blend", type=int, default=2)
    parser.add_argument("--product", type=Path, help="Distinct real product fixture, never a source-scene crop")
    parser.add_argument("--product-name", default="Integrated evaluation product")
    parser.add_argument("--product-category", default="furniture")
    parser.add_argument("--check-save", action="store_true", help="Save each replacement twice and compare image IDs")
    parser.add_argument("--check-isolation", action="store_true", help="Create a second staging user and assert job/save 404")
    parser.add_argument("--timeout", type=float, default=900, help="POST plus polling budget in seconds")
    parser.add_argument("--http-timeout", type=float, default=120)
    parser.add_argument("--poll-interval", type=float, default=1)
    parser.add_argument("--gpu-id", type=int, default=0, help="Runner-local nvidia-smi board index")
    parser.add_argument("--output", type=Path, required=True, help="New directory under service/data/results/integrated-*")
    parser.add_argument("--confirm-staging", action="store_true", help="Confirm this URL is an isolated staging backend")
    parser.add_argument("--confirm-gpu-window", action="store_true", help="Confirm no concurrent generation or ComfyUI work")
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    url = urlsplit(args.api)
    if (url.scheme not in {"http", "https"} or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
        parser.error("--api must be a loopback HTTP(S) backend origin, without credentials or a path")
    if not args.confirm_staging or not args.confirm_gpu_window:
        parser.error("Explicit --confirm-staging and --confirm-gpu-window are required before creating users or jobs")
    if (not 1 <= args.steps <= 80 or not 0 <= args.mask_growth <= 32 or not 0 <= args.edge_blend <= 8
            or any(not 0 <= seed <= 2**32 - 1 for seed in args.seeds)):
        parser.error("Invalid steps (1..80), growth (0..32), blend (0..8), or uint32 seed")
    if any(not math.isfinite(value) or value <= 0 for value in
           (args.timeout, args.http_timeout, args.poll_interval)) or args.gpu_id < 0:
        parser.error("Timeouts and polling interval must be finite and positive; GPU index must be nonnegative")
    names = [scene[0] for scene in args.scene]
    if len(names) != len(set(names)) or any(len(name) > 80 for name in names):
        parser.error("Scene names must be unique and at most 80 characters")
    mask_names = [name for name, _ in args.mask]
    if len(mask_names) != len(set(mask_names)) or not set(mask_names) <= set(names):
        parser.error("Corrected masks must name a scene exactly once")
    if args.prompt is not None and (not args.prompt.strip() or len(args.prompt) > 2000):
        parser.error("Prompt must be nonempty and at most 2000 characters")
    if args.product:
        if not args.product_name or not args.product_category:
            parser.error("--product requires --product-name and --product-category")
        if len(args.product_name) > 150 or len(args.product_category) > 100:
            parser.error("Product name/category exceed backend limits (150/100)")
        if args.product.resolve() in {scene[1].resolve() for scene in args.scene}:
            parser.error("Product must be distinct from every source scene, not a source crop")
    output = (SERVICE_ROOT / args.output).resolve()
    if output.parent != RESULTS_ROOT.resolve() or not output.name.startswith("integrated-"):
        parser.error(f"--output must be a new {RESULTS_ROOT}/integrated-* directory (ignored data)")
    if output.exists():
        parser.error("Output directory already exists; choose a new run name")
    args.output = output


def profile_timings(scenes: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for scene in scenes:
        for run in scene["trials"]:
            groups[run["request"]["quality"]].append(run)
    return {profile: {
        "first_observed_wall_seconds": runs[0].get("post_and_poll_wall_seconds"),
        "subsequent_observed_wall_seconds": [run.get("post_and_poll_wall_seconds") for run in runs[1:]],
        "observed_peak_vram_mib": max((run["vram_observed_peak_mib"] for run in runs
                                       if run.get("vram_observed_peak_mib") is not None), default=None),
        "note": "Cold/warm candidates only; modes may differ and other clients/model unloading are not observed",
    } for profile, runs in groups.items()}


def evaluate(args: argparse.Namespace, report: dict) -> None:
    masks = dict(args.mask)
    fixtures = []
    for name, path, coordinate_x, coordinate_y in args.scene:
        original = load_original(path)
        if coordinate_x >= original.width or coordinate_y >= original.height:
            raise EvaluationError("Foreground click lies outside the EXIF-oriented scene")
        corrected = None
        if name in masks:
            with Image.open(masks[name]) as source:
                corrected = binary_mask(source, original.size)
        fixtures.append((name, path, coordinate_x, coordinate_y, original, png_bytes(original), corrected))
    product = load_original(args.product) if args.product else None
    product_bytes = png_bytes(product) if product is not None else None
    if product_bytes is not None and any(product_bytes == fixture[5] for fixture in fixtures):
        raise EvaluationError("Product pixels must be distinct from every source scene")
    client = BackendClient(args.api, args.http_timeout)
    report["account"] = client.create_account()
    observer = None
    if args.check_isolation:
        observer = BackendClient(args.api, args.http_timeout)
        report["isolation_account"] = observer.create_account()
    product_id = None
    if product_bytes is not None:
        product_path = args.output / "explicit-product.png"
        product_path.write_bytes(product_bytes)
        report["product"] = {"fixture": str(args.product.resolve()), "image_path": str(product_path),
                             "name": args.product_name, "category": args.product_category}
        started = time.monotonic()
        ingested = client.request("POST", "/furniture/products", {
            "image": base64.b64encode(product_bytes).decode("ascii"),
            "name": args.product_name, "category": args.product_category,
        })
        product_id = str(UUID(ingested["product_id"]))
        report["product"].update({"product_id": product_id, "ingest_wall_seconds": round(time.monotonic() - started, 4)})
    profile_counts: dict[str, int] = defaultdict(int)
    checks_passed = True
    for name, source_path, coordinate_x, coordinate_y, original, original_bytes, corrected in fixtures:
        directory = args.output / name
        directory.mkdir()
        original_path = directory / "original.png"
        original_path.write_bytes(original_bytes)
        scene = {"name": name, "fixture": str(source_path.resolve()), "original_path": str(original_path),
                 "dimensions": list(original.size), "point": {"x": coordinate_x, "y": coordinate_y, "label": 1},
                 "fixtures_human_approved": False, "trials": [], "isolation_checks": []}
        report["scenes"].append(scene)
        image_payload = base64.b64encode(original_bytes).decode("ascii")
        measurement = {"label": f"{name} segment"}
        scene["segmentation"] = measurement
        segmented = submit_and_poll(client, "/furniture/segment", {
            "image": image_payload, "points": [scene["point"]],
        }, measurement, args)
        for field in ("classification", "bbox", "score", "mask_review_required"):
            scene[field] = segmented.get(field)
        scene["server_elapsed_note"] = "Segment job API does not expose server elapsed_seconds"
        raw_mask_path = directory / "segmented-mask.png"
        raw_mask = decode_asset(segmented["mask"], raw_mask_path)
        if raw_mask.size != original.size:
            raise EvaluationError("Service mask dimensions differ from the original")
        selected = corrected if corrected is not None else binary_mask(raw_mask, original.size)
        expanded = selected.filter(ImageFilter.MaxFilter(2 * args.mask_growth + 1)) if args.mask_growth else selected
        if expanded.histogram()[0] == 0:
            raise EvaluationError("Expanded mask covers the entire image; outside preservation is untestable")
        mask_bytes = png_bytes(selected)
        mask_path = directory / "replacement-mask.png"
        mask_path.write_bytes(mask_bytes)
        scene.update({"segmented_mask_path": str(raw_mask_path), "replacement_mask_path": str(mask_path),
                      "mask_source": "provided corrected mask" if corrected is not None else "binary SAM mask, unreviewed",
                      "corrected_mask_fixture": str(masks[name].resolve()) if corrected is not None else None,
                      "replacement_mask_bbox": list(selected.getbbox())})
        expanded_path = directory / "expanded-mask.png"
        expanded.save(expanded_path)
        scene["expanded_mask_path"] = str(expanded_path)
        overlay_path = directory / "mask-overlay.png"
        save_overlay(original, selected, overlay_path)
        scene["overlay_path"] = str(overlay_path)
        tiles = [("Original", original_path), ("Replacement mask (not approved)", overlay_path)]
        if product_id:
            tiles.append(("Explicit product (no fidelity claim)", args.output / "explicit-product.png"))
        if observer:
            check = expect_not_found(observer, "GET", f"/furniture/jobs/{measurement['job_id']}")
            scene["isolation_checks"].append(check)
            checks_passed = checks_passed and check["passed"]
        schedule = [("reference", "balanced")] if product_id else []
        schedule.extend(("prompt", profile) for profile in dict.fromkeys(args.profiles))
        for mode, profile in schedule:
            for seed in dict.fromkeys(args.seeds):
                profile_counts[profile] += 1
                request_metadata = {
                    "mode": mode, "quality": profile, "seed": seed, "steps": args.steps,
                    "mask_growth": args.mask_growth, "edge_blend": args.edge_blend,
                    "mask_job_id": measurement["job_id"],
                }
                if mode == "reference":
                    request_metadata["product_id"] = product_id
                else:
                    request_metadata["prompt"] = args.prompt or default_prompt(scene["classification"])
                label = f"{mode}-{profile}-seed{seed}"
                run = {"label": f"{name} {label}", "request": request_metadata,
                       "profile_trial_index": profile_counts[profile],
                       "thermal_candidate": "cold_candidate" if profile_counts[profile] == 1 else "warm_candidate"}
                scene["trials"].append(run)
                generated = submit_and_poll(client, "/furniture/replace", {
                    **request_metadata, "image": image_payload,
                    "mask": base64.b64encode(mask_bytes).decode("ascii"),
                }, run, args)
                result_path = directory / f"{label}.png"
                result_image = decode_asset(generated["image"], result_path)
                run["image_path"] = str(result_path)
                run["preservation"] = preservation_check(original, result_image, selected, args.mask_growth)
                checks_passed = checks_passed and run["preservation"]["passed"]
                tiles.append((f"{mode} {profile} seed={seed} steps={args.steps}", result_path))
                if args.check_save:
                    route = f"/furniture/jobs/{run['job_id']}/save"
                    first = client.request("POST", route)
                    second = client.request("POST", route)
                    passed = isinstance(first.get("image_id"), str) and bool(first["image_id"]) and first == second
                    run["save_idempotency"] = {"first_image_id": first.get("image_id"),
                                               "second_image_id": second.get("image_id"), "passed": passed,
                                               "note": "Equal IDs; database row count is not inspected"}
                    checks_passed = checks_passed and passed
                if observer:
                    for method, route in [("GET", f"/furniture/jobs/{run['job_id']}"),
                                          ("POST", f"/furniture/jobs/{run['job_id']}/save")]:
                        check = expect_not_found(observer, method, route)
                        run.setdefault("isolation_checks", []).append(check)
                        checks_passed = checks_passed and check["passed"]
                contact_path = directory / "contact-sheet.png"
                contact_sheet(tiles, contact_path)
                scene["contact_sheet_path"] = str(contact_path)
    report["checks_passed"] = checks_passed


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "api": args.api, "created_at": datetime.now(timezone.utc).isoformat(),
        "output": str(args.output), "limitations": LIMITATIONS, "scenes": [],
        "execution": "Sequential integrated backend HTTP only; no service keys, .env, SSH, or ComfyUI calls",
        "vram_source": {"host": "runner-local", "gpu_index": args.gpu_id, "poll_interval_seconds": args.poll_interval},
        "credentials": "Generated passwords and JWTs only in memory, never included in artifacts",
        "checks_passed": False,
    }
    exit_code = 1
    try:
        evaluate(args, report)
        exit_code = 0 if report["checks_passed"] else 1
    except Exception as exc:
        report["error"] = str(exc) if isinstance(exc, EvaluationError) else f"{type(exc).__name__}: runner failure; details omitted"
        print(report["error"], flush=True)
    except KeyboardInterrupt:
        report["error"] = "Interrupted; server work is not cancelled. Check it before starting any further GPU work."
        print(report["error"], flush=True)
        exit_code = 130
    finally:
        report["profile_timings"] = profile_timings(report["scenes"])
        report["exit_code"] = exit_code
        summary_path = args.output / "summary.json"
        summary_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Summary: {summary_path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())