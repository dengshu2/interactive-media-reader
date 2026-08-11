from __future__ import annotations

import io
import importlib.util
import math
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("asr_backends", ROOT / "scripts" / "asr_backends.py")
backends = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(backends)


class EngineImportTests(unittest.TestCase):
    def test_native_libraries_load(self):
        """sherpa-onnx must import, not just resolve.

        Its native libraries live in a separate sherpa-onnx-core package that
        the wheel declares and the sdist does not. Resolvers that read sdist
        metadata drop it, and the failure only appears at import time as a
        missing @rpath/libonnxruntime — after a green install.
        """
        import sherpa_onnx

        self.assertTrue(hasattr(sherpa_onnx, "OfflineRecognizer"))


class ModelSelectionTests(unittest.TestCase):
    def test_default_model_is_the_parakeet_release_build(self):
        self.assertEqual(backends.default_model(), backends.PARAKEET_MODEL)

    def test_thread_count_stays_within_bounds(self):
        self.assertGreaterEqual(backends.thread_count(), 1)
        self.assertLessEqual(backends.thread_count(), 6)

    def test_release_archive_has_a_pinned_sha256(self):
        self.assertRegex(backends.PARAKEET_RELEASE_SHA256, r"^[0-9a-f]{64}$")

    def test_safe_extract_rejects_path_traversal(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as bundle:
            member = tarfile.TarInfo("../escape.txt")
            payload = b"escape"
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
        archive.seek(0)
        with tempfile.TemporaryDirectory() as directory, tarfile.open(fileobj=archive, mode="r") as bundle:
            with self.assertRaises((tarfile.FilterError, RuntimeError)):
                backends.safe_extract(bundle, Path(directory))


class ParakeetTokenTests(unittest.TestCase):
    # ' Un', 'c', 'ont', 'rol', 'led', '.' is the real subword split Parakeet
    # emits for "Uncontrolled."; a leading space is the only word boundary cue.
    TOKENS = [" Un", "c", "ont", "rol", "led", ".", " But", " when"]
    TIMESTAMPS = [0.4, 0.56, 0.64, 0.8, 1.04, 1.28, 1.44, 1.68]
    DURATIONS = [0.16, 0.08, 0.16, 0.24, 0.24, 0.16, 0.24, 0.32]
    LOG_PROBABILITIES = [-0.958, -0.001, 0.0, 0.0, -0.001, -0.368, -0.001, 0.0]

    def words(self, offset=0.0):
        return backends.tokens_to_words(
            self.TOKENS, self.TIMESTAMPS, self.DURATIONS, self.LOG_PROBABILITIES, offset
        )

    def test_subwords_merge_into_words(self):
        self.assertEqual([word["word"] for word in self.words()], [" Uncontrolled.", " But", " when"])

    def test_timing_spans_first_token_start_to_last_token_end(self):
        first = self.words()[0]
        self.assertEqual(first["start"], 0.4)
        self.assertEqual(first["end"], round(1.28 + 0.16, 3))

    def test_offset_shifts_every_word(self):
        self.assertEqual(self.words(offset=60.0)[0]["start"], 60.4)

    def test_probability_is_geometric_mean_of_token_probabilities(self):
        first = self.words()[0]
        expected = math.exp(sum(self.LOG_PROBABILITIES[:6]) / 6)
        self.assertAlmostEqual(first["probability"], round(expected, 6), places=6)
        self.assertLess(first["probability"], self.words()[1]["probability"])

    def test_end_never_collapses_onto_start(self):
        words = backends.tokens_to_words([" hi"], [1.0], [0.0], [0.0], 0.0)
        self.assertGreater(words[0]["end"], words[0]["start"])


class ParakeetSegmentTests(unittest.TestCase):
    def word(self, text, start, end, probability=0.99):
        return {"word": text, "start": start, "end": end, "probability": probability}

    def test_sentence_end_closes_a_segment(self):
        result = backends.words_to_segments(
            [self.word(" Hello.", 0.0, 0.5), self.word(" Bye.", 0.6, 1.0)]
        )
        self.assertEqual([segment["text"] for segment in result["segments"]], [" Hello.", " Bye."])
        self.assertEqual(result["language"], "en")

    def test_long_pause_closes_a_segment_without_punctuation(self):
        words = [self.word(" one", 0.0, 0.5), self.word(" two", 9.0, 9.5)]
        result = backends.words_to_segments(words)
        self.assertEqual(len(result["segments"]), 2)

    def test_segment_carries_its_words_and_bounds(self):
        result = backends.words_to_segments([self.word(" Hi.", 2.0, 2.75)])
        segment = result["segments"][0]
        self.assertEqual(segment["start"], 2.0)
        self.assertEqual(segment["end"], 2.75)
        self.assertEqual(len(segment["words"]), 1)
        self.assertEqual(result["text"], " Hi.")

    def test_runaway_segment_is_capped(self):
        words = [self.word(f" w{index}", index * 0.1, index * 0.1 + 0.05) for index in range(130)]
        result = backends.words_to_segments(words)
        self.assertTrue(all(len(segment["words"]) <= 60 for segment in result["segments"]))


class ParakeetWindowTests(unittest.TestCase):
    def audio(self, seconds, quiet_at=None):
        import numpy as np

        samples = np.ones(int(seconds * backends.SAMPLE_RATE), dtype=np.float32) * 0.5
        if quiet_at is not None:
            start = int(quiet_at * backends.SAMPLE_RATE)
            samples[start : start + backends.SAMPLE_RATE // 2] = 0.0
        return samples

    def test_short_audio_stays_one_window(self):
        bounds = backends.quiet_windows(self.audio(30), backends.SAMPLE_RATE, 60.0, 8.0)
        self.assertEqual(len(bounds), 1)
        self.assertAlmostEqual(bounds[0][1], 30.0, places=2)

    def test_windows_tile_the_audio_without_gaps(self):
        bounds = backends.quiet_windows(self.audio(200), backends.SAMPLE_RATE, 60.0, 8.0)
        self.assertGreater(len(bounds), 1)
        self.assertEqual(bounds[0][0], 0.0)
        self.assertAlmostEqual(bounds[-1][1], 200.0, places=2)
        for previous, following in zip(bounds, bounds[1:]):
            self.assertEqual(previous[1], following[0])

    def test_boundary_snaps_to_the_quiet_stretch(self):
        bounds = backends.quiet_windows(self.audio(200, quiet_at=55.0), backends.SAMPLE_RATE, 60.0, 8.0)
        self.assertTrue(55.0 <= bounds[0][1] <= 55.5, bounds[0][1])


class ParakeetDegenerateTests(unittest.TestCase):
    def test_window_without_sentence_ends_is_degenerate(self):
        self.assertTrue(backends.is_degenerate([" uncontrolled", " but", " when"], 60.0))

    def test_punctuated_window_is_healthy(self):
        self.assertFalse(backends.is_degenerate([" Uncontrolled.", " But"], 60.0))

    def test_short_window_is_never_degenerate(self):
        # A two-second clip legitimately holds no sentence end.
        self.assertFalse(backends.is_degenerate([" uncontrolled"], 2.0))


if __name__ == "__main__":
    unittest.main()
