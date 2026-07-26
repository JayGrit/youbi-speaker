from __future__ import annotations

from .. import db as _core

def get_voice_profile(task_id: str, sub_stage: str) -> dict[str, _core.Any] | None:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute(f'\n            SELECT task_id, sub_stage, profile_version, reference_item_index, reference_text,\n                   reference_wav_url, reference_embedding_url, generation_options_json,\n                   similarity_threshold, status, error_message\n            FROM {_core.SPEAKER_VOICE_PROFILE_TABLE}\n            WHERE task_id = %s AND sub_stage = %s\n            ', (task_id, sub_stage))
        return cur.fetchone()

def upsert_voice_profile(*, task_id: str, sub_stage: str, profile_version: int, reference_item_index: int | None, reference_text: str | None, reference_wav_url: str | None, reference_embedding_url: str | None, generation_options: _core.Mapping[str, _core.Any] | None, similarity_threshold: float | None, status: str='ready', error_message: str | None=None) -> None:
    generation_options_json = _core.json.dumps(generation_options, ensure_ascii=False) if generation_options is not None else None
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            INSERT INTO {_core.SPEAKER_VOICE_PROFILE_TABLE}\n              (\n                task_id, sub_stage, profile_version, reference_item_index, reference_text,\n                reference_wav_url, reference_embedding_url, generation_options_json,\n                similarity_threshold, status, error_message\n              )\n            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n            ON DUPLICATE KEY UPDATE\n              profile_version = VALUES(profile_version),\n              reference_item_index = VALUES(reference_item_index),\n              reference_text = VALUES(reference_text),\n              reference_wav_url = VALUES(reference_wav_url),\n              reference_embedding_url = VALUES(reference_embedding_url),\n              generation_options_json = VALUES(generation_options_json),\n              similarity_threshold = VALUES(similarity_threshold),\n              status = VALUES(status),\n              error_message = VALUES(error_message)\n            ', (task_id, sub_stage, profile_version, reference_item_index, reference_text, reference_wav_url, reference_embedding_url, generation_options_json, similarity_threshold, status, error_message))
        conn.commit()

def upsert_segment_similarity(*, task_id: str, segment_id: int | None, item_index: int, sub_stage: str, reference_embedding_url: str | None, generated_embedding_url: str | None, similarity_score: float | None, threshold: float | None, passed: bool | None, metrics: _core.Mapping[str, _core.Any] | None, error_message: str | None=None) -> None:
    metrics_json = _core.json.dumps(metrics, ensure_ascii=False) if metrics is not None else None
    passed_value = None if passed is None else int(passed)
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            INSERT INTO {_core.SPEAKER_SEGMENT_SIMILARITY_TABLE}\n              (\n                task_id, segment_id, item_index, sub_stage, reference_embedding_url,\n                generated_embedding_url, similarity_score, threshold, passed,\n                metrics_json, error_message\n              )\n            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n            ON DUPLICATE KEY UPDATE\n              segment_id = VALUES(segment_id),\n              reference_embedding_url = VALUES(reference_embedding_url),\n              generated_embedding_url = VALUES(generated_embedding_url),\n              similarity_score = VALUES(similarity_score),\n              threshold = VALUES(threshold),\n              passed = VALUES(passed),\n              metrics_json = VALUES(metrics_json),\n              error_message = VALUES(error_message)\n            ', (task_id, segment_id, item_index, sub_stage, reference_embedding_url, generated_embedding_url, similarity_score, threshold, passed_value, metrics_json, error_message))
        conn.commit()
