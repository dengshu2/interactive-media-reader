---
name: interactive-media-reader
description: Convert one local audio or video file into a same-language interactive transcript reader with sentence-click playback, synchronized highlighting, chapters, keyboard controls, and a local preview URL. Use when the user asks to turn a local media file into a clickable reader, audio reader, video transcript page, or 跟读/点句播放/字幕阅读页面. Requires only the media path; never request or generate a translation or transcript manuscript.
compatibility: Python 3.11/3.12 and ffmpeg; MLX Whisper on Apple Silicon, faster-whisper elsewhere; the model downloads on first use.
---

# Interactive Media Reader

Build a reader from exactly one required input: a local audio or video path. Do not ask for a transcript or translation. Keep all displayed text in the detected source language.

## Run

Resolve paths to absolute paths, then run:

```bash
./scripts/build.sh "/absolute/path/to/media.mp4" --open
```

The default output is a sibling directory named `<media-stem>-reader`. To avoid replacing an existing unrelated directory, pass an explicit output:

```bash
./scripts/build.sh "/absolute/path/to/media.mp3" --output "/absolute/path/to/output" --open
```

The command prints a JSON summary containing the resolved title, output path, sentence/chapter counts, repair count, and local URL. Report these concisely to the user.

The display title resolves as `--title` > yt-dlp sidecar (`<stem>.info.json` or sibling `metadata.json`) > cleaned filename. When the filename is machine-generated (for example `compressed-audio.mp3`) and no sidecar exists, pass `--title` with a human-readable title instead of accepting the filename.

## Behavior

- Accept browser-playable MP3, M4A, WAV, FLAC, Ogg/Opus, MP4/M4V, and WebM media; reject codecs the generated browser page cannot reliably play.
- Preserve the original media through a symbolic link; never modify or duplicate it.
- Detect the spoken language and transcribe in that same language.
- Repair speech-bearing holes produced by long-form Whisper.
- Detect explicit spoken chapter headings in English and Chinese; otherwise use one transcript chapter.
- Generate a static interactive frontend and VTT subtitles.
- Bind preview servers to `127.0.0.1` only and reuse an existing managed preview process for the same output.
- Reuse output ASR files only when the source hash, model, options, and pipeline version match.
- Refuse to overwrite non-reader directories.
- Never translate, request a translation, or align an arbitrary manuscript.

## Validation

After building, verify:

```bash
./scripts/build.sh "/absolute/path/to/media" --output "/absolute/path/to/output" --validate-only
```

For debugging, inspect:

- `<output>/public/data/reader.json`
- `<output>/work/gap-repair-report.json`
- `<output>/server.log`

If setup fails, check that `ffmpeg` and `ffprobe` are available. The launcher creates a versioned shared Python environment under `~/.cache/interactive-media-reader/venv` (MLX Whisper on Apple Silicon, faster-whisper on other platforms) unless `MEDIA_READER_PYTHON` points to an existing compatible Python. The generated page uses no translation service, cloud transcription API, or remote font request.
