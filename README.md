# Interactive Media Reader

Turn one local audio or video file into a same-language, clickable transcript reader. Click any sentence to seek and play; the current sentence follows playback automatically.

把一个本地音频或视频文件转换成同语言的交互阅读页面：点击句子播放、自动高亮、章节导航、倍速、循环与快捷键。**仅支持英语及其他欧洲语言，不支持中文。**

> **Upgrading from 0.3.x**
>
> 0.4.0 replaces Whisper with Parakeet TDT and **drops Chinese and every other non-European language**. If you use this on CJK media, stay on [v0.3.2](https://github.com/dengshu2/interactive-media-reader/releases/tag/v0.3.2).
>
> Existing outputs keep working, but the next build re-transcribes from scratch: the ASR cache key changed, and `work/asr-repaired.json` and `work/gap-repair-report.json` are no longer produced.
>
> 0.4.0 起改用 Parakeet TDT，**移除中文及所有非欧洲语言支持**。需要处理中文素材请停留在 v0.3.2。

## Scope

The required input is exactly one local media path.

- English and 24 other European languages; **no Chinese or other non-European support**
- No transcript manuscript required
- No translation requested or generated
- No cloud transcription API
- Original media is never modified or copied; the output uses a symbolic link
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

Transcription runs NVIDIA [Parakeet TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) through [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) on every platform — the int8 build is CPU-only and needs no GPU. Word timings come from the model's own duration head, so there is no separate forced-alignment pass.

The first run installs a pinned environment under `~/.cache/interactive-media-reader/venv` and downloads the 640 MB model from the sherpa-onnx GitHub release into `~/.cache/interactive-media-reader/models/`.

| Variable | Effect |
| --- | --- |
| `INTERACTIVE_MEDIA_READER_PARAKEET_DIR` | Use an existing model directory instead of downloading one |
| `INTERACTIVE_MEDIA_READER_CACHE` | Move the model cache off `~/.cache/interactive-media-reader` |
| `INTERACTIVE_MEDIA_READER_THREADS` | Decode threads, default 4 |
| `MEDIA_READER_PYTHON` | Use an existing Python instead of the managed environment |

The thread default is deliberately below the core count. Measured end to end on an 86-minute file on a 10-core Apple Silicon machine, same code both times, 4 threads ran 4:10 using 882s of CPU where 6 ran 4:46 using 1377s — slower and 56% hungrier, even though an isolated single-window benchmark ranks 6 ahead. Re-measure before raising it.

The model covers Bulgarian, Croatian, Czech, Danish, Dutch, English, Estonian, Finnish, French, German, Greek, Hungarian, Italian, Latvian, Lithuanian, Maltese, Polish, Portuguese, Romanian, Russian, Slovak, Slovenian, Spanish, Swedish and Ukrainian. Anything else — Chinese, Japanese, Korean, Arabic — is out of scope.

## Install as an Agent Skill

```bash
npx skills add dengshu2/interactive-media-reader -g --agent pi -y
```

Then ask Pi:

```text
把 /absolute/path/to/media.mp4 做成交互式阅读器
```

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

## Supported playback formats

The pipeline intentionally rejects media that FFmpeg can decode but the generated browser page cannot reliably play.

- Audio: MP3, M4A/AAC, WAV/PCM, FLAC, Ogg/Vorbis, Opus
- Video: MP4/M4V or WebM with a browser-compatible video/audio codec

For other formats, create a browser proxy first:

```bash
ffmpeg -i input.mkv -c:v libx264 -c:a aac output.mp4
```

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
│   └── media/source.* -> original media
└── work/
    └── asr.json
```

A marker file prevents accidental writes into unrelated non-empty directories. ASR caches are reused only when the source SHA-256, model, decoding options, and pipeline version all match.

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
```

The repository contains no copyrighted media, generated transcript, model, virtual environment, or local output. Tests use synthetic metadata and small text fixtures; full Parakeet inference is an optional local smoke test.

## Current limitations

- Chinese and every other non-European language is out of scope; the model cannot transcribe them
- Spoken chapter heading detection covers English only ("Chapter 3", "Part two"); other languages get one transcript chapter
- Sentence splitting depends on the model's punctuation, so a decode window that loses it is re-decoded rather than salvaged
- Very long readers render all sentence nodes at once
- Arbitrary manuscripts and translations are deliberate non-goals

## License

MIT. See [LICENSE](LICENSE).
