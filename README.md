# Interactive Media Reader

Turn one local audio or video file into a same-language, clickable transcript reader. Click any sentence to seek and play; the current sentence follows playback automatically.

把一个本地音频或视频文件转换成同语言的交互阅读页面：点击句子播放、自动高亮、章节导航、倍速、循环与快捷键。

## Scope

The required input is exactly one local media path.

- No transcript manuscript required
- No translation requested or generated
- No cloud transcription API
- Original media is never modified or copied; the output uses a symbolic link
- Preview servers bind to `127.0.0.1` only

## Requirements

- macOS on Apple Silicon
- Python 3.11 or 3.12
- [FFmpeg](https://ffmpeg.org/)
- `uv` recommended (plain `venv`/`pip` is used as a fallback)

```bash
brew install ffmpeg uv
```

The first run installs a pinned MLX Whisper environment under `~/.cache/interactive-media-reader/venv` and downloads `mlx-community/whisper-large-v3-turbo` from Hugging Face. Expect several gigabytes of local cache in total.

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
    ├── asr.json
    ├── asr-repaired.json
    └── gap-repair-report.json
```

A marker file prevents accidental writes into unrelated non-empty directories. ASR caches are reused only when the source SHA-256, model, decoding options, and pipeline version all match.

## Quality safeguards

Long-form Whisper can skip speech after an incorrect timestamp jump. The pipeline audits gaps longer than 1.5 seconds, re-transcribes candidates in short overlapping windows, and only repairs gaps where confident speech is recovered. Remaining pauses are left untouched, and the frontend clears highlighting when no sentence covers the current time.

## Keyboard controls

- `Space` / `K`: play or pause
- `←` / `→`: seek 5 seconds
- `Shift + ←` / `Shift + →`: previous or next sentence
- `R`: repeat current sentence
- `A`: toggle auto-follow
- `-` / `=`: playback speed
- `0`: reset to 1×
- `?`: shortcut help

## Development

```bash
python3 -m unittest discover -s tests -v
node --check assets/app.js
python3 -m py_compile scripts/*.py
```

The repository contains no copyrighted media, generated transcript, model, virtual environment, or local output. Tests use synthetic metadata and small text fixtures; full Whisper inference is an optional local smoke test.

## Current limitations

- MLX backend means v0.1 supports Apple Silicon only
- Explicit spoken chapter headings are detected; otherwise the output has one transcript chapter
- Very long readers render all sentence nodes at once
- Arbitrary manuscripts and translations are deliberate non-goals

## License

MIT. See [LICENSE](LICENSE).
