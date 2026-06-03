#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YDBI_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -z "${WORKFOLDER:-}" && -d /work && -w /work ]]; then
  WORKFOLDER="/work"
else
  WORKFOLDER="${WORKFOLDER:-$YDBI_ROOT/workfolder}"
fi

export WORKFOLDER
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-$SCRIPT_DIR/model}"
export VOXCPM_MODEL_DIR="${VOXCPM_MODEL_DIR:-$MODELSCOPE_CACHE/VoxCPM2}"

mkdir -p "$WORKFOLDER/speaker" "$MODELSCOPE_CACHE"

if [[ -x "$SCRIPT_DIR/.venv/bin/ydbi-speaker" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/ydbi-speaker"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/python" -m ydbi_speaker.main
fi

exec python -m ydbi_speaker.main
