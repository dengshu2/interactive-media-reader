---
name: interactive-media-reader
description: Convert one local English-language audio or video file into an interactive transcript reader with sentence-click playback, synchronized highlighting, chapters, keyboard controls, and a local preview URL. Use when the user asks to turn English media into a clickable reader, audio reader, video transcript page, or 跟读/点句播放/字幕阅读页面. Requires only the media path; never request or generate a translation or transcript manuscript. Does not support any non-English language.
compatibility: Python 3.11/3.12 and ffmpeg; Parakeet TDT 0.6B v3 through sherpa-onnx on all platforms, CPU only; the 640 MB model downloads on first use.
---

# Interactive Media Reader

Build a reader from exactly one required input: a local English-language audio or video path. Do not ask for a transcript or translation.

The product contract is English only. If the media is known to be non-English, say so and stop. Do not run language identification, multilingual fallback, or translation.

## Run

Resolve paths to absolute paths, then run:

```bash
./scripts/build.sh "/absolute/path/to/media.mp4" --open
```

The default output is a sibling directory named `<media-stem>-reader`. To avoid replacing an existing unrelated directory, pass an explicit output:

```bash
./scripts/build.sh "/absolute/path/to/media.mp3" --output "/absolute/path/to/output" --open
```

The command prints a JSON summary containing the resolved title, output path, sentence/chapter counts, low-confidence sentence count, and local URL. Report these concisely to the user.

The display title resolves as `--title` > yt-dlp sidecar (`<stem>.info.json` or sibling `metadata.json`) > cleaned filename. When the filename is machine-generated (for example `compressed-audio.mp3`) and no sidecar exists, pass `--title` with a human-readable title instead of accepting the filename.

## Behavior

- Accept browser-playable MP3, M4A, WAV, FLAC, Ogg/Opus, MP4/M4V, and WebM media; reject codecs the generated browser page cannot reliably play.
- Preserve the original media through a symbolic link; never modify or duplicate it.
- Accept and transcribe English-language media only; do not attempt to identify or process other languages.
- Re-decode collapsed Parakeet windows so a lost punctuation head cannot produce minute-long sentences.
- Detect explicit spoken chapter headings in English; otherwise use one transcript chapter.
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
- `<output>/work/asr.json`
- `<output>/server.log`

If setup fails, check that `ffmpeg` and `ffprobe` are available. The launcher creates a versioned shared Python environment under `~/.cache/interactive-media-reader/venv` (sherpa-onnx on every platform) unless `MEDIA_READER_PYTHON` points to an existing compatible Python, and caches the model under `~/.cache/interactive-media-reader/models/`. The generated page uses no translation service, cloud transcription API, or remote font request.
