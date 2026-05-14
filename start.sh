#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${YDBI_ROOT:-}" ]]; then
  if [[ "$(basename "$(dirname "$SCRIPT_DIR")")" == "services" ]]; then
    export YDBI_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
  else
    export YDBI_ROOT="$SCRIPT_DIR"
  fi
fi

export WORKFOLDER="${WORKFOLDER:-$YDBI_ROOT/workfolder}"
export MODEL_CACHE_DIR="${MODEL_CACHE_DIR:-$YDBI_ROOT/data/modelscope}"
export VOXCPM_MODEL_DIR="${VOXCPM_MODEL_DIR:-$MODEL_CACHE_DIR/OpenBMB__VoxCPM2}"
export YDBI_SPEAKER_WORK_DIR="${YDBI_SPEAKER_WORK_DIR:-/tmp/ydbi/speaker}"

if [[ ! -d "$VOXCPM_MODEL_DIR" ]]; then
  echo "VoxCPM model directory does not exist: $VOXCPM_MODEL_DIR" >&2
  echo "Set VOXCPM_MODEL_DIR to the local OpenBMB/VoxCPM2 directory, or place the model at:" >&2
  echo "  $VOXCPM_MODEL_DIR" >&2
  echo "Example:" >&2
  echo "  MODEL_CACHE_DIR=/path/to/modelscope VOXCPM_MODEL_DIR=/path/to/OpenBMB__VoxCPM2 ./start.sh" >&2
  exit 1
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/ydbi-speaker" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/ydbi-speaker"
fi

if [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
  exec "$SCRIPT_DIR/.venv/bin/python" -m ydbi_speaker.main
fi

exec python -m ydbi_speaker.main
