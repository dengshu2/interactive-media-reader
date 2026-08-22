# Contributing

Focused bug reports and pull requests are welcome.

Before opening a pull request:

1. Keep the product boundary intact: one English media source, audio-only reader output, URL downloads restricted to audio-only formats, and no multilingual handling, translation, or manuscript alignment.
2. Add or update regression tests for behavior changes.
3. Run `uv sync --locked --no-dev`, `uv run python -m unittest discover -s tests -v`, `python -m py_compile scripts/*.py`, `node --check assets/app.js`, and `shellcheck scripts/*.sh`.
4. Do not reintroduce video assets, source-media symlinks, or frontend video rendering. Do not commit media, model files, transcripts, generated readers, virtual environments, or cache contents.

Full Parakeet inference is optional for small code changes but should be reported when the ASR path, model handling, timing, or cache behavior changes.
