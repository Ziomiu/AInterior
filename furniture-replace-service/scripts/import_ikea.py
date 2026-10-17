"""Collect IKEA Ireland product references and publish an isolated shared catalog."""
from __future__ import annotations

import argparse
import asyncio
import base64
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from PIL import Image, ImageOps
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.ikea.com/ie/en/"
CATEGORIES = {
    "chair": "armchairs-fu006",
    "sofa": "sofas-fu003",
    "table": "coffee-tables-10716",
    "bed": "beds-bm003",
    "cabinet": "cabinets-cupboards-st003",
    "shelf": "bookcases-10382",
    "desk": "desks-computer-desks-20649",
    "stool": "bar-stools-chairs-20864",
    "bench": "benches-700319",
    "lamp": "floor-lamps-10731",
}


class LinkedData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.parts = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.active = True
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.active = False
            self.documents.append(json.loads("".join(self.parts)))


def nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from nodes(child)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from nodes(value["@graph"])


def structured(session, url):
    response = session.get(url, timeout=45)
    response.raise_for_status()
    parser = LinkedData()
    parser.feed(response.text)
    return list(nodes(parser.documents))


def image_url(value):
    if isinstance(value, str):
        return value
    return value.get("contentUrl") or value.get("url")


def prepare_image(content):
    with Image.open(BytesIO(content)) as source:
        source = ImageOps.exif_transpose(source).convert("RGB")
        source.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        pixels = np.asarray(source)
        foreground = np.min(pixels, axis=2) < 245
        rows, columns = np.where(foreground)
        if not len(rows):
            raise ValueError("Blank product image")
        bounds = (int(columns.min()), int(rows.min()), int(columns.max()) + 1, int(rows.max()) + 1)
        cropped = source.crop(bounds)
        cropped.thumbnail((680, 680), Image.Resampling.LANCZOS)
        prepared = Image.new("RGB", (768, 768), "white")
        prepared.paste(cropped, ((768 - cropped.width) // 2, (768 - cropped.height) // 2))
        return prepared, {"original_size": list(source.size), "foreground_bounds": list(bounds),
                          "white_fraction": round(float((~foreground).mean()), 4),
                          "method": "studio-photo-crop-white-padding", "size": [768, 768]}


def collect(args):
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"products": []}
    products = existing["products"]
    session = requests.Session()
    session.headers["User-Agent"] = "AInteriorResearchCatalog/1.0 (limited product reference import)"
    failures = []
    for category in args.categories:
        selected = [product for product in products if product["category"] == category]
        if len(selected) >= args.per_category:
            continue
        families = {product["name"].split()[0] for product in selected}
        try:
            listing = next(item for item in structured(session, BASE + "cat/" + CATEGORIES[category] + "/")
                           if item.get("@type") == "ItemList")
            for item in listing["itemListElement"]:
                if len(selected) >= args.per_category:
                    break
                if item["name"].split()[0] in families:
                    continue
                try:
                    url = item["url"]
                    product = next(node for node in structured(session, url) if node.get("@type") == "Product")
                    if any(term in product["name"].lower() for term in ("cover for", "cushion", "slatted", "footstool", "with footstool", "mattress", "headboard")):
                        continue
                    offer = product["offers"]
                    if offer["priceCurrency"] != "EUR":
                        raise ValueError("Expected EUR offer")
                    references = product["image"]
                    if not isinstance(references, list):
                        references = [references]
                    photo_url = image_url(references[0])
                    photo = session.get(photo_url, timeout=45)
                    photo.raise_for_status()
                    if len(photo.content) > 20 * 1024 * 1024:
                        raise ValueError("Product photo exceeds 20 MB")
                    product_id = str(uuid5(NAMESPACE_URL, url))
                    raw_path = args.output / "originals" / (product_id + ".jpg")
                    ready_path = args.output / "references" / (product_id + ".png")
                    raw_path.parent.mkdir(exist_ok=True)
                    ready_path.parent.mkdir(exist_ok=True)
                    prepared, preprocessing = prepare_image(photo.content)
                    raw_path.write_bytes(photo.content)
                    prepared.save(ready_path)
                    record = {
                        "product_id": product_id, "name": product["name"], "category": category,
                        "price": float(offer["price"]), "currency": "EUR", "brand": "IKEA",
                        "language": "en", "market": "IE", "article_number": product.get("sku"),
                        "description": product.get("description", ""), "color": product.get("color"),
                        "material": product.get("material"), "source_url": url, "source_image_url": photo_url,
                        "source_images": [image_url(reference) for reference in references],
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                        "reference": str(ready_path.relative_to(args.output)), "preprocessing": preprocessing,
                    }
                    products.append(record)
                    selected.append(record)
                    families.add(product["name"].split()[0])
                    manifest_path.write_text(json.dumps({"products": products}, indent=2, ensure_ascii=True) + "\n")
                    print(f"{category}: {record['name']} EUR {record['price']}", flush=True)
                except (requests.RequestException, ValueError, KeyError, StopIteration, OSError) as exc:
                    failures.append({"category": category, "url": item.get("url"), "error": str(exc)[:200]})
        except (requests.RequestException, ValueError, KeyError, StopIteration) as exc:
            failures.append({"category": category, "error": str(exc)[:200]})
    counts = Counter(product["category"] for product in products)
    summary = {"counts": dict(counts), "failures": failures}
    (args.output / "collection-report.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return 0 if all(counts[category] >= args.per_category for category in args.categories) else 1


async def publish(args):
    from dotenv import dotenv_values
    from motor.motor_asyncio import AsyncIOMotorClient

    sys.path.insert(0, str(ROOT.parent / "backend"))
    config = dotenv_values(args.mongo_env)
    parsed = urlsplit(config.get("MONGO_URL") or "mongodb://127.0.0.1:27017")
    if parsed.hostname == "mongo":
        authority = parsed.netloc.rsplit("@", 1)
        credentials = authority[0] + "@" if len(authority) == 2 else ""
        parsed = parsed._replace(netloc=credentials + "127.0.0.1:27017")
    mongo_url = urlunsplit(parsed)
    import os
    os.environ.update(MONGO_URL=mongo_url, MONGO_DATABASE="ainterior_replacement_lab", ENV_FILE="/dev/null")
    from utils import gpu_queue

    key = args.key_file.read_text().strip()
    headers = {"X-Service-Key": key}
    client = AsyncIOMotorClient(mongo_url)
    collection = client["ainterior_replacement_lab"]["furniture_products"]
    manifest = json.loads((args.output / "manifest.json").read_text())
    try:
        for product in manifest["products"]:
            product_id = product["product_id"]
            prior = await collection.find_one({"_id": product_id, "status": "ready"})
            if prior and not args.refresh:
                print(f"Already published: {product['name']}", flush=True)
                continue
            ticket = await gpu_queue.enqueue("ikea-catalog-import", "furniture:catalog-ingest")
            payload = {field: product[field] for field in ("product_id", "name", "category", "price", "currency")}
            payload["image"] = {"image_base64": base64.b64encode((args.output / product["reference"]).read_bytes()).decode("ascii")}
            try:
                response = await asyncio.to_thread(requests.post, args.api.rstrip("/") + "/v1/catalog/products",
                                                  headers={**headers, "X-GPU-Ticket": ticket}, json=payload, timeout=120)
                if response.status_code != 200 or response.json().get("product_id") != product_id:
                    raise RuntimeError(f"Catalog publication failed: HTTP {response.status_code}")
                await collection.update_one({"_id": product_id}, {"$set": {
                    **product, "shared": True, "status": "ready", "import_source": "ikea-ie-en",
                }}, upsert=True)
                print(f"Published: {product['category']} / {product['name']}", flush=True)
            except BaseException:
                await gpu_queue.cancel(ticket, "catalog_import_failed")
                raise
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("collect", "publish"))
    parser.add_argument("--output", type=Path, default=ROOT / "data/ikea-ie-en")
    parser.add_argument("--per-category", type=int, default=5)
    parser.add_argument("--categories", nargs="+", choices=list(CATEGORIES), default=list(CATEGORIES))
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--key-file", type=Path, default=ROOT / "data/lab-service.key")
    parser.add_argument("--mongo-env", type=Path)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.mode == "publish":
        if args.mongo_env is None:
            parser.error("publish requires --mongo-env; destination is always ainterior_replacement_lab")
        asyncio.run(publish(args))
        return 0
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())