#!/usr/bin/env python3
"""Stop only a preview process that proves it owns the recorded server token."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HEALTH_PATH = "/.interactive-media-reader-health"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def verified_server(metadata: dict) -> bool:
    try:
        pid = int(metadata["pid"])
        port = int(metadata["port"])
        url = str(metadata["url"])
        token = str(metadata["token"])
    except (KeyError, TypeError, ValueError):
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != port:
        return False
    request = urllib.request.Request(
        f"{url.rstrip('/')}{HEALTH_PATH}",
        headers={"X-Interactive-Media-Reader-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=0.75) as response:
            payload = json.load(response)
        return response.status == 200 and payload == {"ok": True, "pid": pid}
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    output = args.output.expanduser().resolve()
    if not output.is_dir():
        parser.error(f"reader output does not exist: {output}")
    metadata_path = output / ".server.json"
    if not metadata_path.exists():
        print(f"No managed preview server recorded for {output}")
        return

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        pid = int(metadata["pid"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Invalid preview server metadata: {metadata_path}") from error

    if not process_alive(pid):
        metadata_path.unlink()
        print(f"Preview server {pid} was not running; removed stale metadata")
        return
    if not verified_server(metadata):
        raise RuntimeError(
            f"Refusing to stop PID {pid}: it did not prove ownership of {metadata_path}. "
            "Remove stale metadata manually after checking the process."
        )

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 3
    while verified_server(metadata) and time.time() < deadline:
        time.sleep(0.05)
    if verified_server(metadata):
        raise RuntimeError(f"Preview server {pid} did not stop after SIGTERM")
    metadata_path.unlink(missing_ok=True)
    print(f"Stopped verified preview server {pid}")


if __name__ == "__main__":
    main()
