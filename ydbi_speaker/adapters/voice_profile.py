from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ydbi_speaker import db, storage
from ydbi_speaker.adapters.audio import split_audio_segments
from ydbi_speaker.adapters.reference import select_global_reference
from ydbi_speaker.adapters.speaker_embedding import embedding, save_embedding
from ydbi_speaker.adapters.voxcpm import fallback_reference, generation_options
from ydbi_speaker.config import SPEAKER_PROFILE_VERSION, SPEAKER_SIMILARITY_THRESHOLD

log = logging.getLogger(__name__)
_PROFILE_LOCKS: dict[str, threading.Lock] = {}
_PROFILE_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class VoiceProfile:
    task_id: str
    sub_stage: str
    profile_version: int
    reference_item_index: int | None
    reference_text: str
    reference_wav: Path
    reference_wav_url: str
    reference_embedding_url: str
    generation_options: dict[str, Any]
    similarity_threshold: float


def _profile_object_prefix(task_id: str) -> str:
    return f"{task_id}/speaker/profile/{db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE}"


def profile_json_object(task_id: str) -> str:
    return f"{_profile_object_prefix(task_id)}/profile.json"


def reference_wav_object(task_id: str) -> str:
    return f"{_profile_object_prefix(task_id)}/reference.wav"


def reference_embedding_object(task_id: str) -> str:
    return f"{_profile_object_prefix(task_id)}/reference_embedding.npy"


def _profile_dir(session: Path) -> Path:
    path = session / "profile" / db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_lock(task_id: str) -> threading.Lock:
    with _PROFILE_LOCKS_GUARD:
        lock = _PROFILE_LOCKS.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _PROFILE_LOCKS[task_id] = lock
        return lock


def _profile_from_payload(task_id: str, payload: dict[str, Any], reference_wav: Path) -> VoiceProfile:
    options = payload.get("generation_options")
    if not isinstance(options, dict):
        options = generation_options()
    return VoiceProfile(
        task_id=task_id,
        sub_stage=str(payload.get("sub_stage") or db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE),
        profile_version=int(payload.get("profile_version") or SPEAKER_PROFILE_VERSION),
        reference_item_index=(
            int(payload["reference_item_index"]) if payload.get("reference_item_index") is not None else None
        ),
        reference_text=str(payload.get("reference_text") or ""),
        reference_wav=reference_wav,
        reference_wav_url=str(payload.get("reference_wav_url") or storage.object_url(reference_wav_object(task_id))),
        reference_embedding_url=str(
            payload.get("reference_embedding_url") or storage.object_url(reference_embedding_object(task_id))
        ),
        generation_options=options,
        similarity_threshold=float(payload.get("similarity_threshold") or SPEAKER_SIMILARITY_THRESHOLD),
    )


def _payload_from_db(row: dict[str, Any]) -> dict[str, Any]:
    options = row.get("generation_options_json")
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except json.JSONDecodeError:
            options = None
    return {
        "task_id": row.get("task_id"),
        "sub_stage": row.get("sub_stage"),
        "profile_version": row.get("profile_version"),
        "reference_item_index": row.get("reference_item_index"),
        "reference_text": row.get("reference_text"),
        "reference_wav_url": row.get("reference_wav_url"),
        "reference_embedding_url": row.get("reference_embedding_url"),
        "generation_options": options,
        "similarity_threshold": row.get("similarity_threshold"),
    }


def _write_local_profile(profile_dir: Path, payload: dict[str, Any]) -> Path:
    profile_path = profile_dir / "profile.json"
    profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile_path


def _upsert_profile(profile: VoiceProfile, error_message: str | None = None, status: str = "ready") -> None:
    db.upsert_voice_profile(
        task_id=profile.task_id,
        sub_stage=profile.sub_stage,
        profile_version=profile.profile_version,
        reference_item_index=profile.reference_item_index,
        reference_text=profile.reference_text,
        reference_wav_url=profile.reference_wav_url,
        reference_embedding_url=profile.reference_embedding_url,
        generation_options=profile.generation_options,
        similarity_threshold=profile.similarity_threshold,
        status=status,
        error_message=error_message,
    )


def _ensure_reference_embedding(profile: VoiceProfile, profile_dir: Path) -> None:
    embedding_path = profile_dir / "reference_embedding.npy"
    object_name = reference_embedding_object(profile.task_id)

    if not embedding_path.exists() or embedding_path.stat().st_size == 0:
        try:
            storage.download(profile.reference_embedding_url, embedding_path, (object_name,))
        except FileNotFoundError:
            reference_embedding = embedding(profile.reference_wav)
            temporary_path = embedding_path.with_suffix(".tmp.npy")
            save_embedding(temporary_path, reference_embedding)
            temporary_path.replace(embedding_path)

    storage.upload_once(embedding_path, object_name, "application/octet-stream")
    _upsert_profile(profile)


def _ensure_ready_profile(profile: VoiceProfile, profile_dir: Path) -> VoiceProfile:
    try:
        _ensure_reference_embedding(profile, profile_dir)
    except Exception as exc:
        _upsert_profile(profile, str(exc), status="failed")
        raise RuntimeError(f"speaker profile embedding is unavailable for task: {profile.task_id}") from exc
    return profile


def _load_existing_profile(task_id: str, session: Path) -> VoiceProfile | None:
    profile_dir = _profile_dir(session)
    reference_path = profile_dir / "reference.wav"

    row = db.get_voice_profile(task_id, db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE)
    if row and row.get("reference_wav_url"):
        payload = _payload_from_db(row)
        try:
            if not reference_path.exists() or reference_path.stat().st_size == 0:
                storage.download(str(row["reference_wav_url"]), reference_path, (reference_wav_object(task_id),))
            profile = _profile_from_payload(task_id, payload, reference_path)
            return _ensure_ready_profile(profile, profile_dir)
        except Exception as exc:
            log.warning("speaker task=%s failed to reuse DB voice profile: %s", task_id, exc)

    profile_path = profile_dir / "profile.json"
    minio_profile_url = storage.object_url(profile_json_object(task_id))
    try:
        storage.download(minio_profile_url, profile_path, (profile_json_object(task_id),))
    except FileNotFoundError:
        pass
    except Exception as exc:
        log.warning("speaker task=%s failed to download voice profile json: %s", task_id, exc)

    if profile_path.exists() and profile_path.stat().st_size > 0:
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        reference_url = str(payload.get("reference_wav_url") or storage.object_url(reference_wav_object(task_id)))
        try:
            if not reference_path.exists() or reference_path.stat().st_size == 0:
                storage.download(reference_url, reference_path, (reference_wav_object(task_id),))
            profile = _profile_from_payload(task_id, payload, reference_path)
            _upsert_profile(profile)
            return _ensure_ready_profile(profile, profile_dir)
        except Exception as exc:
            log.warning("speaker task=%s failed to reuse cached voice profile: %s", task_id, exc)

    return None


def get_or_create_profile(task_id: str, vocals: Path, session: Path) -> VoiceProfile:
    with _profile_lock(task_id):
        return _get_or_create_profile(task_id, vocals, session)


def _get_or_create_profile(task_id: str, vocals: Path, session: Path) -> VoiceProfile:
    existing = _load_existing_profile(task_id, session)
    if existing:
        return existing

    segment_rows = db.list_reference_segments(task_id) or db.list_speaker_segments(task_id)
    if not segment_rows:
        raise RuntimeError(f"speaker has no segment rows for task: {task_id}")

    segment_paths = split_audio_segments(vocals, segment_rows, session)
    try:
        global_reference, candidates = select_global_reference(segment_paths, segment_rows, session)
    except FileNotFoundError:
        log.warning("speaker task=%s could not select a scored profile reference; using legacy fallback", task_id)
        global_reference = fallback_reference(session / "segments" / "vocals")
        candidates = []

    selected_candidate = next((item for item in candidates if float(item.get("score") or 0) > 0), None)
    reference_item_index = int(selected_candidate["item_index"]) if selected_candidate else None
    rows_by_index = {int(row["item_index"]): row for row in segment_rows}
    reference_text = ""
    if reference_item_index is not None:
        reference_text = str(rows_by_index.get(reference_item_index, {}).get("src_text") or "").strip()
    if not reference_text:
        log.warning("speaker task=%s selected profile reference has empty src_text", task_id)

    profile_dir = _profile_dir(session)
    reference_path = profile_dir / "reference.wav"
    if global_reference.resolve() != reference_path.resolve():
        shutil.copy2(global_reference, reference_path)

    reference_wav_url = storage.upload(reference_path, reference_wav_object(task_id), "audio/wav")
    reference_embedding_url = storage.object_url(reference_embedding_object(task_id))
    payload = {
        "task_id": task_id,
        "sub_stage": db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
        "profile_version": SPEAKER_PROFILE_VERSION,
        "reference_item_index": reference_item_index,
        "reference_text": reference_text,
        "reference_wav_url": reference_wav_url,
        "reference_embedding_url": reference_embedding_url,
        "generation_options": generation_options(),
        "similarity_threshold": SPEAKER_SIMILARITY_THRESHOLD,
    }
    profile_path = _write_local_profile(profile_dir, payload)
    storage.upload(profile_path, profile_json_object(task_id), "application/json")

    profile = _profile_from_payload(task_id, payload, reference_path)
    _upsert_profile(profile, "reference_text is empty" if not reference_text else None)
    return _ensure_ready_profile(profile, profile_dir)
