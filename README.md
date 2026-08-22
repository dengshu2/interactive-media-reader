# Interactive Media Reader

Turn one English-language audio or video source into an **audio-only** clickable transcript reader. Click any sentence to seek and play; the current sentence follows playback automatically.

把一个英文音频或视频源转换成**纯音频**交互阅读页面：点击句子播放、自动高亮、章节导航、倍速、循环与快捷键。仅支持英语，输出不包含、链接或渲染视频。

> **0.6.0 audio-only release**
>
> Every input is normalized to a compact mono AAC/M4A playback asset inside the reader. Local videos remain valid inputs, but their video streams are never copied or linked into the output. The normalized audio is also the ASR input, keeping transcript timing aligned with playback.
>
> Rebuilding a 0.5.x reader removes stale media links under `public/media` and re-transcribes from the normalized audio because the ASR cache version changed.

## Scope

The required input is exactly one English media source: a local path for direct use, or a URL handled by the agent workflow.

- English only; all other languages are out of scope
- Audio-only reader output, even when the local source is video
- URL workflow downloads `bestaudio` only and never downloads a video stream
- No transcript manuscript required
- No translation requested or generated
- No cloud transcription API
- User source media is never modified or deleted
- Preview servers bind to `127.0.0.1` only

## Requirements

- Python 3.11 or 3.12
- [FFmpeg](https://ffmpeg.org/)
- `uv` recommended (plain `venv`/`pip` is used as a fallback)

```bash
brew install ffmpeg uv        # macOS
sudo apt install ffmpeg       # Debian/Ubuntu
```

### ASR engine

Transcription runs NVIDIA [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) through [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) on every platform — the int8 build is CPU-only and needs no GPU. Word timings come from the model's own duration head, so there is no separate forced-alignment pass. Although the upstream model is multilingual, this project intentionally accepts English input only and contains no language-identification path.

The first run installs a pinned environment under `~/.cache/interactive-media-reader/venv` and downloads the 640 MB model from the sherpa-onnx GitHub release into `~/.cache/interactive-media-reader/models/`. The 487 MB release archive is verified against its upstream SHA-256 before extraction.

| Variable | Effect |
| --- | --- |
| `INTERACTIVE_MEDIA_READER_PARAKEET_DIR` | Use an existing model directory instead of downloading one |
| `INTERACTIVE_MEDIA_READER_CACHE` | Move the model cache off `~/.cache/interactive-media-reader` |
| `INTERACTIVE_MEDIA_READER_THREADS` | Decode threads, default 4 |
| `MEDIA_READER_PYTHON` | Use an existing Python instead of the managed environment |

The thread default is deliberately below the core count. Measured end to end on an 86-minute file on a 10-core Apple Silicon machine, same code both times, 4 threads ran 4:10 using 882s of CPU where 6 ran 4:46 using 1377s — slower and 56% hungrier, even though an isolated single-window benchmark ranks 6 ahead. Re-measure before raising it.

The upstream model can recognize multiple languages, but this project's supported and tested contract is English only. Non-English media is out of scope.

## Install as an Agent Skill

```bash
npx skills add dengshu2/interactive-media-reader -g --agent pi -y
```

Then ask Pi with a local path or URL:

```text
把 /absolute/path/to/media.mp4 做成纯音频交互式阅读器
把 https://example.com/talk 做成纯音频交互式阅读器，不要下载视频
```

For URLs, the skill downloads only an audio-only format with `yt-dlp -f bestaudio`; it stops if the source offers no audio-only stream.

Or invoke the skill directly:

```text
/skill:interactive-media-reader "/absolute/path/to/media.mp3"
```

## Direct use

```bash
./scripts/build.sh "/absolute/path/to/media.mp3" --open
```

The default output is a sibling directory named `<media-stem>-reader`. Repeated `--open` calls reuse the managed preview server. Stop it with `./scripts/stop.sh /path/to/output`. An explicit output is also supported:

```bash
./scripts/build.sh input.mp4 --output /absolute/path/to/output --open
```

The display title is resolved in this order: `--title`, a yt-dlp sidecar (`<stem>.info.json` or a sibling `metadata.json` with a `title` field), then the cleaned filename. Downloaded media often has a mangled filename, so the sidecar usually wins:

```bash
./scripts/build.sh input.mp3 --title "10 Positive Habits That Will Rewire Your Mindset" --open
```

## Supported inputs and playback

Any local audio or video that FFmpeg can decode is accepted when it contains an audio stream. The first audio stream is normalized to `public/media/source.m4a` as mono AAC at 64 kbit/s. FFmpeg receives `-vn -sn -dn`, so video, subtitle, data, and attached-picture streams cannot enter the reader.

The normalized asset is self-contained rather than a source symlink. The original input stays outside the reader and is never modified or deleted.

## Output

```text
<output>/
├── .interactive-media-reader.json
├── public/
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── data/reader.json
│   ├── data/subtitles.vtt
│   └── media/source.m4a
└── work/
    ├── playback-audio.json
    └── asr.json
```

A marker file prevents accidental writes into unrelated non-empty directories. Playback audio is reused only when its source hash and normalization options match; ASR is reused only when the normalized audio hash, model, decoding options, and pipeline version match. Rebuilds remove stale media files and symlinks from the reader-owned `public/media` directory.

## Quality safeguards

Roughly one Parakeet decode window in ten collapses, losing punctuation, capitalization and content at once. Because sentence splitting depends on punctuation, a collapsed window would otherwise produce minute-long "sentences". Windows that come back with no sentence-ending punctuation at all are detected and re-decoded in halves, which recovers them.

Earlier versions ran a second pass that hunted for speech-bearing holes in the transcript. That existed because long-form Whisper can seek past audio after predicting an early end timestamp — on an 86-minute audiobook it swallowed 98.7 seconds across five places. Parakeet decodes frame-synchronously and cannot skip ahead: the same file yielded one candidate gap and zero repairs, so the pass was removed rather than kept as decoration.

Pauses are left untouched, and the frontend clears highlighting when no sentence covers the current time.

## Keyboard controls

- `Space` / `K`: play or pause
- `←` / `→`: seek 5 seconds
- `Shift + ←` / `Shift + →`: previous or next sentence
- `R`: repeat current sentence
- `A`: toggle auto-follow
- `-` / `=`: playback speed
- `0`: reset to 1×
- `Shift + /` (`?`): shortcut help

## Development

```bash
uv sync --locked --no-dev
uv run python -m unittest discover -s tests -v
node --check assets/app.js
python3 -m py_compile scripts/*.py
shellcheck scripts/*.sh
```

The repository contains no copyrighted media, generated transcript, model, virtual environment, or local output. Tests use synthetic metadata and small text fixtures; full Parakeet inference is an optional local smoke test. CI covers Python 3.11 and 3.12 on Ubuntu and macOS.

## Current limitations

- Only English-language media is supported; other languages are not detected, translated, or handled
- Readers are deliberately audio-only; source video is never available in the generated page
- Spoken chapter heading detection covers English phrases such as "Chapter 3" and "Part two"
- Sentence splitting depends on the model's punctuation, so a decode window that loses it is re-decoded rather than salvaged
- Very long readers render all sentence nodes at once
- Arbitrary manuscripts and translations are deliberate non-goals

## License

The project code is MIT. See [LICENSE](LICENSE). The downloaded model and runtime dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Security reports are handled as described in [SECURITY.md](SECURITY.md).
