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

    def test_no_spoken_heading_uses_one_chapter(self):
        chapters = media_reader.detect_chapters([{"text": "Hello world.", "start": 0.2, "end": 1.0}])
        self.assertEqual([(item["start"], item["title"]) for item in chapters], [(0.0, "Transcript")])

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
            "gapRepair": {"repairedGaps": 1},
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
            self.assertEqual(reader["alignment"]["repairedGaps"], 1)
            self.assertTrue((public / "data" / "subtitles.vtt").read_text().startswith("WEBVTT"))

    def test_cache_key_changes_with_model(self):
        fingerprint = {"sha256": "abc"}
        first = media_reader.asr_cache_key(fingerprint, "model-a")
        second = media_reader.asr_cache_key(fingerprint, "model-b")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
