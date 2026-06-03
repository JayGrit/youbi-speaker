from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydub import AudioSegment


def _candidate_paths(binary_name: str) -> list[Path]:
    suffix = ".exe" if os.name == "nt" else ""
    executable = f"{binary_name}{suffix}"
    roots = [
        Path.cwd(),
        Path(__file__).resolve().parents[2],
        Path(__file__).resolve().parents[3],
    ]
    paths: list[Path] = []
    for root in roots:
        paths.extend(
            [
                root / "ffmpeg" / "bin" / executable,
                root / "ffmpeg-master-latest-win64-gpl" / "bin" / executable,
                root / "tools" / "ffmpeg" / "bin" / executable,
            ]
        )
    if os.name == "nt":
        paths.extend(
            [
                Path("C:/ffmpeg/bin") / executable,
                Path("C:/Program Files/ffmpeg/bin") / executable,
                Path("C:/ProgramData/chocolatey/bin") / executable,
            ]
        )
    return paths


def _resolve_binary(binary_name: str, env_name: str) -> str | None:
    explicit = os.getenv(env_name)
    if explicit:
        path = Path(explicit).expanduser()
        if path.exists():
            return str(path)
        found = shutil.which(explicit)
        if found:
            return found
        raise FileNotFoundError(f"{env_name} points to a missing executable: {explicit}")

    found = shutil.which(binary_name)
    if found:
        return found

    for path in _candidate_paths(binary_name):
        if path.exists():
            return str(path)
    return None


def configure_pydub_ffmpeg() -> None:
    ffmpeg = _resolve_binary("ffmpeg", "FFMPEG_BINARY")
    ffprobe = _resolve_binary("ffprobe", "FFPROBE_BINARY")
    if not ffmpeg:
        raise FileNotFoundError(
            "pydub requires ffmpeg, but speaker could not find it. Install FFmpeg and add its bin "
            "directory to PATH, or set FFMPEG_BINARY to the executable path."
        )

    AudioSegment.converter = ffmpeg
    AudioSegment.ffmpeg = ffmpeg
    if ffprobe:
        AudioSegment.ffprobe = ffprobe
