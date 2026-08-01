#!/usr/bin/env python3
"""Detect speech-bearing holes in long-form Whisper output and re-transcribe them.

Long-form Whisper can occasionally advance past audio after predicting an early
end timestamp. This script scans gaps between ASR segments, re-transcribes each
candidate in short overlapping windows, and replaces boundary segments only when
confident speech is recovered inside the gap.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import mlx_whisper

END_RE = re.compile(r"[.!?](?:[\"'”’])?$")


def extract_clip(audio: Path, output: Path, start: float, end: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
            "-t", f"{end - start:.3f}", "-i", str(audio), "-map", "0:a:0",
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-y", str(output),
        ],
        check=True,
    )


def transcribe_region(
    audio: Path,
    start: float,
    end: float,
    model: str,
    language: str | None,
    temporary_directory: Path,
    owner_seconds: float = 18.0,
    context_seconds: float = 3.0,
) -> list[dict]:
    """Transcribe a region in short windows and return non-overlapping timed words."""
    span = max(0.01, end - start)
    part_count = max(1, math.ceil(span / owner_seconds))
    part_span = span / part_count
    recovered: list[dict] = []

    for part in range(part_count):
        owner_start = start + part * part_span
        owner_end = end if part == part_count - 1 else start + (part + 1) * part_span
        clip_start = max(0.0, owner_start - context_seconds)
        clip_end = owner_end + context_seconds
        clip_path = temporary_directory / f"clip-{start:.3f}-{part}.wav"
        extract_clip(audio, clip_path, clip_start, clip_end)
        result = mlx_whisper.transcribe(
            str(clip_path),
            path_or_hf_repo=model,
            language=language,
            task="transcribe",
            word_timestamps=True,
            condition_on_previous_text=False,
            hallucination_silence_threshold=None,
            verbose=None,
        )
        for segment in result.get("segments", []):
            for word in segment.get("words", []):
                if word.get("start") is None or word.get("end") is None:
                    continue
                absolute_start = clip_start + float(word["start"])
                absolute_end = clip_start + float(word["end"])
                midpoint = (absolute_start + absolute_end) / 2
                if owner_start <= midpoint < owner_end or (
                    part == part_count - 1 and owner_start <= midpoint <= owner_end
                ):
                    recovered.append(
                        {
                            "word": str(word.get("word", "")),
                            "start": round(absolute_start, 3),
                            "end": round(max(absolute_start + 0.01, absolute_end), 3),
                            "probability": round(float(word.get("probability", 1.0)), 6),
                        }
                    )

    recovered.sort(key=lambda item: (item["start"], item["end"]))

    # Neighboring short windows can assign slightly different timestamps to the
    # same boundary word. Merge only overlapping identical tokens; intentional
    # repetitions have consecutive, non-overlapping timestamps and are retained.
    stitched: list[dict] = []
    for word in recovered:
        normalized = re.sub(r"[^a-z0-9']+", "", word["word"].lower())
        if stitched:
            previous = stitched[-1]
            previous_normalized = re.sub(r"[^a-z0-9']+", "", previous["word"].lower())
            if normalized and normalized == previous_normalized and word["start"] <= previous["end"] + 0.05:
                previous["start"] = min(previous["start"], word["start"])
                previous["end"] = max(previous["end"], word["end"])
                previous["probability"] = max(previous["probability"], word["probability"])
                if END_RE.search(word["word"].strip()) or len(word["word"].strip()) > len(previous["word"].strip()):
                    previous["word"] = word["word"]
                continue
        stitched.append(word)
    return stitched


def words_to_segments(words: list[dict]) -> list[dict]:
    segments: list[dict] = []
    current: list[dict] = []
    for word in words:
        if current and word["start"] - current[-1]["end"] > 1.35:
            segments.append(make_segment(current))
            current = []
        current.append(word)
        if END_RE.search(word["word"].strip()) or len(current) >= 60:
            segments.append(make_segment(current))
            current = []
    if current:
        segments.append(make_segment(current))
    return segments


def make_segment(words: list[dict]) -> dict:
    text = re.sub(r"\s+", " ", "".join(word["word"] for word in words)).strip()
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": f" {text}",
        "words": words,
        "repaired": True,
    }


def recovered_text(words: list[dict]) -> str:
    return re.sub(r"\s+", " ", "".join(word["word"] for word in words)).strip()


def is_confirmed(gap_start: float, gap_end: float, words: list[dict]) -> tuple[bool, list[dict]]:
    inside = [
        word for word in words
        if gap_start + 0.08 <= (word["start"] + word["end"]) / 2 <= gap_end - 0.08
        and word["probability"] >= 0.55
    ]
    if not inside:
        return False, inside
    duration = gap_end - gap_start
    average_probability = sum(word["probability"] for word in inside) / len(inside)
    spoken_duration = sum(max(0.0, word["end"] - word["start"]) for word in inside)
    if duration >= 3.0:
        confirmed = len(inside) >= 2 and average_probability >= 0.7 and spoken_duration >= 0.35
    else:
        confirmed = len(inside) >= 2 and average_probability >= 0.82 and spoken_duration >= 0.3
    return confirmed, inside


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("asr", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--model", default="mlx-community/whisper-large-v3-turbo")
    parser.add_argument("--min-gap", type=float, default=1.5)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and not args.force:
        print(f"Repaired ASR already exists: {args.output}")
        return

    source = json.loads(args.asr.read_text(encoding="utf-8"))
    segments = sorted(source.get("segments", []), key=lambda item: float(item["start"]))
    candidates = []
    for index, (previous, following) in enumerate(zip(segments, segments[1:])):
        gap_start = float(previous["end"])
        gap_end = float(following["start"])
        if gap_end - gap_start >= args.min_gap:
            candidates.append((index, previous, following, gap_start, gap_end))

    audit = []
    repairs = []
    with tempfile.TemporaryDirectory(prefix="audio-reader-gap-") as directory:
        temporary_directory = Path(directory)
        for number, (_, previous, following, gap_start, gap_end) in enumerate(candidates, 1):
            region_start = float(previous["start"])
            region_end = float(following["end"])
            print(
                f"[{number}/{len(candidates)}] Checking {gap_start:.2f}-{gap_end:.2f} "
                f"({gap_end - gap_start:.2f}s)",
                flush=True,
            )
            words = transcribe_region(
                args.audio,
                region_start,
                region_end,
                args.model,
                source.get("language"),
                temporary_directory,
            )
            confirmed, inside = is_confirmed(gap_start, gap_end, words)
            # Preserve the casing of the original boundary sentence when the
            # short clip lacks enough left context to capitalize its first word.
            previous_text = str(previous.get("text", "")).strip()
            if words and previous_text and previous_text[0].isupper():
                raw_word = words[0]["word"]
                first_alpha = next((i for i, char in enumerate(raw_word) if char.isalpha()), None)
                if first_alpha is not None:
                    words[0]["word"] = raw_word[:first_alpha] + raw_word[first_alpha].upper() + raw_word[first_alpha + 1:]
            record = {
                "gapStart": round(gap_start, 3),
                "gapEnd": round(gap_end, 3),
                "gapDuration": round(gap_end - gap_start, 3),
                "previousText": previous.get("text", "").strip(),
                "followingText": following.get("text", "").strip(),
                "recoveredInsideGap": recovered_text(inside),
                "replacementText": recovered_text(words),
                "recoveredWords": len(inside),
                "confirmed": confirmed,
            }
            audit.append(record)
            if confirmed:
                repairs.append({"start": region_start, "end": region_end, "words": words, "audit": record})
                print(f"  REPAIR: {record['recoveredInsideGap']}", flush=True)

    # Keep original segments outside repair regions and insert short-window replacements.
    repaired_segments = list(segments)
    for repair in repairs:
        repaired_segments = [
            segment for segment in repaired_segments
            if float(segment["end"]) <= repair["start"] or float(segment["start"]) >= repair["end"]
        ]
        repaired_segments.extend(words_to_segments(repair["words"]))
    repaired_segments.sort(key=lambda item: (float(item["start"]), float(item["end"])))
    for index, segment in enumerate(repaired_segments):
        segment["id"] = index
        segment["seek"] = int(round(float(segment["end"]) * 100))

    remaining_gaps = [
        float(following["start"]) - float(previous["end"])
        for previous, following in zip(repaired_segments, repaired_segments[1:])
        if float(following["start"]) - float(previous["end"]) >= args.min_gap
    ]
    output = dict(source)
    output["segments"] = repaired_segments
    output["text"] = "".join(segment.get("text", "") for segment in repaired_segments)
    output["gapRepair"] = {
        "method": "short overlapping MLX Whisper windows",
        "candidateGaps": len(candidates),
        "repairedGaps": len(repairs),
        "minimumGap": args.min_gap,
        "remainingGaps": len(remaining_gaps),
        "maximumRemainingGap": round(max(remaining_gaps, default=0.0), 3),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    args.report.write_text(
        json.dumps({"summary": output["gapRepair"], "gaps": audit}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(output["gapRepair"], ensure_ascii=False))


if __name__ == "__main__":
    main()
