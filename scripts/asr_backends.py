#!/usr/bin/env python3
"""Transcribe media with NVIDIA Parakeet TDT through sherpa-onnx.

Parakeet's duration head reports word timings directly, so the pipeline needs
no separate forced-alignment pass. It covers English and 24 other European
languages; there is no Chinese or other non-European support.

sherpa_onnx is imported inside functions so this module (and its callers) can
be imported without the engine installed.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

PARAKEET_MODEL = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
PARAKEET_RELEASE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{PARAKEET_MODEL}.tar.bz2"
)
# Parakeet decodes a whole window at once and its encoder memory grows with the
# window, so long media is cut into windows instead of streamed. Boundaries are
# nudged onto the quietest nearby frame so a cut never lands mid-word and no
# overlap stitching is needed.
PARAKEET_WINDOW_SECONDS = 60.0
PARAKEET_BOUNDARY_SEARCH_SECONDS = 8.0
# Roughly one window in ten collapses into a degenerate decode: punctuation and
# capitalization vanish and content is dropped, while the token count stops
# growing with the audio. It is sporadic rather than length-dependent (seen at
# 45s, 80s and 90s but not at 70s on the same file), so the recovery is to
# detect it and re-decode the window in halves, which reliably comes back clean.
PARAKEET_DEGENERATE_MINIMUM_SECONDS = 15.0
PARAKEET_MAXIMUM_RETRY_DEPTH = 3
SAMPLE_RATE = 16000
SEGMENT_PAUSE_SECONDS = 1.35
SEGMENT_MAXIMUM_WORDS = 60
END_RE = re.compile(r"[.!?](?:[\"'”’])?$")

_MODEL_CACHE: dict[str, object] = {}


def cache_root() -> Path:
    override = os.environ.get("INTERACTIVE_MEDIA_READER_CACHE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".cache" / "interactive-media-reader"


def default_model() -> str:
    return PARAKEET_MODEL


def thread_count() -> int:
    # Measured end-to-end on an 86-minute file (10-core Apple Silicon): 4
    # threads ran 4:10 using 882s of CPU, 6 threads ran 4:46 using 1377s —
    # slower and far hungrier, even though an isolated single-window benchmark
    # ranks 6 ahead. Kept below the core count; override to re-measure.
    return max(1, int(os.environ.get("INTERACTIVE_MEDIA_READER_THREADS", "4")))


def model_directory(model: str) -> Path:
    """Resolve a Parakeet model to a local directory, downloading it once."""
    override = os.environ.get("INTERACTIVE_MEDIA_READER_PARAKEET_DIR")
    candidate = Path(override).expanduser() if override else Path(model).expanduser()
    if (candidate / "encoder.int8.onnx").exists():
        return candidate

    target = cache_root() / "models" / PARAKEET_MODEL
    if (target / "encoder.int8.onnx").exists():
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {PARAKEET_MODEL} (~500 MB) to {target}", flush=True)
    with tempfile.TemporaryDirectory(prefix="parakeet-") as directory:
        archive = Path(directory) / "model.tar.bz2"
        urllib.request.urlretrieve(PARAKEET_RELEASE_URL, archive)
        with tarfile.open(archive, "r:bz2") as bundle:
            try:
                bundle.extractall(directory, filter="data")
            except TypeError:  # Python without the extraction filter
                bundle.extractall(directory)
        extracted = Path(directory) / PARAKEET_MODEL
        if not (extracted / "encoder.int8.onnx").exists():
            raise RuntimeError(f"{PARAKEET_RELEASE_URL} did not contain {PARAKEET_MODEL}/encoder.int8.onnx")
        shutil.move(str(extracted), str(target))
    return target


def recognizer(model: str):
    cached = _MODEL_CACHE.get(model)
    if cached is not None:
        return cached
    import sherpa_onnx

    directory = model_directory(model)
    engine = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(directory / "encoder.int8.onnx"),
        decoder=str(directory / "decoder.int8.onnx"),
        joiner=str(directory / "joiner.int8.onnx"),
        tokens=str(directory / "tokens.txt"),
        num_threads=thread_count(),
        model_type="nemo_transducer",
    )
    _MODEL_CACHE[model] = engine
    return engine


def load_audio(path: Path | str, sample_rate: int = SAMPLE_RATE):
    """Decode any ffmpeg-readable media to mono float32 samples."""
    import numpy as np

    process = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-map", "0:a:0", "-f", "f32le", "-ac", "1", "-ar", str(sample_rate), "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    return np.frombuffer(process.stdout, dtype=np.float32)


def quiet_windows(audio, sample_rate: int, window: float, search: float) -> list[tuple[float, float]]:
    """Split audio into windows, cutting at the quietest frame near each boundary."""
    import numpy as np

    total = len(audio) / sample_rate
    if total <= window:
        return [(0.0, total)]

    frame = max(1, int(0.1 * sample_rate))
    count = len(audio) // frame
    energy = np.sqrt((audio[: count * frame].astype(np.float32).reshape(count, frame) ** 2).mean(axis=1))

    bounds: list[tuple[float, float]] = []
    start = 0.0
    while total - start > window:
        low = max(start + window - search, start + search)
        high = min(total, start + window + search)
        low_index = int(low / 0.1)
        high_index = min(count, int(high / 0.1))
        cut = high if high_index <= low_index else (low_index + int(np.argmin(energy[low_index:high_index]))) * 0.1
        cut = min(max(cut, start + search), total)
        bounds.append((start, cut))
        start = cut
    if total - start > 0.01:
        bounds.append((start, total))
    return bounds


def tokens_to_words(tokens, timestamps, durations, log_probabilities, offset: float) -> list[dict]:
    """Merge sherpa-onnx subword tokens into whisper-shaped words.

    Parakeet emits subwords (' Un', 'c', 'ont', 'rol', 'led'); a leading space
    starts a new word. Timing comes from the TDT duration head and the per-word
    probability is the geometric mean of its token probabilities.
    """
    words: list[dict] = []
    for index, token in enumerate(tokens):
        start = offset + float(timestamps[index])
        duration = float(durations[index]) if index < len(durations) else 0.0
        log_probability = float(log_probabilities[index]) if index < len(log_probabilities) else 0.0
        if token.startswith(" ") or not words:
            words.append({"word": token, "start": start, "end": start + duration, "logProbabilities": [log_probability]})
            continue
        current = words[-1]
        current["word"] += token
        current["end"] = max(current["end"], start + duration)
        current["logProbabilities"].append(log_probability)

    for word in words:
        log_probabilities = word.pop("logProbabilities")
        mean = sum(log_probabilities) / len(log_probabilities)
        word["probability"] = round(math.exp(mean), 6)
        word["start"] = round(word["start"], 3)
        word["end"] = round(max(word["end"], word["start"] + 0.01), 3)
    return words


def words_to_segments(words: list[dict], language: str | None) -> dict:
    """Group words into segments on sentence ends and pauses.

    Segments are what the reader turns into clickable sentences, so a segment
    closes on a sentence end, on a pause long enough to read as one, or at a
    word cap that stops an unpunctuated stretch from running away.
    """
    segments: list[dict] = []
    current: list[dict] = []

    def flush() -> None:
        if not current:
            return
        text = re.sub(r"\s+", " ", "".join(word["word"] for word in current)).strip()
        segments.append(
            {
                "id": len(segments),
                "seek": int(round(current[-1]["end"] * 100)),
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": f" {text}",
                "words": list(current),
            }
        )
        current.clear()

    for word in words:
        if current and word["start"] - current[-1]["end"] > SEGMENT_PAUSE_SECONDS:
            flush()
        current.append(word)
        if END_RE.search(word["word"].strip()) or len(current) >= SEGMENT_MAXIMUM_WORDS:
            flush()
    flush()

    return {
        "text": "".join(segment["text"] for segment in segments),
        "segments": segments,
        "language": language,
    }


def is_degenerate(tokens, duration: float) -> bool:
    """Detect a collapsed Parakeet decode.

    Continuous speech longer than a few seconds effectively always contains a
    sentence end, so a window that yields none has dropped its punctuation head
    and, with it, content.
    """
    if duration < PARAKEET_DEGENERATE_MINIMUM_SECONDS:
        return False
    return not any(token.strip().endswith((".", "!", "?")) for token in tokens)


def decode_window(engine, audio, start: float, end: float, depth: int = 0) -> list[dict]:
    chunk = audio[int(start * SAMPLE_RATE) : int(end * SAMPLE_RATE)]
    if not len(chunk):
        return []

    stream = engine.create_stream()
    stream.accept_waveform(SAMPLE_RATE, chunk)
    engine.decode_stream(stream)
    result = stream.result

    if is_degenerate(result.tokens, end - start) and depth < PARAKEET_MAXIMUM_RETRY_DEPTH:
        halves = quiet_windows(
            chunk,
            SAMPLE_RATE,
            (end - start) / 2,
            min(PARAKEET_BOUNDARY_SEARCH_SECONDS, (end - start) / 5),
        )
        if len(halves) > 1:
            print(f"  degenerate decode at {start:.0f}-{end:.0f}s; retrying in {len(halves)} parts", flush=True)
            recovered: list[dict] = []
            for half_start, half_end in halves:
                recovered.extend(decode_window(engine, audio, start + half_start, start + half_end, depth + 1))
            return recovered

    return tokens_to_words(result.tokens, result.timestamps, result.durations, result.ys_log_probs, start)


def transcribe_file(path: Path | str, model: str, *, language: str | None = None) -> dict:
    audio = load_audio(path)
    engine = recognizer(model)
    windows = quiet_windows(audio, SAMPLE_RATE, PARAKEET_WINDOW_SECONDS, PARAKEET_BOUNDARY_SEARCH_SECONDS)

    words: list[dict] = []
    for index, (start, end) in enumerate(windows):
        words.extend(decode_window(engine, audio, start, end))
        if len(windows) > 1 and (index + 1) % 10 == 0:
            print(f"  window {index + 1}/{len(windows)} ({end:.0f}s)", flush=True)

    return words_to_segments(words, language or "en")
