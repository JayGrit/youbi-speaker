from __future__ import annotations

from .. import db as _core

def list_speaker_segments(task_id: str) -> list[dict[str, _core.Any]]:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute('\n            SELECT id, task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,\n                   start_time, end_time, speaker, reference_wav_path, reference_wav_url,\n                   tts_wav_path, tts_wav_url\n            FROM speaker_segment\n            WHERE task_id = %s\n            ORDER BY item_index ASC\n            ', (task_id,))
        return list(cur.fetchall())

def get_speaker_segment(task_id: str, item_index: int) -> dict[str, _core.Any] | None:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute("\n            SELECT seg.*,\n                   vi.task_type AS task_type,\n                   sp.sub_stage AS speaker_sub_stage,\n                   proc.translation_json_path AS translation_json_path\n            FROM speaker_segment seg\n            JOIN task vi ON vi.id = seg.task_id\n            LEFT JOIN task_processing proc ON proc.task_id = seg.task_id\n            JOIN distributor_task_stages sp\n              ON sp.task_id = seg.task_id\n             AND sp.stage_name = 'speaker'\n             AND sp.sub_stage = CASE\n                   WHEN vi.task_type = 'narration' THEN %s\n                   WHEN vi.task_type IN (%s, %s) THEN %s\n                   WHEN vi.task_type = 'ppt' THEN %s\n                   ELSE %s\n                 END\n            WHERE seg.task_id = %s\n              AND seg.item_index = %s\n            LIMIT 1\n            ", (_core.SPEAKER_NARRATION_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES, _core.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE, _core.SPEAKER_PPT_DIALOGUE_SUB_STAGE, _core.SPEAKER_MAIN_SUB_STAGE, task_id, item_index))
        return _core.task_info.merge_into(cur.fetchone(), fields=_core.SPEAKER_TASK_INFO_FIELDS)

def mark_speaker_segment_success(segment_id: int, reference_wav_path: str, reference_wav_url: str, tts_wav_path: str, tts_wav_url: str, attempt_count: int | None=None) -> bool:
    operator = _core._operator_value()
    where = 'id = %s'
    where_values: list[_core.Any] = [segment_id]
    if attempt_count is not None:
        where += ' AND attempt_count = %s AND status = %s'
        where_values.extend([attempt_count, _core.SEGMENT_RUNNING])
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE speaker_segment\n            SET status = %s,\n                reference_wav_path = %s,\n                reference_wav_url = %s,\n                tts_wav_path = %s,\n                tts_wav_url = %s,\n                started_at = COALESCE(started_at, NOW()),\n                completed_at = NOW(),\n                error_message = NULL,\n                `operator` = %s\n            WHERE {where}\n            ', (_core.SEGMENT_SUCCESS, reference_wav_path, reference_wav_url, tts_wav_path, tts_wav_url, operator, *where_values))
        updated = cur.rowcount == 1
        conn.commit()
        return updated

def reset_speaker_segment_after_worker_crash(segment_id: int, message: str, attempt_count: int | None=None) -> bool:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute('SELECT status, attempt_count, max_attempts FROM speaker_segment WHERE id = %s', (segment_id,))
        row = cur.fetchone()
        if not row:
            conn.commit()
            return False
        if attempt_count is not None and (int(row['attempt_count']) != attempt_count or str(row['status']) != _core.SEGMENT_RUNNING):
            conn.commit()
            return False
        exhausted = int(row['attempt_count']) >= int(row['max_attempts'])
        status = _core.SEGMENT_FAILED if exhausted else _core.SEGMENT_READY
        completed_at = 'NOW()' if exhausted else 'NULL'
        where = 'id = %s AND status = %s'
        values: list[_core.Any] = [status, message, segment_id, _core.SEGMENT_RUNNING]
        if attempt_count is not None:
            where += ' AND attempt_count = %s'
            values.append(attempt_count)
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE speaker_segment\n            SET status = %s,\n                error_message = %s,\n                started_at = NULL,\n                completed_at = {completed_at},\n                `operator` = NULL\n            WHERE {where}\n            ', tuple(values))
        updated = cur.rowcount == 1
        conn.commit()
        return updated

def mark_speaker_segment_failed(segment_id: int, message: str, attempt_count: int | None=None) -> bool:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute('SELECT status, attempt_count, max_attempts FROM speaker_segment WHERE id = %s', (segment_id,))
        row = cur.fetchone()
        if not row:
            conn.commit()
            return True
        if attempt_count is not None and (int(row['attempt_count']) != attempt_count or str(row['status']) != _core.SEGMENT_RUNNING):
            conn.commit()
            return False
        exhausted = int(row['attempt_count']) >= int(row['max_attempts'])
        status = _core.SEGMENT_FAILED if exhausted else _core.SEGMENT_READY
        completed_at = 'NOW()' if exhausted else 'NULL'
        where = 'id = %s'
        values: list[_core.Any] = [status, message, segment_id]
        if attempt_count is not None:
            where += ' AND attempt_count = %s AND status = %s'
            values.extend([attempt_count, _core.SEGMENT_RUNNING])
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE speaker_segment\n            SET status = %s,\n                error_message = %s,\n                completed_at = {completed_at}\n            WHERE {where}\n            ', tuple(values))
        if cur.rowcount != 1:
            exhausted = False
        conn.commit()
        return exhausted
