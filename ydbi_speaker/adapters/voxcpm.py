from __future__ import annotations

import contextlib
import os
import re
import unicodedata
from pathlib import Path

import soundfile as sf
from pydub import AudioSegment

from ..config import (
    VOXCPM_CFG_VALUE,
    VOXCPM_INFERENCE_TIMESTEPS,
    VOXCPM_LOAD_DENOISER,
    VOXCPM_MIN_REFERENCE_MS,
    VOXCPM_MODEL,
    VOXCPM_MODEL_DIR,
    VOXCPM_OPTIMIZE,
)

_MODEL = None
_WHITESPACE_RE = re.compile(r"\s+")


def _is_audio_segment(path: Path) -> bool:
    return path.suffix == ".wav" and not path.name.startswith(".")


def _model_path() -> Path:
    if VOXCPM_MODEL_DIR:
        path = Path(VOXCPM_MODEL_DIR).expanduser()
        if path.exists():
            return path

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from modelscope import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "VoxCPM model is missing and modelscope is not installed. "
                f"Install project dependencies, then rerun start.sh. Expected model path: {path}"
            ) from exc

        print(f"VoxCPM model not found; downloading {VOXCPM_MODEL} to {path}", flush=True)
        downloaded = Path(
            snapshot_download(
                VOXCPM_MODEL,
                cache_dir=str(path.parent),
                local_dir=str(path),
            )
        ).expanduser()
        if downloaded.exists():
            return downloaded
        if path.exists():
            return path
        raise FileNotFoundError(f"VoxCPM model download did not create the expected directory: {path}")

    raise RuntimeError(f"VoxCPM model directory is not configured; expected bundled model for {VOXCPM_MODEL}")


def _load_model():
    global _MODEL
    if _MODEL is None:
        from voxcpm import VoxCPM

        _MODEL = VoxCPM.from_pretrained(
            str(_model_path()),
            load_denoiser=VOXCPM_LOAD_DENOISER,
            optimize=VOXCPM_OPTIMIZE,
        )
    return _MODEL


def _fallback_reference(vocals_dir: Path, min_ms: int) -> Path:
    files = sorted(path for path in vocals_dir.glob("*.wav") if _is_audio_segment(path))
    if not files:
        raise FileNotFoundError("No vocal segments were generated for VoxCPM references.")
    for path in files:
        if len(AudioSegment.from_file(path)) >= min_ms:
            return path
    return files[0]


def fallback_reference(vocals_dir: Path) -> Path:
    return _fallback_reference(vocals_dir, VOXCPM_MIN_REFERENCE_MS)


def sanitize_target_text(text: object) -> str:
    cleaned: list[str] = []
    for char in str(text or ""):
        if char.isspace():
            cleaned.append(" ")
            continue
        category = unicodedata.category(char)
        if category.startswith("Z"):
            cleaned.append(" ")
            continue
        if category.startswith("C"):
            continue
        cleaned.append(char)
    return _WHITESPACE_RE.sub(" ", "".join(cleaned)).strip()


def generate_tts_segment(
    text: str,
    item_index: int,
    reference: Path,
    fallback: Path,
    session: Path,
) -> Path:
    output_dir = session / "segments" / "tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{item_index + 1:04d}.wav"
    if output_file.exists():
        return output_file

    min_reference_ms = VOXCPM_MIN_REFERENCE_MS
    reference_file = reference
    if not reference_file.exists() or len(AudioSegment.from_file(reference_file)) < min_reference_ms:
        reference_file = fallback

    target_text = sanitize_target_text(text)
    if not target_text:
        raise ValueError("target text must be a non-empty string after sanitization")

    model = _load_model()
    with open(os.devnull, "w") as devnull, contextlib.redirect_stderr(devnull):
        wav = model.generate(
            text=target_text,
            reference_wav_path=str(reference_file),
            cfg_value=VOXCPM_CFG_VALUE,
            inference_timesteps=VOXCPM_INFERENCE_TIMESTEPS,
        )
    sf.write(output_file, wav, model.tts_model.sample_rate)
    return output_file
