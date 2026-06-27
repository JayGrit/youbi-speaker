from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from ydbi_speaker import db, storage
from ydbi_speaker.adapters.voice_profile import VoiceProfile, reference_embedding_object
from ydbi_speaker.config import MODEL_CACHE_DIR, SPEAKER_SIMILARITY_ENABLED

log = logging.getLogger(__name__)

_ENCODER = None


def _similarity_object_prefix(task_id: str) -> str:
    return f"{task_id}/speaker/profile/{db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE}/similarity"


def similarity_json_object(task_id: str, item_index: int) -> str:
    return f"{_similarity_object_prefix(task_id)}/{item_index}.json"


def generated_embedding_object(task_id: str, item_index: int) -> str:
    return f"{_similarity_object_prefix(task_id)}/{item_index}.generated_embedding.npy"


def _load_encoder():
    global _ENCODER
    if _ENCODER is None:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier

        _ENCODER = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(MODEL_CACHE_DIR / "speechbrain-spkrec-ecapa-voxceleb"),
        )
    return _ENCODER


def _embedding(path: Path) -> np.ndarray:
    encoder = _load_encoder()
    encoded = encoder.encode_file(str(path))
    if hasattr(encoded, "detach"):
        encoded = encoded.detach().cpu().numpy()
    return np.asarray(encoded, dtype=np.float32).reshape(-1)


def _save_embedding(path: Path, embedding: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, embedding)


def _load_or_create_reference_embedding(profile: VoiceProfile, profile_dir: Path) -> tuple[Path, str, np.ndarray]:
    embedding_path = profile_dir / "reference_embedding.npy"
    if not embedding_path.exists() or embedding_path.stat().st_size == 0:
        try:
            storage.download(
                profile.reference_embedding_url,
                embedding_path,
                (reference_embedding_object(profile.task_id),),
            )
        except FileNotFoundError:
            pass
    if embedding_path.exists() and embedding_path.stat().st_size > 0:
        return embedding_path, profile.reference_embedding_url, np.load(embedding_path)

    embedding = _embedding(profile.reference_wav)
    _save_embedding(embedding_path, embedding)
    embedding_url = storage.upload(embedding_path, reference_embedding_object(profile.task_id), "application/octet-stream")
    return embedding_path, embedding_url, embedding


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_norm = float(np.linalg.norm(left))
    right_norm = float(np.linalg.norm(right))
    if left_norm == 0.0 or right_norm == 0.0:
        raise ValueError("speaker embedding norm is zero")
    return float(np.dot(left, right) / (left_norm * right_norm))


def _write_similarity_payload(
    session: Path,
    item_index: int,
    payload: dict[str, Any],
) -> Path:
    directory = session / "profile" / db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE / "similarity"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{item_index}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def record_similarity(
    *,
    profile: VoiceProfile,
    row: dict[str, Any],
    generated_wav: Path,
    session: Path,
) -> None:
    if not SPEAKER_SIMILARITY_ENABLED:
        return

    task_id = profile.task_id
    item_index = int(row["item_index"])
    segment_id = int(row["id"]) if row.get("id") is not None else None
    threshold = profile.similarity_threshold
    profile_dir = session / "profile" / db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE

    try:
        _reference_path, reference_embedding_url, reference_embedding = _load_or_create_reference_embedding(
            profile,
            profile_dir,
        )
        generated_embedding = _embedding(generated_wav)
        generated_embedding_path = profile_dir / "similarity" / f"{item_index}.generated_embedding.npy"
        _save_embedding(generated_embedding_path, generated_embedding)
        generated_embedding_url = storage.upload(
            generated_embedding_path,
            generated_embedding_object(task_id, item_index),
            "application/octet-stream",
        )
        similarity_score = _cosine_similarity(reference_embedding, generated_embedding)
        passed = similarity_score >= threshold
        metrics: dict[str, Any] = {
            "similarity_score": similarity_score,
            "threshold": threshold,
            "passed": passed,
            "reference_item_index": profile.reference_item_index,
        }
        payload = {
            "task_id": task_id,
            "segment_id": segment_id,
            "item_index": item_index,
            "sub_stage": profile.sub_stage,
            "reference_embedding_url": reference_embedding_url,
            "generated_embedding_url": generated_embedding_url,
            "similarity_score": similarity_score,
            "threshold": threshold,
            "passed": passed,
            "metrics": metrics,
            "error_message": None,
        }
        payload_path = _write_similarity_payload(session, item_index, payload)
        storage.upload(payload_path, similarity_json_object(task_id, item_index), "application/json")
        db.upsert_segment_similarity(
            task_id=task_id,
            segment_id=segment_id,
            item_index=item_index,
            sub_stage=profile.sub_stage,
            reference_embedding_url=reference_embedding_url,
            generated_embedding_url=generated_embedding_url,
            similarity_score=similarity_score,
            threshold=threshold,
            passed=passed,
            metrics=metrics,
        )
    except Exception as exc:
        message = str(exc)
        log.warning("speaker task=%s index=%d similarity failed: %s", task_id, item_index, message, exc_info=True)
        try:
            payload = {
                "task_id": task_id,
                "segment_id": segment_id,
                "item_index": item_index,
                "sub_stage": profile.sub_stage,
                "reference_embedding_url": profile.reference_embedding_url,
                "generated_embedding_url": None,
                "similarity_score": None,
                "threshold": threshold,
                "passed": None,
                "metrics": None,
                "error_message": message,
            }
            payload_path = _write_similarity_payload(session, item_index, payload)
            storage.upload(payload_path, similarity_json_object(task_id, item_index), "application/json")
        except Exception:
            log.warning("speaker task=%s index=%d failed to upload similarity error payload", task_id, item_index)
        db.upsert_segment_similarity(
            task_id=task_id,
            segment_id=segment_id,
            item_index=item_index,
            sub_stage=profile.sub_stage,
            reference_embedding_url=profile.reference_embedding_url,
            generated_embedding_url=None,
            similarity_score=None,
            threshold=threshold,
            passed=None,
            metrics=None,
            error_message=message,
        )
