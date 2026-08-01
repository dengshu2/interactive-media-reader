from __future__ import annotations

import importlib.util
import platform
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("asr_backends", ROOT / "scripts" / "asr_backends.py")
backends = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(backends)


class BackendSelectionTests(unittest.TestCase):
    def test_backend_matches_platform(self):
        expected = "mlx" if (platform.system() == "Darwin" and platform.machine() == "arm64") else "faster-whisper"
        self.assertEqual(backends.backend_name(), expected)

    def test_default_model_per_backend(self):
        self.assertEqual(backends.default_model("mlx"), "mlx-community/whisper-large-v3-turbo")
        self.assertEqual(backends.default_model("faster-whisper"), "large-v3-turbo")


class ConversionTests(unittest.TestCase):
    def test_faster_result_converts_to_whisper_shape(self):
        segments = iter([
            SimpleNamespace(
                id=0,
                seek=120,
                start=0.5,
                end=2.0,
                text=" Hello world.",
                words=[
                    SimpleNamespace(word=" Hello", start=0.5, end=1.0, probability=0.98),
                    SimpleNamespace(word=" world.", start=1.1, end=2.0, probability=0.97),
                ],
            ),
            SimpleNamespace(id=1, seek=200, start=2.5, end=3.0, text=" Bye.", words=None),
        ])
        info = SimpleNamespace(language="en")
        result = backends.faster_result_to_whisper(segments, info)
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["text"], " Hello world. Bye.")
        self.assertEqual(len(result["segments"]), 2)
        first = result["segments"][0]
        self.assertEqual(first["words"][0], {"word": " Hello", "start": 0.5, "end": 1.0, "probability": 0.98})
        self.assertEqual(result["segments"][1]["words"], [])


if __name__ == "__main__":
    unittest.main()
