from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping
from pathlib import Path
from statistics import pstdev
from typing import Any

from pydub import AudioSegment
from pydub.silence import detect_silence

MIN_REFERENCE_MS = 1800
BEST_MIN_MS = 3000
BEST_MAX_MS = 10000
MAX_REFERENCE_MS = 15000
TARGET_REFERENCE_MS = 10000


def _finite_db(value: float) -> float:
    if math.isinf(value) or math.isnan(value):
        return -120.0
    return value


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _duration_score(duration_ms: int) -> float:
    if duration_ms < MIN_REFERENCE_MS:
        return 0.0
    if duration_ms < BEST_MIN_MS:
        return 10.0 + 20.0 * (duration_ms - MIN_REFERENCE_MS) / (BEST_MIN_MS - MIN_REFERENCE_MS)
    if duration_ms <= BEST_MAX_MS:
        return 30.0
    if duration_ms <= MAX_REFERENCE_MS:
        return 30.0 - 10.0 * (duration_ms - BEST_MAX_MS) / (MAX_REFERENCE_MS - BEST_MAX_MS)
    return 10.0


def _loudness_score(rms_db: float) -> float:
    if -28.0 <= rms_db <= -14.0:
        return 20.0
    distance = min(abs(rms_db + 28.0), abs(rms_db + 14.0))
    return _clamp(20.0 - distance * 1.5, 0.0, 20.0)


def _source_text_score(text: str) -> float:
    cleaned = "".join(ch for ch in text.strip() if not ch.isspace())
    length = len(cleaned)
    if length <= 1:
        return 0.0
    if length < 6:
        return 2.0 + length
    if length <= 80:
        return 10.0
    return 7.0


def _stability_score(audio: AudioSegment) -> float:
    chunk_values = [
        _finite_db(audio[start : start + 250].dBFS)
        for start in range(0, len(audio), 250)
        if len(audio[start : start + 250]) >= 120
    ]
    voiced = [value for value in chunk_values if value > -45.0]
    if len(voiced) < 2:
        return 0.0
    return _clamp(10.0 - pstdev(voiced), 0.0, 10.0)


def _trim_if_long(audio: AudioSegment) -> AudioSegment:
    if len(audio) <= MAX_REFERENCE_MS:
        return audio
    center = len(audio) // 2
    half = TARGET_REFERENCE_MS // 2
    return audio[max(0, center - half) : min(len(audio), center + half)]


def _metrics(path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    audio = _trim_if_long(AudioSegment.from_file(path))
    duration_ms = len(audio)
    rms_db = _finite_db(audio.dBFS)
    peak_db = _finite_db(audio.max_dBFS)
    silence = detect_silence(audio, min_silence_len=180, silence_thresh=max(rms_db - 14.0, -45.0))
    silence_ms = sum(end - start for start, end in silence)
    silence_ratio = silence_ms / duration_ms if duration_ms else 1.0
    text = str(row.get("src_text") or "")

    duration = _duration_score(duration_ms)
    loudness = _loudness_score(rms_db)
    speech_density = _clamp((1.0 - silence_ratio) * 20.0, 0.0, 20.0)
    clipping = 10.0 if peak_db <= -3.0 else 5.0 if peak_db <= -1.0 else 0.0
    source_text = _source_text_score(text)
    stability = _stability_score(audio)

    disqualified = (
        duration_ms < MIN_REFERENCE_MS
        or silence_ratio > 0.45
        or rms_db < -35.0
        or rms_db > -8.0
    )
    penalty = 20.0 if peak_db > -0.5 else 0.0
    score = 0.0 if disqualified else duration + loudness + speech_density + clipping + source_text + stability - penalty

    return {
        "item_index": int(row["item_index"]),
        "path": str(path),
        "duration_ms": duration_ms,
        "rms_db": round(rms_db, 2),
        "peak_db": round(peak_db, 2),
        "silence_ratio": round(silence_ratio, 4),
        "score": round(max(0.0, score), 2),
        "disqualified": disqualified,
        "components": {
            "duration": round(duration, 2),
            "loudness": round(loudness, 2),
            "speech_density": round(speech_density, 2),
            "clipping": round(clipping, 2),
            "source_text": round(source_text, 2),
            "stability": round(stability, 2),
            "penalty": round(penalty, 2),
        },
    }


def select_global_reference(
    segment_paths: Mapping[int, Path],
    segment_rows: list[Mapping[str, Any]],
    session: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    reference_dir = session / "speaker"
    reference_dir.mkdir(parents=True, exist_ok=True)
    reference_file = reference_dir / "reference.wav"
    candidates_file = reference_dir / "reference_candidates.json"
    if reference_file.exists() and reference_file.stat().st_size > 0 and candidates_file.exists():
        data = json.loads(candidates_file.read_text(encoding="utf-8"))
        candidates = data.get("candidates") or []
        return reference_file, candidates

    rows_by_index = {int(row["item_index"]): row for row in segment_rows}
    candidates = [
        _metrics(path, rows_by_index[item_index])
        for item_index, path in segment_paths.items()
        if path.exists() and path.stat().st_size > 0 and item_index in rows_by_index
    ]
    candidates.sort(key=lambda item: item["score"], reverse=True)
    candidates_file.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")

    usable = [item for item in candidates if item["score"] > 0]
    if not usable:
        raise FileNotFoundError("No usable vocal reference segment was found.")

    selected = Path(usable[0]["path"])
    if not reference_file.exists() or reference_file.stat().st_size == 0:
        audio = AudioSegment.from_file(selected)
        if len(audio) > MAX_REFERENCE_MS:
            _trim_if_long(audio).export(reference_file, format="wav")
        else:
            shutil.copy2(selected, reference_file)
    return reference_file, candidates
