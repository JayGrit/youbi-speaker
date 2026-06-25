from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter

log = logging.getLogger(__name__)

FRAME_SECONDS = 0.5
HOP_SECONDS = 0.05
TARGET_DB = -31.0
SILENCE_THRESHOLD_DB = -55.0
MAX_BOOST_DB = 3.0
MAX_CUT_DB = 22.0
GAIN_SMOOTH_FRAMES = 81
CEILING_DB = -1.0


def _db_to_amp(db: np.ndarray | float) -> np.ndarray | float:
    return 10 ** (db / 20)


def _amp_to_db(amp: np.ndarray, floor: float = 1e-8) -> np.ndarray:
    return 20 * np.log10(np.maximum(amp, floor))


def _to_mono_for_analysis(audio: np.ndarray) -> np.ndarray:
    if audio.ndim == 1:
        return audio
    return np.mean(audio, axis=1)


def _calculate_rms_db(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, int]:
    frame_length = max(1, int(sample_rate * FRAME_SECONDS))
    hop_length = max(1, int(sample_rate * HOP_SECONDS))
    half_frame = frame_length // 2
    padded = np.pad(audio, (half_frame, frame_length - half_frame), mode="constant")
    squared = np.square(padded, dtype=np.float64)
    cumulative = np.concatenate(([0.0], np.cumsum(squared)))
    frame_starts = np.arange(0, len(audio) + 1, hop_length)
    frame_sums = cumulative[frame_starts + frame_length] - cumulative[frame_starts]
    rms = np.sqrt(frame_sums / frame_length)
    return _amp_to_db(rms), hop_length


def _build_gain_curve(rms_db: np.ndarray) -> np.ndarray:
    gain_db = TARGET_DB - rms_db
    gain_db[rms_db < SILENCE_THRESHOLD_DB] = 0.0
    gain_db = np.clip(gain_db, -MAX_CUT_DB, MAX_BOOST_DB)

    smooth_frames = GAIN_SMOOTH_FRAMES
    if smooth_frames > 1:
        if smooth_frames % 2 == 0:
            smooth_frames += 1
        gain_db = median_filter(gain_db, size=smooth_frames)
    return gain_db


def _apply_gain_curve(audio: np.ndarray, gain_db: np.ndarray, hop_length: int) -> np.ndarray:
    frame_positions = np.arange(len(gain_db)) * hop_length
    sample_positions = np.arange(len(audio))
    gain_db_per_sample = np.interp(
        sample_positions,
        frame_positions,
        gain_db,
        left=gain_db[0],
        right=gain_db[-1],
    )
    return audio * _db_to_amp(gain_db_per_sample)


def _peak_limit(audio: np.ndarray) -> np.ndarray:
    peak = float(np.max(np.abs(audio)))
    ceiling_amp = float(_db_to_amp(CEILING_DB))
    if peak > ceiling_amp:
        return audio / peak * ceiling_amp
    return audio


def balance_generated_audio(input_path: Path, session: Path) -> Path:
    output_dir = session / "segments" / "tts_adjusted"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / input_path.name
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    audio, sample_rate = sf.read(input_path, dtype="float32", always_2d=False)
    if audio.size == 0:
        raise ValueError(f"generated audio is empty: {input_path}")

    analysis_audio = _to_mono_for_analysis(audio)
    rms_db_before, hop_length = _calculate_rms_db(analysis_audio, sample_rate)
    gain_db = _build_gain_curve(rms_db_before)

    if audio.ndim == 1:
        adjusted = _apply_gain_curve(audio, gain_db, hop_length)
    else:
        adjusted = np.column_stack(
            [_apply_gain_curve(audio[:, channel], gain_db, hop_length) for channel in range(audio.shape[1])]
        )
    adjusted = _peak_limit(adjusted)

    sf.write(output_path, adjusted, sample_rate)
    rms_db_after, _ = _calculate_rms_db(_to_mono_for_analysis(adjusted), sample_rate)
    log.info(
        "speaker generated audio adjusted input=%s output=%s mean_rms_before=%.2f mean_rms_after=%.2f",
        input_path,
        output_path,
        float(np.mean(rms_db_before)),
        float(np.mean(rms_db_after)),
    )
    return output_path


def stabilize_narration_audio(input_path: Path, session: Path) -> Path:
    return balance_generated_audio(input_path, session)
