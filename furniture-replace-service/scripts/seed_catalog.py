"""
Seed the Qdrant catalog from a folder of product images.

Usage:
    python scripts/seed_catalog.py ./products --api http://localhost:8000

Each image filename encodes metadata as:  <category>__<name>__<price>.<ext>
e.g.  sofa__Karlstad 3-seater beige__1899.jpg
Price is optional:  armchair__Poang.png

This just POSTs to the running service's /v1/catalog/products endpoint — it does
not touch Qdrant directly, so the service stays the single writer.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import requests

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def parse_meta(path: Path) -> dict:
    parts = path.stem.split("__")
    category = parts[0].strip() if len(parts) > 0 else "unknown"
    name = parts[1].strip() if len(parts) > 1 else path.stem
    price = None
    if len(parts) > 2:
        try:
            price = float(parts[2])
        except ValueError:
            price = None
    return {"category": category, "name": name, "price": price}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path, help="Directory of product images")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--key", default=None, help="X-Service-Key, if the service requires one")
    args = ap.parse_args()

    headers = {"X-Service-Key": args.key} if args.key else {}
    images = [p for p in sorted(args.folder.iterdir()) if p.suffix.lower() in IMAGE_EXTS]
    if not images:
        print(f"No images found in {args.folder}", file=sys.stderr)
        return 1

    ok = 0
    for p in images:
        meta = parse_meta(p)
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        payload = {"image": {"image_base64": b64}, **meta}
        r = requests.post(f"{args.api}/v1/catalog/products", json=payload, headers=headers, timeout=60)
        if r.ok:
            ok += 1
            print(f"  ✓ {meta['category']:<12} {meta['name']}  -> {r.json()['product_id']}")
        else:
            print(f"  ✗ {p.name}: {r.status_code} {r.text}", file=sys.stderr)

    print(f"\nIndexed {ok}/{len(images)} products into the catalog.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
