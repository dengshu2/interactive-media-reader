from __future__ import annotations

import contextlib
import http.client
import importlib.util
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("serve", ROOT / "scripts" / "serve.py")
serve = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(serve)


class MediaTypeTests(unittest.TestCase):
    def test_browser_playable_types_are_pinned(self):
        # The system table maps .m4a to audio/mp4a-latm, which no browser
        # decodes; every accepted container must resolve to a type the page
        # can actually play.
        for suffix, expected in (
            (".m4a", "audio/mp4"),
            (".mp4", "video/mp4"),
            (".m4v", "video/mp4"),
            (".mp3", "audio/mpeg"),
            (".webm", "video/webm"),
        ):
            self.assertEqual(serve.MEDIA_TYPES[suffix], expected, suffix)

    def test_every_accepted_container_is_covered(self):
        accepted = {".aac", ".flac", ".m4a", ".m4v", ".mp3", ".mp4", ".ogg", ".opus", ".wav", ".webm"}
        self.assertTrue(accepted <= set(serve.MEDIA_TYPES), accepted - set(serve.MEDIA_TYPES))


class RangeServerTests(unittest.TestCase):
    def test_m4a_is_served_as_audio_mp4(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.m4a").write_bytes(b"\0" * 64)
            status, headers = self.request(root, "/source.m4a")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "audio/mp4")

    def request(self, root: Path, path: str, headers: dict | None = None):
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(port), "--directory", str(root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.time() + 5
            while True:
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    connection.request("GET", path, headers=headers or {})
                    response = connection.getresponse()
                    response.read()
                    return response.status, {key: value for key, value in response.getheaders()}
                except OSError:
                    if time.time() >= deadline:
                        raise
                    time.sleep(0.05)
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=3)
            if process.poll() is None:
                process.kill()

    def test_byte_range_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.bin").write_bytes(bytes(range(256)) * 8)
            # Reserve a port by asking the OS, then release it immediately for the subprocess.
            import socket
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, str(ROOT / "scripts" / "serve.py"), "--port", str(port), "--directory", str(root)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.time() + 5
                while True:
                    try:
                        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                        connection.request("GET", "/sample.bin", headers={"Range": "bytes=100-199"})
                        response = connection.getresponse()
                        body = response.read()
                        break
                    except OSError:
                        if time.time() >= deadline:
                            raise
                        time.sleep(0.05)
                self.assertEqual(response.status, 206)
                self.assertEqual(response.getheader("Content-Range"), "bytes 100-199/2048")
                self.assertEqual(len(body), 100)
            finally:
                process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=3)
                if process.poll() is None:
                    process.kill()


if __name__ == "__main__":
    unittest.main()
