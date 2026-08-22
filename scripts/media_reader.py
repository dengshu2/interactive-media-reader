#!/usr/bin/env python3
"""Build an audio-only English interactive reader from one local media file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser
from bisect import bisect_right
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = SKILL_DIR / "assets"
SERVE_SCRIPT = SKILL_DIR / "scripts" / "serve.py"
END_RE = re.compile(r"[.!?](?:[\"'”’])?$")
HEADING_RE = re.compile(
    r"^(?P<kind>chapter|part|lesson|section)\s+(?P<number>\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\b",
    re.I,
)
NUMBER_WORDS = {
    word: index for index, word in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
OUTRO_RE = re.compile(r"^(?:outro|conclusion)\b|(?:you(?:'ve| have)? reached the end)", re.I)
ALIGNMENT_METHOD = "Parakeet TDT duration-head word timestamps with degenerate-window re-decoding"
# Parakeet's greedy transducer probabilities bunch near 1.0, so this sits much
# higher than a Whisper-calibrated threshold would; it marks roughly the weakest
# 4% of sentences on real material.
LOW_CONFIDENCE_THRESHOLD = 0.95
GENERATOR_VERSION = "0.6.0"
ASR_PIPELINE_VERSION = 3
PLAYBACK_AUDIO_VERSION = 1
PROJECT_MARKER = ".interactive-media-reader.json"
SERVER_HEALTH_PATH = "/.interactive-media-reader-health"
TRANSCRIBE_OPTIONS = {
    "task": "transcribe",
    "window": "quiet-boundary",
    "windowSeconds": 60.0,
}
PLAYBACK_AUDIO_OPTIONS = {
    "codec": "aac",
    "bitrate": "64k",
    "channels": 1,
    "sampleRate": 48000,
}


def json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Cannot serialize {type(value)!r}")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.stem + "-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=json_default)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def probe_media(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    if not any(stream.get("codec_type") == "audio" for stream in streams):
        raise RuntimeError("The input has no audio stream")
    duration_values = [
        float(value) for value in [payload.get("format", {}).get("duration")]
        if value not in (None, "N/A")
    ]
    duration_values.extend(
        float(stream["duration"]) for stream in streams
        if stream.get("duration") not in (None, "N/A")
    )
    video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
    motion_video = [
        stream for stream in video_streams
        if not bool(stream.get("disposition", {}).get("attached_pic"))
    ]
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    return {
        "sourceMediaType": "video" if motion_video else "audio",
        "duration": max(duration_values, default=0.0),
        "audioCodec": str(audio_streams[0].get("codec_name", "")).lower(),
        "hasVideoStream": bool(video_streams),
    }


def source_fingerprint(path: Path) -> dict:
    stat = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {
        "size": stat.st_size,
        "sha256": digest.hexdigest(),
    }


def clean_title(path: Path) -> str:
    title = path.stem
    title = re.sub(r"\s*\[[A-Za-z0-9_-]{6,}\]\s*", " ", title)
    title = re.sub(r"\s*[-–—]\s*compressed\s*$", "", title, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" -–—_")
    return title or "Interactive Media Reader"


def metadata_title(media: Path) -> str | None:
    """Prefer a yt-dlp sidecar title over the often-mangled download filename."""
    candidates = [media.with_suffix(".info.json"), media.with_name("metadata.json")]
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict):
            title = str(payload.get("title") or payload.get("fulltitle") or "").strip()
            if title:
                return re.sub(r"\s+", " ", title)
    return None


def resolve_title(media: Path, override: str | None = None) -> str:
    if override and override.strip():
        return re.sub(r"\s+", " ", override).strip()
    return metadata_title(media) or clean_title(media)


def asr_cache_key(fingerprint: dict, model: str) -> dict:
    return {
        "pipelineVersion": ASR_PIPELINE_VERSION,
        "model": model,
        "options": TRANSCRIBE_OPTIONS,
        "source": fingerprint,
    }


def transcribe(media: Path, output: Path, fingerprint: dict, model: str) -> dict:
    try:
        from asr_backends import transcribe_file
    except ImportError as error:
        raise RuntimeError("ASR engine is unavailable; rerun through scripts/build.sh") from error

    expected_cache_key = asr_cache_key(fingerprint, model)
    if output.exists():
        cached = json.loads(output.read_text(encoding="utf-8"))
        if cached.get("cacheKey") == expected_cache_key:
            print(f"Using cached transcription: {output}", flush=True)
            return cached
        print("Transcription cache is stale; rebuilding.", flush=True)
        output.unlink()

    print(f"Transcribing {media.name} with {model}", flush=True)
    result = transcribe_file(media, model)
    result["model"] = model
    result["cacheKey"] = expected_cache_key
    result["sourceFingerprint"] = fingerprint
    result["sourcePath"] = str(media.resolve())
    atomic_json(output, result)
    return result


def timed_sentences(asr: dict) -> list[dict]:
    words = [
        word for segment in asr.get("segments", []) for word in segment.get("words", [])
        if word.get("start") is not None and word.get("end") is not None and str(word.get("word", "")).strip()
    ]
    sentences = []
    current = []
    for word in words:
        current.append(word)
        if END_RE.search(str(word["word"]).strip()) or len(current) >= 60:
            sentences.append(make_sentence(current, len(sentences)))
            current = []
    if current:
        sentences.append(make_sentence(current, len(sentences)))
    return sentences


def make_sentence(words: list[dict], index: int) -> dict:
    text = re.sub(r"\s+", " ", "".join(str(word["word"]) for word in words)).strip()
    probabilities = [float(word.get("probability", 1.0)) for word in words]
    return {
        "id": f"s{index + 1:05d}",
        "order": index,
        "text": text,
        "start": round(float(words[0]["start"]), 3),
        "end": round(float(words[-1]["end"]), 3),
        "confidence": round(statistics.fmean(probabilities), 3),
        "wordCount": len(words),
    }


def parse_heading(text: str) -> dict | None:
    """Match a spoken chapter heading.

    Returns the dedup key parts (kind, number), a display label preserving the
    spoken number form, and the match end for subtitle extraction.
    """
    match = HEADING_RE.search(text)
    if not match:
        return None
    raw_number = match.group("number").lower()
    number = int(raw_number) if raw_number.isdigit() else NUMBER_WORDS[raw_number]
    return {
        "kind": match.group("kind").lower(),
        "number": number,
        "label": f"{match.group('kind').capitalize()} {number}",
        "end": match.end(),
    }


def collapse_adjacent_duplicates(words: list[str]) -> list[str]:
    collapsed: list[str] = []
    for word in words:
        if collapsed and word.lower().strip(",.;:!?") == collapsed[-1].lower().strip(",.;:!?"):
            continue
        collapsed.append(word)
    return collapsed


def inline_subtitle(remainder: str) -> str | None:
    """Extract a subtitle spoken in the same ASR sentence as the heading.

    A short capitalized remainder is the whole subtitle ("Chapter 9 Cut what
    drains your energy."). A longer remainder usually runs into narration, so
    only its leading title-cased words are trusted.
    """
    words = remainder.split()
    if not words:
        return None
    first_alpha = next((char for char in words[0] if char.isalpha()), "")
    if not first_alpha.isupper():
        return None
    if len(words) <= 6:
        return " ".join(collapse_adjacent_duplicates(words)).rstrip(".!?,;:")
    run = []
    for word in words:
        alpha = next((char for char in word if char.isalpha()), "")
        if not alpha or not alpha.isupper():
            break
        run.append(word)
    run = collapse_adjacent_duplicates(run)
    if 2 <= len(run) <= 8:
        return " ".join(run).rstrip(".!?,;:")
    return None


def heading_title(sentences: list[dict], index: int) -> str:
    text = sentences[index]["text"].strip()
    parsed = parse_heading(text)
    if not parsed:
        return text.rstrip(".!?")
    heading = parsed["label"]
    remainder = text[parsed["end"]:].strip(" .:—–-")
    if remainder:
        subtitle = inline_subtitle(remainder)
        return f"{heading}: {subtitle}" if subtitle else heading
    additions: list[str] = []
    previous_end = sentences[index]["end"]
    for following in sentences[index + 1:index + 3]:
        words = following["text"].split()
        if len(words) > 6 or following["start"] - previous_end > 2.0 or parse_heading(following["text"].strip()):
            break
        addition = following["text"].strip().rstrip(".!?,")
        previous_end = following["end"]
        # Narrators often speak the subtitle twice; keep one copy.
        if any(existing.lower() == addition.lower() for existing in additions):
            continue
        additions.append(addition)
        if sum(len(item.split()) for item in additions) >= 7:
            break
    if not additions:
        return heading
    subtitle = additions[0]
    for addition in additions[1:]:
        if len(addition.split()) == 1:
            # A single-word ASR sentence ("Daily.") continues the phrase.
            subtitle += f" {addition[0].lower()}{addition[1:]}"
        else:
            subtitle += f", {addition}"
    return f"{heading}: {subtitle}"


def detect_chapters(sentences: list[dict]) -> list[dict]:
    boundaries: list[tuple[float, str]] = []
    # Long-form narration may preview a chapter before speaking its real heading.
    # Keep the final occurrence of each explicit chapter/part number.
    by_heading = {}
    for index, item in enumerate(sentences):
        parsed = parse_heading(item["text"].strip())
        if not parsed:
            continue
        by_heading[(parsed["kind"], parsed["number"])] = (index, item)
    headings = sorted(by_heading.values(), key=lambda pair: pair[1]["start"])
    if headings:
        first_start = headings[0][1]["start"]
        if first_start > 8:
            boundaries.append((0.0, "Introduction"))
        for index, item in headings:
            boundaries.append((item["start"], heading_title(sentences, index)))
        for item in sentences:
            if OUTRO_RE.search(item["text"].strip()) and item["start"] > boundaries[-1][0] + 30:
                boundaries.append((item["start"], "Conclusion"))
                break
    else:
        boundaries.append((0.0, "Transcript"))

    deduplicated = []
    for start, title in sorted(boundaries):
        if deduplicated and start - deduplicated[-1][0] < 5:
            continue
        deduplicated.append((start, title))
    return [
        {"id": f"chapter-{index + 1:02d}", "order": index, "title": title, "start": round(start, 3)}
        for index, (start, title) in enumerate(deduplicated)
    ]


def vtt_timestamp(value: float) -> str:
    milliseconds = max(0, round(value * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def build_reader(asr: dict, info: dict, title: str, media_url: str, public: Path) -> dict:
    sentences = timed_sentences(asr)
    if not sentences:
        raise RuntimeError("Transcription produced no timed sentences")
    chapters = detect_chapters(sentences)
    starts = [chapter["start"] for chapter in chapters]
    counts = [0] * len(chapters)
    for sentence in sentences:
        chapter_index = max(0, bisect_right(starts, sentence["start"]) - 1)
        sentence["chapterId"] = chapters[chapter_index]["id"]
        counts[chapter_index] += 1
    for index, chapter in enumerate(chapters):
        chapter["sentenceCount"] = counts[index]

    word_count = sum(item["wordCount"] for item in sentences)
    confidence = sum(item["confidence"] * item["wordCount"] for item in sentences) / word_count
    low_confidence = LOW_CONFIDENCE_THRESHOLD
    quality = f"EN 转写 · 置信度 {confidence:.0%}"
    reader = {
        "version": 1,
        "generator": {
            "name": "interactive-media-reader",
            "version": GENERATOR_VERSION,
            "model": asr.get("model"),
            "asrPipelineVersion": ASR_PIPELINE_VERSION,
        },
        "title": title,
        "mediaUrl": media_url,
        "audioUrl": media_url,
        "mediaType": "audio",
        "sourceLanguage": "en",
        "duration": info["duration"] or sentences[-1]["end"],
        "chapters": chapters,
        "sentences": sentences,
        "alignment": {
            "method": ALIGNMENT_METHOD,
            "mode": "english-asr",
            "averageWordConfidence": round(confidence, 4),
            "lowConfidenceSentences": sum(item["confidence"] < low_confidence for item in sentences),
            "lowConfidenceThreshold": low_confidence,
            "display": quality,
        },
    }
    data_dir = public / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(data_dir / "reader.json", reader)
    with (data_dir / "subtitles.vtt").open("w", encoding="utf-8") as handle:
        handle.write("WEBVTT\n\n")
        for sentence in sentences:
            handle.write(
                f"{sentence['id']}\n{vtt_timestamp(sentence['start'])} --> "
                f"{vtt_timestamp(sentence['end'])}\n{sentence['text']}\n\n"
            )
    return reader


def prepare_output(output: Path, media: Path, fingerprint: dict) -> None:
    marker = output / PROJECT_MARKER
    if output.exists() and not output.is_dir():
        raise RuntimeError(f"Output path is not a directory: {output}")
    if output.exists():
        if marker.exists():
            metadata = json.loads(marker.read_text(encoding="utf-8"))
            if metadata.get("sourceFingerprint") != fingerprint:
                raise RuntimeError(f"Output belongs to another media file: {output}")
        elif any(output.iterdir()):
            raise RuntimeError(
                f"Refusing to write into a non-reader directory: {output}. "
                "Choose an empty output directory."
            )
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(
        marker,
        {
            "project": "interactive-media-reader",
            "generatorVersion": GENERATOR_VERSION,
            "sourcePath": str(media.resolve()),
            "sourceFingerprint": fingerprint,
        },
    )


def prepare_public(output: Path) -> Path:
    public = output / "public"
    public.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copy2(ASSETS_DIR / name, public / name)
    return public


def remove_stale_media(media_dir: Path, keep: Path) -> None:
    """Remove media artifacts owned by an existing reader, including v0.5 video links."""
    for path in media_dir.iterdir():
        if path == keep:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def playback_audio_cache_key(source_fingerprint: dict) -> dict:
    return {
        "version": PLAYBACK_AUDIO_VERSION,
        "source": source_fingerprint,
        "options": PLAYBACK_AUDIO_OPTIONS,
    }


def prepare_playback_audio(media: Path, output: Path, source_fingerprint: dict) -> Path:
    """Normalize the first source audio stream to an audio-only browser asset."""
    public = output / "public"
    media_dir = public / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    playback = media_dir / "source.m4a"
    manifest = output / "work" / "playback-audio.json"
    expected = playback_audio_cache_key(source_fingerprint)

    if playback.is_file() and not playback.is_symlink() and manifest.exists():
        try:
            cached = json.loads(manifest.read_text(encoding="utf-8"))
            playback_info = probe_media(playback)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            cached = None
            playback_info = {}
        if (
            cached == expected
            and playback_info.get("audioCodec") == "aac"
            and not playback_info.get("hasVideoStream", True)
        ):
            remove_stale_media(media_dir, playback)
            return playback

    fd, temporary_name = tempfile.mkstemp(prefix="source-", suffix=".m4a", dir=media_dir)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-v", "error",
                "-y",
                "-i", str(media),
                "-map", "0:a:0",
                "-vn",
                "-sn",
                "-dn",
                "-c:a", PLAYBACK_AUDIO_OPTIONS["codec"],
                "-b:a", PLAYBACK_AUDIO_OPTIONS["bitrate"],
                "-ac", str(PLAYBACK_AUDIO_OPTIONS["channels"]),
                "-ar", str(PLAYBACK_AUDIO_OPTIONS["sampleRate"]),
                "-movflags", "+faststart",
                str(temporary),
            ],
            check=True,
        )
        playback_info = probe_media(temporary)
        if playback_info["audioCodec"] != "aac" or playback_info["hasVideoStream"]:
            raise RuntimeError("Normalized playback asset is not audio-only AAC")
        os.replace(temporary, playback)
        remove_stale_media(media_dir, playback)
        atomic_json(manifest, expected)
        return playback
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_output(output: Path) -> dict:
    public = output / "public"
    required = [public / "index.html", public / "styles.css", public / "app.js", public / "data/reader.json"]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing generated files: {', '.join(missing)}")
    reader = json.loads((public / "data/reader.json").read_text(encoding="utf-8"))
    sentences = reader.get("sentences", [])
    if not sentences or not reader.get("chapters"):
        raise RuntimeError("Generated reader has no sentences or chapters")
    if any(float(item["start"]) >= float(item["end"]) for item in sentences):
        raise RuntimeError("Generated reader contains invalid sentence timestamps")
    if reader.get("mediaType") != "audio":
        raise RuntimeError("Generated reader is not audio-only")
    media = public / reader["mediaUrl"]
    if not media.is_file() or media.is_symlink():
        raise RuntimeError(f"Generated audio asset is missing or not self-contained: {media}")
    media_info = probe_media(media)
    if media_info["audioCodec"] != "aac" or media_info["hasVideoStream"]:
        raise RuntimeError(f"Generated playback asset is not audio-only AAC: {media}")
    return reader


def available_port(start: int = 8765) -> int:
    for port in range(start, start + 100):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No local preview port available")


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def server_health(url: str, token: str, pid: int, timeout: float = 0.5) -> bool:
    if not url or not token:
        return False
    request = urllib.request.Request(
        f"{url.rstrip('/')}{SERVER_HEALTH_PATH}",
        headers={"X-Interactive-Media-Reader-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
        return response.status == 200 and payload == {"ok": True, "pid": pid}
    except (OSError, ValueError, urllib.error.URLError):
        return False


def launch_server(output: Path) -> str:
    metadata_path = output / ".server.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            pid = int(metadata["pid"])
            if process_alive(pid) and server_health(
                str(metadata["url"]), str(metadata.get("token", "")), pid
            ):
                return str(metadata["url"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass

    port = available_port()
    token = secrets.token_urlsafe(32)
    with (output / "server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                str(SERVE_SCRIPT),
                "--directory",
                str(output / "public"),
                "--port",
                str(port),
                "--token",
                token,
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    url = f"http://localhost:{port}"
    deadline = time.time() + 3
    while time.time() < deadline:
        if process.poll() is not None:
            break
        if server_health(url, token, process.pid):
            atomic_json(metadata_path, {"pid": process.pid, "port": port, "url": url, "token": token})
            return url
        time.sleep(0.05)
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=3)
    raise RuntimeError(f"Preview server failed health verification; see {output / 'server.log'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", help="Parakeet model directory; defaults to the cached release build")
    parser.add_argument("--title", help="display title; defaults to a yt-dlp sidecar title, then the cleaned filename")
    parser.add_argument("--open", action="store_true", dest="open_preview")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    media = args.media.expanduser().resolve()
    if not media.is_file():
        parser.error(f"media file does not exist: {media}")
    output = (args.output.expanduser().resolve() if args.output else media.with_name(f"{media.stem}-reader"))
    if output in media.parents:
        parser.error("media input must be outside the reader output directory")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe are required")
    if args.validate_only:
        reader = validate_output(output)
        print(json.dumps({"valid": True, "output": str(output), "sentences": len(reader["sentences"])}, ensure_ascii=False))
        return

    from asr_backends import default_model
    model = args.model or default_model()
    source_info = probe_media(media)
    source_fingerprint_value = source_fingerprint(media)
    prepare_output(output, media, source_fingerprint_value)
    public = prepare_public(output)
    playback = prepare_playback_audio(media, output, source_fingerprint_value)
    playback_info = probe_media(playback)
    playback_fingerprint = source_fingerprint(playback)
    asr_path = output / "work" / "asr.json"
    asr = transcribe(playback, asr_path, playback_fingerprint, model)
    media_url = f"media/{playback.name}"
    reader = build_reader(asr, playback_info, resolve_title(media, args.title), media_url, public)
    validate_output(output)

    url = None
    if args.open_preview:
        url = launch_server(output)
        webbrowser.open(url)
    summary = {
        "valid": True,
        "input": str(media),
        "output": str(output),
        "title": reader["title"],
        "model": model,
        "mediaType": "audio",
        "sourceMediaType": source_info["sourceMediaType"],
        "language": reader["sourceLanguage"],
        "sentences": len(reader["sentences"]),
        "chapters": len(reader["chapters"]),
        "lowConfidenceSentences": reader["alignment"]["lowConfidenceSentences"],
        "url": url,
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
