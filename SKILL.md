---
name: interactive-media-reader
description: Convert one English-language audio/video path or media URL into an audio-only interactive transcript reader with sentence-click playback, synchronized highlighting, chapters, keyboard controls, and a local preview URL. Use for clickable readers, audio readers, or 跟读/点句播放/字幕阅读页面. Requires only the source; never request a translation or transcript manuscript, and never download, retain, link, or render video for URL workflows.
compatibility: Python 3.11/3.12, ffmpeg/ffprobe, and yt-dlp for URLs; Parakeet TDT 0.6B v3 through sherpa-onnx on all platforms, CPU only; the 640 MB model downloads on first use.
---

# Interactive Media Reader

Build an audio-only reader from exactly one English media source: a local audio/video path or a URL. Do not ask for a transcript or translation.

The product contract is English only and audio-only. If the media is known to be non-English, say so and stop. Do not run language identification, multilingual fallback, translation, or retain video for playback.

## Acquire URL Audio

When the user supplies a URL, download only its audio stream. Never download a video stream and never create an MP4/WebM video intermediate:

```bash
yt-dlp --no-playlist -f bestaudio --write-info-json \
  -o "/absolute/download/path/%(title)s [%(id)s].%(ext)s" \
  "https://example.com/media"
```

If no audio-only format exists, stop and explain that the source cannot be processed without downloading video. Resolve the downloaded audio path to an absolute path before building. Preserve the audio download unless the user explicitly asks to remove it.

## Build

Resolve paths to absolute paths, then run:

```bash
./scripts/build.sh "/absolute/path/to/media" --open
```

A local video is accepted as input, but only its first audio stream is used. The builder creates a compact mono AAC/M4A playback asset inside the reader, transcribes that exact asset so timings match, and never copies, symlinks, or renders the video.

The default output is a sibling directory named `<media-stem>-reader`. To avoid replacing an existing unrelated directory, pass an explicit output:

```bash
./scripts/build.sh "/absolute/path/to/media" --output "/absolute/path/to/output" --open
```

The command prints a JSON summary containing the resolved title, output path, sentence/chapter counts, low-confidence sentence count, source media type, and local URL. Report these concisely to the user.

The display title resolves as `--title` > yt-dlp sidecar (`<stem>.info.json` or sibling `metadata.json`) > cleaned filename. When the filename is machine-generated and no matching sidecar exists, pass `--title` with a human-readable title.

## Behavior

- Accept any local audio or video that ffmpeg can decode and that has an audio stream.
- Generate only `public/media/source.m4a`: mono AAC at 64 kbit/s with no video, subtitle, data, or attached-picture stream.
- Transcribe the normalized playback audio so sentence timings match browser playback.
- Never modify or delete the user's source file. Never place or link source video inside the reader.
- Remove stale v0.5 media links/files from the reader-owned `public/media` directory when rebuilding.
- Accept and transcribe English-language media only; do not attempt to identify or process other languages.
- Re-decode collapsed Parakeet windows so a lost punctuation head cannot produce minute-long sentences.
- Detect explicit spoken chapter headings in English; otherwise use one transcript chapter.
- Generate a static audio-only frontend and VTT subtitles.
- Bind preview servers to `127.0.0.1` only and reuse an existing managed preview process for the same output.
- Reuse normalized audio and ASR files only when their source hash, options, model, and pipeline versions match.
- Refuse to overwrite non-reader directories.
- Never translate, request a translation, or align an arbitrary manuscript.

## Validation

After building, verify:

```bash
./scripts/build.sh "/absolute/path/to/media" --output "/absolute/path/to/output" --validate-only
```

Validation rejects missing/symlinked playback media, non-AAC media, any video stream, and non-audio reader metadata.

For debugging, inspect:

- `<output>/public/data/reader.json`
- `<output>/work/playback-audio.json`
- `<output>/work/asr.json`
- `<output>/server.log`

If setup fails, check that `ffmpeg` and `ffprobe` are available. The launcher creates a versioned shared Python environment under `~/.cache/interactive-media-reader/venv` unless `MEDIA_READER_PYTHON` points to an existing compatible Python, and caches the model under `~/.cache/interactive-media-reader/models/`. The generated page uses no translation service, cloud transcription API, or remote font request.
