import argparse
import base64
import io
import json
from pathlib import Path
import secrets
import time

import httpx
from PIL import Image, ImageStat


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--quality", choices=("draft", "high"), default="draft")
    parser.add_argument("--model")
    parser.add_argument("--output", type=Path, default=Path("results/panorama"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url="http://127.0.0.1:5176/api", timeout=960) as client:
        for path in ("/internal/gpu-queue/status", "/admin/users", "/docs", "/openapi.json"):
            assert client.get(path).status_code == 404, path
        assert client.get("/model/panorama/models").status_code in (401, 403)
        account = {
            "first_name": "Panorama", "last_name": "Lab",
            "email": f"panorama-{secrets.token_hex(6)}@example.com",
            "password": secrets.token_urlsafe(24),
            "role": "user",
        }
        response = client.post("/auth/register", json=account)
        response.raise_for_status()
        response = client.post("/auth/login", json={"email": account["email"], "password": account["password"]})
        response.raise_for_status()
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        response = client.get("/model/panorama/models")
        response.raise_for_status()
        profiles = response.json()["models"]
        qualities = response.json()["qualities"]
        assert args.quality in qualities, qualities
        assert {profile["id"] for profile in profiles} == {
            "realvisxl-v4", "juggernaut-xl-v9", "sdxl-base", "sd-1.5", "sd-2.1", "dreamcreation",
        }, profiles
        print("Authenticated inventory:", [profile["id"] for profile in profiles], flush=True)
        print("Available quality:", qualities, flush=True)
        if args.model:
            profiles = [profile for profile in profiles if profile["id"] == args.model]
            assert profiles, "Requested model is not installed"
        response = client.post("/model/generate/panorama", json={"model_id": "../invalid", "brief": "room", "seed": 42})
        assert response.status_code == 422
        results = []
        if args.generate:
            for profile in profiles:
                started = time.monotonic()
                response = client.post("/model/generate/panorama", json={
                    "model_id": profile["id"], "seed": 42,
                    "quality": args.quality,
                    "brief": "A spacious contemporary exhibition gallery with white walls, a polished grey concrete floor, timber benches, large windows, sculptural displays and soft daylight",
                })
                response.raise_for_status()
                image_bytes = base64.b64decode(response.json()["image"], validate=True)
                expected_size = (4096, 2048) if args.quality == "high" else (profile["width"], profile["height"])
                with Image.open(io.BytesIO(image_bytes)) as image:
                    assert image.size == expected_size, image.size
                    assert max(ImageStat.Stat(image.convert("RGB")).stddev) > 10
                (args.output / f"{profile['id']}.png").write_bytes(image_bytes)
                gallery_response = client.get("/gallery/", params={"page_size": 1})
                gallery_response.raise_for_status()
                record = gallery_response.json()["images"][0]
                assert (record["width"], record["height"]) == expected_size
                assert record["image_base64"] == response.json()["image"]
                result = {"model": profile["id"], "quality": args.quality, "seed": 42, "width": expected_size[0], "height": expected_size[1], "seconds": round(time.monotonic() - started, 2), "png_bytes": len(image_bytes), "gallery_verified": True}
                results.append(result)
                (args.output / "measurements.json").write_text(json.dumps(results, indent=2) + "\n")
                print(json.dumps(result), flush=True)
    print("Public proxy, authentication, inventory and validation checks passed", flush=True)


if __name__ == "__main__":
    main()