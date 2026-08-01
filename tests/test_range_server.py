from __future__ import annotations

import contextlib
import http.client
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RangeServerTests(unittest.TestCase):
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
