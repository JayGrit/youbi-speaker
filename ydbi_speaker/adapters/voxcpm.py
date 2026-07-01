from __future__ import annotations

import contextlib
import contextvars
import inspect
import math
import operator
import os
import re
import sys
import unicodedata
import warnings
from pathlib import Path
from typing import Any, Mapping

import soundfile as sf
from pydub import AudioSegment
from tqdm import tqdm

from .ffmpeg import configure_pydub_ffmpeg
from .speechbrain_compat import suppress_optional_k2_lazy_import
from ..config import (
    VOXCPM_CFG_VALUE,
    VOXCPM_DENOISE,
    VOXCPM_DEVICE,
    VOXCPM_INFERENCE_TIMESTEPS,
    VOXCPM_LOAD_DENOISER,
    VOXCPM_MAX_LEN,
    VOXCPM_MIN_REFERENCE_MS,
    VOXCPM_MIN_LEN,
    VOXCPM_MODEL,
    VOXCPM_MODEL_DIR,
    VOXCPM_NORMALIZE,
    VOXCPM_OPTIMIZE,
    VOXCPM_RETRY_BADCASE,
    VOXCPM_RETRY_BADCASE_MAX_TIMES,
    VOXCPM_RETRY_BADCASE_RATIO_THRESHOLD,
)

configure_pydub_ffmpeg()

_MODEL = None
_WHITESPACE_RE = re.compile(r"\s+")
_PROGRESS_TOTAL_DIVISOR = 5
_PROGRESS_LABEL: contextvars.ContextVar[str] = contextvars.ContextVar("voxcpm_progress_label", default="")


class _CappedVisualProgress(tqdm):
    def update(self, n: int | float = 1) -> bool | None:
        if self.total is not None:
            n = min(n, max(0, self.total - self.n))
            if n <= 0:
                return None
        return super().update(n)

    def close(self) -> None:
        if self.total is not None:
            self.n = self.total
        super().close()


def _chinese_progress(iterable, *args, **kwargs):
    original_total = kwargs.get("total")
    if original_total is None:
        original_total = operator.length_hint(iterable, 0)
    if original_total:
        kwargs["total"] = math.ceil(original_total / _PROGRESS_TOTAL_DIVISOR)
    label = _PROGRESS_LABEL.get()
    desc = f"正在生成语音 {label}" if label else "正在生成语音"
    kwargs.update(
        desc=desc,
        bar_format="{desc}: {percentage:3.0f}%|{bar}|",
        dynamic_ncols=True,
        file=sys.stdout,
    )
    return _CappedVisualProgress(iterable, *args, **kwargs)


def _is_complete_model_dir(path: Path) -> bool:
    return (path / "model.safetensors").exists() and (
        (path / "audiovae.safetensors").exists() or (path / "audiovae.pth").exists()
    )


def _is_audio_segment(path: Path) -> bool:
    return path.suffix == ".wav" and not path.name.startswith(".")


def _model_path() -> Path:
    if VOXCPM_MODEL_DIR:
        path = Path(VOXCPM_MODEL_DIR).expanduser()
        if _is_complete_model_dir(path):
            return path
        if path.exists():
            print(f"VoxCPM 模型目录不完整，正在重新下载：{path}", flush=True)

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from modelscope import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "VoxCPM model is missing and modelscope is not installed. "
                f"Install project dependencies, then rerun start.sh. Expected model path: {path}"
            ) from exc

        print(f"未找到 VoxCPM 模型，正在下载到：{path}", flush=True)
        downloaded = Path(
            snapshot_download(
                VOXCPM_MODEL,
                cache_dir=str(path.parent),
                local_dir=str(path),
            )
        ).expanduser()
        if _is_complete_model_dir(downloaded):
            return downloaded
        if _is_complete_model_dir(path):
            return path
        raise FileNotFoundError(f"VoxCPM model download did not create a complete model directory: {path}")

    raise RuntimeError(f"VoxCPM model directory is not configured; expected bundled model for {VOXCPM_MODEL}")


def _voxcpm_will_use_mps() -> bool:
    device = VOXCPM_DEVICE.strip().lower()
    try:
        import torch
    except ImportError:
        return False

    has_mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    if not has_mps:
        return False
    if device == "mps":
        return True
    if device not in {"", "auto"}:
        return False
    return not torch.cuda.is_available()


def _patch_voxcpm_mps_audio_vae() -> None:
    if not _voxcpm_will_use_mps():
        return

    import torch
    import voxcpm.modules.audiovae.audio_vae_v2 as audio_vae_v2

    for name in (
        "_jit_override_can_fuse_on_gpu",
        "_jit_set_texpr_fuser_enabled",
        "_jit_set_nvfuser_enabled",
    ):
        setter = getattr(torch._C, name, None)
        if setter is not None:
            with contextlib.suppress(Exception):
                setter(False)

    def snake_eager(x, alpha):
        shape = x.shape
        x = x.reshape(shape[0], shape[1], -1)
        x = x + (alpha + 1e-9).reciprocal() * torch.sin(alpha * x).pow(2)
        return x.reshape(shape)

    audio_vae_v2.snake = snake_eager


def _voxcpm_from_pretrained_kwargs(from_pretrained: object) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "load_denoiser": VOXCPM_LOAD_DENOISER,
        "optimize": VOXCPM_OPTIMIZE,
        "device": VOXCPM_DEVICE,
    }
    try:
        signature = inspect.signature(from_pretrained)
    except (TypeError, ValueError):
        return kwargs

    parameters = signature.parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return kwargs
    return {name: value for name, value in kwargs.items() if name in parameters}


def _load_model():
    global _MODEL
    if _MODEL is None:
        model_path = _model_path()
        print(f"正在加载 VoxCPM 语音模型：{model_path}", flush=True)
        with (
            warnings.catch_warnings(),
        ):
            warnings.simplefilter("ignore", FutureWarning)
            from voxcpm import VoxCPM

            _patch_voxcpm_mps_audio_vae()
            _MODEL = VoxCPM.from_pretrained(
                str(model_path),
                **_voxcpm_from_pretrained_kwargs(VoxCPM.from_pretrained),
            )
            import voxcpm.model.voxcpm2 as voxcpm2

            voxcpm2.tqdm = _chinese_progress
        print("VoxCPM 语音模型加载完成", flush=True)
    return _MODEL


def _fallback_reference(vocals_dir: Path, min_ms: int) -> Path:
    files = sorted(path for path in vocals_dir.glob("*.wav") if _is_audio_segment(path))
    if not files:
        raise FileNotFoundError("No vocal segments were generated for VoxCPM references.")
    for path in files:
        if len(AudioSegment.from_file(path, format="wav")) >= min_ms:
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


def generation_options() -> dict[str, Any]:
    options: dict[str, Any] = {
        "cfg_value": VOXCPM_CFG_VALUE,
        "inference_timesteps": VOXCPM_INFERENCE_TIMESTEPS,
        "normalize": VOXCPM_NORMALIZE,
        "denoise": VOXCPM_DENOISE,
        "retry_badcase": VOXCPM_RETRY_BADCASE,
        "retry_badcase_max_times": VOXCPM_RETRY_BADCASE_MAX_TIMES,
        "retry_badcase_ratio_threshold": VOXCPM_RETRY_BADCASE_RATIO_THRESHOLD,
    }
    if VOXCPM_MIN_LEN is not None:
        options["min_len"] = VOXCPM_MIN_LEN
    if VOXCPM_MAX_LEN is not None:
        options["max_len"] = VOXCPM_MAX_LEN
    return options


def generate_tts_segment(
    text: str,
    item_index: int,
    reference: Path,
    fallback: Path,
    session: Path,
    progress_label: str = "",
    prompt_text: str | None = None,
    combined_cloning: bool = False,
    generation_options_override: Mapping[str, Any] | None = None,
) -> Path:
    output_dir = session / "segments" / "tts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{item_index + 1:04d}.wav"
    if output_file.exists():
        return output_file

    min_reference_ms = VOXCPM_MIN_REFERENCE_MS
    reference_file = reference
    if not reference_file.exists() or len(AudioSegment.from_file(reference_file, format="wav")) < min_reference_ms:
        reference_file = fallback

    target_text = sanitize_target_text(text)
    if not target_text:
        raise ValueError("target text must be a non-empty string after sanitization")

    model = _load_model()
    progress_token = _PROGRESS_LABEL.set(progress_label)
    try:
        suppress_optional_k2_lazy_import()
        options = dict(generation_options_override or generation_options())
        if combined_cloning:
            wav = model.generate(
                text=target_text,
                prompt_wav_path=str(reference_file),
                prompt_text=prompt_text or "",
                reference_wav_path=str(reference_file),
                **options,
            )
        else:
            wav = model.generate(
                text=target_text,
                reference_wav_path=str(reference_file),
                cfg_value=options["cfg_value"],
                inference_timesteps=options["inference_timesteps"],
            )
    finally:
        _PROGRESS_LABEL.reset(progress_token)
    sf.write(output_file, wav, model.tts_model.sample_rate)
    return output_file
