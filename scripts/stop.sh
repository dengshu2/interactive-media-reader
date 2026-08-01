#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /absolute/path/to/reader-output" >&2
  exit 2
fi

OUTPUT="$(cd "$1" && pwd)"
METADATA="$OUTPUT/.server.json"
if [[ ! -f "$METADATA" ]]; then
  echo "No managed preview server recorded for $OUTPUT"
  exit 0
fi

PID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$METADATA")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped preview server $PID"
else
  echo "Preview server $PID was not running"
fi
rm -f "$METADATA"
