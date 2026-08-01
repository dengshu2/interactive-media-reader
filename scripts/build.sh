#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/interactive-media-reader"
VENV="$CACHE_DIR/venv"
STAMP="$CACHE_DIR/environment-version"
LOCK_HASH="$(shasum -a 256 "$SKILL_DIR/uv.lock" | awk '{print $1}')"
EXPECTED_VERSION="0.3.1-$LOCK_HASH"

command -v ffmpeg >/dev/null || { echo "ffmpeg is required (brew install ffmpeg)" >&2; exit 1; }
command -v ffprobe >/dev/null || { echo "ffprobe is required (brew install ffmpeg)" >&2; exit 1; }

# Apple Silicon runs MLX Whisper; every other platform runs faster-whisper.
if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  ENGINE=mlx_whisper
else
  ENGINE=faster_whisper
fi

if [[ -n "${MEDIA_READER_PYTHON:-}" ]]; then
  PY="$MEDIA_READER_PYTHON"
  "$PY" -c "import $ENGINE, numpy" 2>/dev/null || {
    echo "MEDIA_READER_PYTHON does not provide $ENGINE and numpy: $PY" >&2
    exit 1
  }
elif [[ -x "$VENV/bin/python" ]] && [[ -f "$STAMP" ]] && [[ "$(<"$STAMP")" == "$EXPECTED_VERSION" ]] && "$VENV/bin/python" -c "import $ENGINE, numpy" 2>/dev/null; then
  PY="$VENV/bin/python"
else
  mkdir -p "$CACHE_DIR"
  rm -rf "$VENV"
  if command -v uv >/dev/null; then
    UV_PROJECT_ENVIRONMENT="$VENV" uv sync --project "$SKILL_DIR" --locked --no-dev
  else
    python3 -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
    # Read the pinned dependencies (with platform markers) from pyproject.toml
    # so they live in one place; one requirement per line preserves markers.
    PYPROJECT="$SKILL_DIR/pyproject.toml" "$VENV/bin/python" -c 'import os, tomllib; print("\n".join(tomllib.load(open(os.environ["PYPROJECT"], "rb"))["project"]["dependencies"]))' \
      | "$VENV/bin/python" -m pip install -r /dev/stdin
  fi
  PY="$VENV/bin/python"
  printf '%s\n' "$EXPECTED_VERSION" > "$STAMP"
fi

exec "$PY" "$SKILL_DIR/scripts/media_reader.py" "$@"
