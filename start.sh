#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

mkdir -p /work/speaker /models/modelscope

if [[ -x "$SCRIPT_DIR/.venv/bin/ydbi-speaker" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/ydbi-speaker"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/python" -m ydbi_speaker.main
fi

exec python -m ydbi_speaker.main
