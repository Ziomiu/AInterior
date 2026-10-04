import argparse
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values
import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-env", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5556)
    args = parser.parse_args()
    config = dotenv_values(args.mongo_env)
    key_path = Path(__file__).resolve().parents[1] / "furniture-replace-service/data/lab-jwt.key"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(key_path, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as key_file:
            key_file.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    mongo_url = config.get("MONGO_URL") or "mongodb://127.0.0.1:27017"
    parsed = urlsplit(mongo_url)
    if parsed.hostname == "mongo":
        authority = parsed.netloc.rsplit("@", 1)
        credentials = authority[0] + "@" if len(authority) == 2 else ""
        mongo_url = urlunsplit(parsed._replace(netloc=credentials + "127.0.0.1:27017"))
    os.environ.update({
        "MONGO_URL": mongo_url, "MONGO_DATABASE": "ainterior_replacement_lab",
        "ENV_FILE": "/dev/null", "SECRET_KEY": key_path.read_text().strip(), "ALGORITHM": "HS256",
        "FURNITURE_SERVICE_URL": "http://127.0.0.1:8000",
    })
    uvicorn.run("main:app", host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()