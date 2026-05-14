#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export YDBI_ROOT="${YDBI_ROOT:-$SCRIPT_DIR}"

export WORKFOLDER="${WORKFOLDER:-$SCRIPT_DIR/workfolder}"
export MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-$SCRIPT_DIR/data/modelscope}"
export VOXCPM_MODEL_DIR="${VOXCPM_MODEL_DIR:-$MODEL_CACHE_DIR/OpenBMB__VoxCPM2}"
export YDBI_SPEAKER_WORK_DIR="${YDBI_SPEAKER_WORK_DIR:-/tmp/ydbi/speaker}"

mkdir -p "$WORKFOLDER" "$MODEL_CACHE_DIR"

if [[ -x "$SCRIPT_DIR/.venv/bin/ydbi-speaker" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/ydbi-speaker"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/python" -m ydbi_speaker.main
fi

exec python -m ydbi_speaker.main
