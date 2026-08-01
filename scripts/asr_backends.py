#!/usr/bin/env python3
"""Select and adapt a Whisper engine for the current platform.

Apple Silicon uses MLX Whisper; every other platform uses faster-whisper.
Engine imports stay inside functions so this module (and its callers) can be
imported without either engine installed.
"""

from __future__ import annotations

import platform
from pathlib import Path

_MODEL_CACHE: dict[str, object] = {}


def backend_name() -> str:
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "mlx"
    return "faster-whisper"


def default_model(backend: str | None = None) -> str:
    backend = backend or backend_name()
    if backend == "mlx":
        return "mlx-community/whisper-large-v3-turbo"
    return "large-v3-turbo"


def faster_result_to_whisper(segments, info) -> dict:
    """Convert faster-whisper streaming output to the whisper result shape."""
    converted = []
    for segment in segments:
        words = [
            {
                "word": word.word,
                "start": float(word.start),
                "end": float(word.end),
                "probability": float(word.probability),
            }
            for word in (segment.words or [])
        ]
        converted.append(
            {
                "id": getattr(segment, "id", len(converted)),
                "seek": getattr(segment, "seek", 0),
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text,
                "words": words,
            }
        )
    return {
        "text": "".join(segment["text"] for segment in converted),
        "segments": converted,
        "language": getattr(info, "language", None),
    }


def transcribe_file(
    path: Path | str,
    model: str,
    *,
    language: str | None = None,
    condition_on_previous_text: bool,
    hallucination_silence_threshold: float | None,
    backend: str | None = None,
) -> dict:
    backend = backend or backend_name()
    if backend == "mlx":
        import mlx_whisper

        return mlx_whisper.transcribe(
            str(path),
            path_or_hf_repo=model,
            verbose=False,
            task="transcribe",
            language=language,
            word_timestamps=True,
            condition_on_previous_text=condition_on_previous_text,
            hallucination_silence_threshold=hallucination_silence_threshold,
        )

    from faster_whisper import WhisperModel

    whisper = _MODEL_CACHE.get(model)
    if whisper is None:
        whisper = _MODEL_CACHE[model] = WhisperModel(model, device="auto", compute_type="auto")
    segments, info = whisper.transcribe(
        str(path),
        task="transcribe",
        language=language,
        word_timestamps=True,
        condition_on_previous_text=condition_on_previous_text,
        hallucination_silence_threshold=hallucination_silence_threshold,
    )
    return faster_result_to_whisper(segments, info)
