import argparse
import getpass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--port", type=int, default=5176)
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/") or url.port not in (None, 443):
        parser.error("--url must be the assigned ngrok HTTPS origin")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    token = getpass.getpass("ngrok authtoken (hidden, never paste into chat): ").strip()
    if not token:
        parser.error("authtoken must not be empty")
    config = {
        "version": "3",
        "agent": {"authtoken": token, "inspect_db_size": -1, "web_addr": False},
        "endpoints": [{
            "name": "ainterior", "url": args.url.rstrip("/"),
            "upstream": {"url": f"http://127.0.0.1:{args.port}"},
        }],
    }
    directory = Path.home() / ".config/ainterior-ngrok"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / "ngrok.yml"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w") as config_file:
        json.dump(config, config_file, indent=2)
        config_file.write("\n")
    print(f"Saved private ngrok configuration to {path}")


if __name__ == "__main__":
    main()