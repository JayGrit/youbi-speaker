from __future__ import annotations

from .. import db as _core

def claim_ready_blessing_task() -> dict[str, _core.Any] | None:
    operator = _core._operator_value()
    with _core.connect() as conn:
        conn.start_transaction()
        cur = _core._dict_cursor(conn)
        cur.execute(f"\n            SELECT sp.task_id, pb.tts_text\n            FROM distributor_task_stages sp\n            JOIN task vi ON vi.id = sp.task_id\n            JOIN {_core.PRODUCT_BLESSING_TABLE} pb ON pb.task_id = sp.task_id\n            WHERE sp.stage_name = 'speaker'\n              AND sp.sub_stage = %s\n              AND sp.status = %s\n              AND vi.task_type = 'blessing'\n              AND NULLIF(TRIM(COALESCE(pb.tts_text, '')), '') IS NOT NULL\n            ORDER BY sp.task_id ASC\n            LIMIT 1\n            FOR UPDATE\n            ", (_core.SPEAKER_BLESSING_SUB_STAGE, _core.READY))
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        task_id = str(row['task_id'])
        cur = conn.cursor()
        cur.execute(f"\n            UPDATE {_core.SERVICE_TABLE}\n            SET status = %s,\n                started_at = COALESCE(started_at, NOW()),\n                error_message = NULL,\n                `operator` = %s\n            WHERE task_id = %s\n              AND stage_name = 'speaker'\n              AND sub_stage = %s\n              AND status = %s\n            ", (_core.RUNNING, operator, task_id, _core.SPEAKER_BLESSING_SUB_STAGE, _core.READY))
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        return {'task_id': task_id, 'tts_text': str(row.get('tts_text') or '')}

def mark_blessing_success(task_id: str, audio_url: str) -> None:
    operator = _core._operator_value()
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE {_core.PRODUCT_BLESSING_TABLE}\n            SET background_music_url = %s,\n                error_message = NULL,\n                `operator` = %s\n            WHERE task_id = %s\n            ', (audio_url, operator, task_id))
        conn.commit()
    _core.mark_success(_core.SERVICE_NAME, task_id, {'tts_segments_dir': audio_url}, _core.SPEAKER_BLESSING_SUB_STAGE)

def mark_blessing_failed(task_id: str, message: str) -> None:
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE {_core.PRODUCT_BLESSING_TABLE}\n            SET error_message = %s,\n                `operator` = %s\n            WHERE task_id = %s\n            ', (message, _core._operator_value(), task_id))
        conn.commit()
    _core.mark_failed(_core.SERVICE_NAME, task_id, message, _core.SPEAKER_BLESSING_SUB_STAGE)

def mark_ppt_dialogue_success(task_id: str, audio_url: str) -> None:
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            INSERT INTO {_core.PRODUCT_PPT_TABLE}\n              (task_id, ppt_dialogue_audio_url, status, completed_at, error_message, `operator`)\n            VALUES (%s, %s, %s, NOW(), NULL, %s)\n            ON DUPLICATE KEY UPDATE\n              ppt_dialogue_audio_url = VALUES(ppt_dialogue_audio_url),\n              status = VALUES(status),\n              completed_at = VALUES(completed_at),\n              error_message = NULL,\n              `operator` = VALUES(`operator`)\n            ', (task_id, audio_url, _core.SUCCESS, _core._operator_value()))
        conn.commit()

def mark_ppt_dialogue_failed(task_id: str, message: str) -> None:
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            INSERT INTO {_core.PRODUCT_PPT_TABLE}\n              (task_id, status, error_message, completed_at, `operator`)\n            VALUES (%s, %s, %s, NOW(), %s)\n            ON DUPLICATE KEY UPDATE\n              status = VALUES(status),\n              error_message = VALUES(error_message),\n              completed_at = VALUES(completed_at),\n              `operator` = VALUES(`operator`)\n            ', (task_id, _core.FAILED, message, _core._operator_value()))
        conn.commit()
