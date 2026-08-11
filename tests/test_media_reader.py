from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("media_reader", ROOT / "scripts" / "media_reader.py")
media_reader = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(media_reader)


class Completed:
    def __init__(self, payload):
        self.stdout = json.dumps(payload)


class MediaReaderTests(unittest.TestCase):
    def test_clean_title_removes_video_id_and_compressed_suffix(self):
        path = Path("A useful talk [abcDEF_123] - compressed.mp3")
        self.assertEqual(media_reader.clean_title(path), "A useful talk")

    def test_mp3_attached_picture_is_not_motion_video(self):
        payload = {
            "streams": [
                {"codec_type": "audio", "codec_name": "mp3", "duration": "10"},
                {"codec_type": "video", "codec_name": "png", "duration": "10", "disposition": {"attached_pic": 1}},
            ],
            "format": {"duration": "10"},
        }
        with patch.object(media_reader.subprocess, "run", return_value=Completed(payload)):
            info = media_reader.probe_media(Path("book.mp3"))
        self.assertEqual(info["mediaType"], "audio")
        self.assertTrue(info["codecCompatible"])

    def test_h264_aac_mp4_is_video(self):
        payload = {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "duration": "12", "disposition": {"attached_pic": 0}},
                {"codec_type": "audio", "codec_name": "aac", "duration": "12"},
            ],
            "format": {"duration": "12"},
        }
        with patch.object(media_reader.subprocess, "run", return_value=Completed(payload)):
            info = media_reader.probe_media(Path("talk.mp4"))
        self.assertEqual(info["mediaType"], "video")
        self.assertTrue(info["codecCompatible"])

    def test_final_repeated_heading_wins(self):
        def sentence(text, start, end):
            return {"text": text, "start": start, "end": end}

        sentences = [
            sentence("Welcome.", 0, 1),
            sentence("Chapter 1 is about focus.", 10, 12),
            sentence("More introduction.", 15, 17),
            sentence("Chapter 1.", 30, 31),
            sentence("Protect your focus.", 31.3, 32.5),
            sentence("Main content begins here.", 33, 35),
        ]
        chapters = media_reader.detect_chapters(sentences)
        self.assertEqual(len(chapters), 2)
        self.assertEqual(chapters[1]["start"], 30)
        self.assertTrue(chapters[1]["title"].startswith("Chapter 1: Protect your focus"))

    def test_heading_dedupes_repeated_spoken_subtitle(self):
        sentences = [
            {"text": "Chapter 8.", "start": 4380.2, "end": 4381.5},
            {"text": "Learn one useful thing.", "start": 4382.2, "end": 4384.5},
            {"text": "Learn one useful thing.", "start": 4384.9, "end": 4385.6},
        ]
        self.assertEqual(media_reader.heading_title(sentences, 0), "Chapter 8: Learn one useful thing")

    def test_heading_single_word_continuation_is_lowercased(self):
        sentences = [
            {"text": "Chapter 3.", "start": 1490.5, "end": 1491.7},
            {"text": "Do one hard thing.", "start": 1492.4, "end": 1494.5},
            {"text": "Daily.", "start": 1494.8, "end": 1495.5},
        ]
        self.assertEqual(media_reader.heading_title(sentences, 0), "Chapter 3: Do one hard thing daily")

    def test_heading_extracts_inline_subtitle(self):
        sentences = [{"text": "Chapter 9 Cut what drains your energy.", "start": 4930.9, "end": 4934.9}]
        self.assertEqual(media_reader.heading_title(sentences, 0), "Chapter 9: Cut what drains your energy")

    def test_heading_trims_inline_subtitle_before_narration(self):
        sentences = [{"text": "Chapter 10 Build Consistency, Not Perfection Perfection is a trap.", "start": 5438.2, "end": 5445.5}]
        self.assertEqual(media_reader.heading_title(sentences, 0), "Chapter 10: Build Consistency, Not Perfection")

    def test_heading_ignores_lowercase_inline_narration(self):
        sentences = [{"text": "Chapter 2 is where things change.", "start": 10.0, "end": 12.0}]
        self.assertEqual(media_reader.heading_title(sentences, 0), "Chapter 2")

    def test_resolve_title_prefers_sidecar_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "compressed-audio.mp3"
            media.write_bytes(b"audio")
            (Path(directory) / "metadata.json").write_text(
                json.dumps({"title": "10 Positive Habits  That Stick"}), encoding="utf-8"
            )
            self.assertEqual(media_reader.resolve_title(media), "10 Positive Habits That Stick")
            self.assertEqual(media_reader.resolve_title(media, "My Title"), "My Title")

    def test_resolve_title_falls_back_to_cleaned_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "A useful talk [abcDEF_123].mp3"
            media.write_bytes(b"audio")
            self.assertEqual(media_reader.resolve_title(media), "A useful talk")

    def test_no_spoken_heading_uses_one_chapter(self):
        chapters = media_reader.detect_chapters([{"text": "Hello world.", "start": 0.2, "end": 1.0}])
        self.assertEqual([(item["start"], item["title"]) for item in chapters], [(0.0, "Transcript")])

    def test_chapters_detected_from_spoken_headings(self):
        sentences = [
            {"text": "Welcome in.", "start": 0.2, "end": 1.0},
            {"text": "Chapter one. The power of mornings.", "start": 30.0, "end": 33.0},
            {"text": "Body copy.", "start": 34.0, "end": 36.0},
            {"text": "Chapter 12. Why persistence matters.", "start": 90.0, "end": 93.0},
            {"text": "Conclusion.", "start": 150.0, "end": 151.0},
        ]
        chapters = media_reader.detect_chapters(sentences)
        self.assertEqual(
            [item["title"] for item in chapters],
            ["Introduction", "Chapter 1: The power of mornings", "Chapter 12: Why persistence matters", "Conclusion"],
        )

    def test_non_reader_directory_is_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "existing"
            output.mkdir()
            (output / "important.txt").write_text("keep", encoding="utf-8")
            source = root / "audio.mp3"
            source.write_bytes(b"audio")
            fingerprint = media_reader.source_fingerprint(source)
            with self.assertRaisesRegex(RuntimeError, "Refusing to write"):
                media_reader.prepare_output(output, source, fingerprint)
            self.assertEqual((output / "important.txt").read_text(), "keep")

    def test_reader_build_has_valid_timestamps_and_generator(self):
        asr = {
            "language": "en",
            "model": "test-model",
            "segments": [
                {
                    "words": [
                        {"word": " Hello", "start": 0.2, "end": 0.5, "probability": 0.99},
                        {"word": " world.", "start": 0.5, "end": 1.0, "probability": 0.98},
                        {"word": " Another", "start": 1.3, "end": 1.7, "probability": 0.97},
                        {"word": " sentence.", "start": 1.7, "end": 2.2, "probability": 0.96},
                    ]
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            reader = media_reader.build_reader(
                asr,
                {"mediaType": "audio", "duration": 2.5},
                "Test Reader",
                "media/source.mp3",
                public,
            )
            self.assertEqual(len(reader["sentences"]), 2)
            self.assertEqual(reader["generator"]["version"], media_reader.GENERATOR_VERSION)
            self.assertEqual(reader["alignment"]["averageWordConfidence"], 0.975)
            self.assertTrue((public / "data" / "subtitles.vtt").read_text().startswith("WEBVTT"))

    def test_cache_key_changes_with_model(self):
        fingerprint = {"sha256": "abc"}
        first = media_reader.asr_cache_key(fingerprint, "model-a")
        second = media_reader.asr_cache_key(fingerprint, "model-b")
        self.assertNotEqual(first, second)

    def confidence_reader(self, probability):
        asr = {
            "language": "en",
            "model": "test-model",
            "segments": [
                {
                    "words": [
                        {"word": " Hello", "start": 0.2, "end": 0.5, "probability": probability},
                        {"word": " world.", "start": 0.5, "end": 1.0, "probability": probability},
                    ]
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            return media_reader.build_reader(
                asr,
                {"mediaType": "audio", "duration": 1.5},
                "Test Reader",
                "media/source.mp3",
                Path(directory),
            )

    def test_alignment_method_names_the_engine(self):
        self.assertIn("Parakeet", self.confidence_reader(0.99)["alignment"]["method"])

    def test_low_confidence_threshold_is_calibrated_for_parakeet(self):
        # 0.90 would be a healthy Whisper word but is a weak Parakeet one, whose
        # greedy transducer probabilities bunch near 1.0.
        healthy = self.confidence_reader(0.99)["alignment"]
        weak = self.confidence_reader(0.90)["alignment"]
        self.assertEqual(healthy["lowConfidenceSentences"], 0)
        self.assertEqual(weak["lowConfidenceSentences"], 1)
        self.assertEqual(weak["lowConfidenceThreshold"], 0.95)


if __name__ == "__main__":
    unittest.main()
