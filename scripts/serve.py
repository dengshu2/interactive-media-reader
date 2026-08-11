#!/usr/bin/env python3
"""Small static server with byte-range support for reliable audio seeking."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
from email.utils import formatdate
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HEALTH_PATH = "/.interactive-media-reader-health"


# Python's mimetypes reads the system table, which maps .m4a to
# audio/mp4a-latm (raw LATM-framed AAC). No browser decodes that, so an m4a
# reader loads its page and then silently fails to load its audio. Pin the
# container types the pipeline accepts instead of trusting the host.
MEDIA_TYPES = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".m4v": "video/mp4",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".webm": "video/webm",
}


class RangeRequestHandler(SimpleHTTPRequestHandler):
    byte_range: tuple[int, int] | None = None

    def guess_type(self, path):
        suffix = Path(path).suffix.lower()
        return MEDIA_TYPES.get(suffix) or super().guess_type(path)

    def do_GET(self):
        if self.path == HEALTH_PATH:
            expected = str(getattr(self.server, "health_token", ""))
            supplied = self.headers.get("X-Interactive-Media-Reader-Token", "")
            if not expected or not hmac.compare_digest(expected, supplied):
                self.send_error(403, "Invalid reader server token")
                return
            body = json.dumps({"ok": True, "pid": os.getpid()}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            file = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        stat = os.fstat(file.fileno())
        size = stat.st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                file.close()
                self.send_error(416, "Invalid byte range")
                return None
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            elif last:
                length = min(int(last), size)
                start, end = size - length, size - 1
            if start > end or start >= size:
                file.close()
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None
            status = 206
            self.byte_range = (start, end)
        else:
            self.byte_range = None

        self.send_response(status)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", formatdate(stat.st_mtime, usegmt=True))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        file.seek(start)
        return file

    def copyfile(self, source, outputfile):
        if not self.byte_range:
            return super().copyfile(source, outputfile)
        start, end = self.byte_range
        remaining = end - start + 1
        while remaining:
            chunk = source.read(min(128 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--directory", type=Path, default=Path.cwd())
    parser.add_argument("--token", default="")
    args = parser.parse_args()
    os.chdir(args.directory)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), RangeRequestHandler)
    server.health_token = args.token
    print(f"Reader: http://localhost:{args.port}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
