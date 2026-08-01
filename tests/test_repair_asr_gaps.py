from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("repair_asr_gaps", ROOT / "scripts" / "repair_asr_gaps.py")
repair = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(repair)


def word(text: str, start: float, end: float, probability: float = 0.9) -> dict:
    return {"word": text, "start": start, "end": end, "probability": probability}


class StitchWordsTests(unittest.TestCase):
    def test_merges_overlapping_duplicate_boundary_tokens(self):
        stitched = repair.stitch_words([
            word(" focus", 10.0, 10.4, 0.8),
            word(" focus.", 10.38, 10.8, 0.9),
        ])
        self.assertEqual(len(stitched), 1)
        self.assertEqual(stitched[0]["word"], " focus.")
        self.assertEqual(stitched[0]["start"], 10.0)
        self.assertEqual(stitched[0]["end"], 10.8)
        self.assertEqual(stitched[0]["probability"], 0.9)

    def test_keeps_intentional_non_overlapping_repetitions(self):
        stitched = repair.stitch_words([
            word(" no", 5.0, 5.3),
            word(" no", 5.6, 5.9),
        ])
        self.assertEqual(len(stitched), 2)

    def test_merges_repeated_cjk_tokens(self):
        stitched = repair.stitch_words([
            word("你好", 1.0, 1.4),
            word("你好", 1.42, 1.8),
        ])
        self.assertEqual(len(stitched), 1)


class IsConfirmedTests(unittest.TestCase):
    def test_long_gap_uses_relaxed_threshold(self):
        words = [word("a", 11.0, 11.4, 0.72), word("b", 12.0, 12.3, 0.70)]
        confirmed, inside = repair.is_confirmed(10.0, 14.0, words)
        self.assertTrue(confirmed)
        self.assertEqual(len(inside), 2)

    def test_short_gap_requires_high_confidence(self):
        words = [word("a", 10.5, 10.8, 0.75), word("b", 11.0, 11.3, 0.80)]
        confirmed, _ = repair.is_confirmed(10.0, 12.0, words)
        self.assertFalse(confirmed)

    def test_single_word_is_not_enough(self):
        confirmed, _ = repair.is_confirmed(10.0, 14.0, [word("a", 11.0, 11.6, 0.99)])
        self.assertFalse(confirmed)

    def test_words_outside_gap_margins_are_ignored(self):
        words = [word("a", 9.5, 10.05, 0.99), word("b", 13.95, 14.4, 0.99)]
        confirmed, inside = repair.is_confirmed(10.0, 14.0, words)
        self.assertFalse(confirmed)
        self.assertEqual(inside, [])


class WordsToSegmentsTests(unittest.TestCase):
    def test_splits_on_sentence_punctuation_including_cjk(self):
        segments = repair.words_to_segments([
            word("你好。", 0.0, 0.5),
            word("世界", 0.7, 1.0),
        ])
        self.assertEqual(len(segments), 2)
        self.assertTrue(segments[0]["repaired"])

    def test_splits_on_long_pause(self):
        segments = repair.words_to_segments([
            word(" one", 0.0, 0.3),
            word(" two", 2.0, 2.3),
        ])
        self.assertEqual(len(segments), 2)


if __name__ == "__main__":
    unittest.main()
