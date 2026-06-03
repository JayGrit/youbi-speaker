from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydub import AudioSegment

from .ffmpeg import configure_pydub_ffmpeg

configure_pydub_ffmpeg()


def split_audio_segment(
    vocals_file: Path,
    item_index: int,
    start_time: int,
    end_time: int,
    session: Path,
) -> Path:
    output_dir = session / "segments" / "vocals"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{item_index + 1:04d}.wav"
    if output_file.exists():
        return output_file

    audio = AudioSegment.from_file(vocals_file)
    start = max(0, int(start_time) - 80)
    end = min(len(audio), int(end_time) + 160)
    audio[start:end].export(output_file, format="wav")
    return output_file


def split_audio_segments(
    vocals_file: Path,
    segments: list[Mapping[str, Any]],
    session: Path,
) -> dict[int, Path]:
    output_dir = session / "segments" / "vocals"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    missing: list[Mapping[str, Any]] = []

    for row in segments:
        item_index = int(row["item_index"])
        output_file = output_dir / f"{item_index + 1:04d}.wav"
        paths[item_index] = output_file
        if not output_file.exists():
            missing.append(row)

    if not missing:
        return paths

    audio = AudioSegment.from_file(vocals_file)
    for row in missing:
        item_index = int(row["item_index"])
        output_file = paths[item_index]
        start = max(0, int(row["start_time"]) - 80)
        end = min(len(audio), int(row["end_time"]) + 160)
        audio[start:end].export(output_file, format="wav")

    return paths
