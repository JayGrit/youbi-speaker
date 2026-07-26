from __future__ import annotations

from .. import db as _core

def get_task(task_id: str) -> dict[str, _core.Any] | None:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute('SELECT id FROM task WHERE id = %s', (task_id,))
        task = cur.fetchone()
        if not task:
            return None
        task['task_info'] = _core.task_info.get(task_id, fields=_core.SPEAKER_TASK_INFO_FIELDS)
        return task

def find_ready(stage_name: str) -> dict[str, _core.Any] | None:
    table = _core._service_table_for(stage_name)
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute(f'\n            SELECT s.*\n            FROM {table} s\n            WHERE s.stage_name = %s\n              AND s.status = %s\n            ORDER BY s.task_id ASC\n            LIMIT 1\n            ', (stage_name, _core.READY))
        return _core.task_info.merge_into(cur.fetchone(), fields=_core.SPEAKER_TASK_INFO_FIELDS)

def mark_running(stage_name: str, task_id: str, sub_stage: str=_core.SPEAKER_MAIN_SUB_STAGE) -> bool:
    table = _core._service_table_for(stage_name)
    operator = _core._operator_value()
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE {table}\n            SET status = %s,\n                started_at = COALESCE(started_at, NOW()),\n                error_message = NULL,\n                `operator` = %s\n            WHERE task_id = %s AND stage_name = %s AND sub_stage = %s AND status = %s\n            ', (_core.RUNNING, operator, task_id, stage_name, sub_stage, _core.READY))
        stage_updated = cur.rowcount == 1
        conn.commit()
        return stage_updated

def _update_stage_fields(stage_name: str, task_id: str, fields: _core.Mapping[str, _core.Any], sub_stage: str=_core.SPEAKER_MAIN_SUB_STAGE) -> None:
    return
    table = _core._service_table_for(stage_name)
    assignments = ', '.join((f'{key} = %s' for key in fields))
    values = list(fields.values()) + [task_id, sub_stage]
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'UPDATE {table} SET {assignments} WHERE task_id = %s AND sub_stage = %s', values)
        conn.commit()

def set_combiner_speaker_inputs(task_id: str, translation_json_path: str, tts_segments_dir: str) -> None:
    _core.task_info.upsert(task_id, {'translation_json_path': translation_json_path, 'tts_segments_dir': tts_segments_dir})

def mark_success(stage_name: str, task_id: str, outputs: _core.Mapping[str, _core.Any] | None=None, sub_stage: str=_core.SPEAKER_MAIN_SUB_STAGE) -> None:
    table = _core._service_table_for(stage_name)
    fields = dict(outputs or {})
    stage_fields: dict[str, _core.Any] = {}
    assignments = ['status = %s', 'completed_at = NOW()', 'error_message = NULL']
    values: list[_core.Any] = [_core.SUCCESS]
    for key, value in stage_fields.items():
        assignments.append(f'{key} = %s')
        values.append(value)
    values.extend([task_id, stage_name, sub_stage])
    with _core.connect() as conn:
        cur = conn.cursor()
        _core.task_info.upsert(task_id, fields, cur)
        cur.execute(f"UPDATE {table} SET {', '.join(assignments)} WHERE task_id = %s AND stage_name = %s AND sub_stage = %s", tuple(values))
        conn.commit()

def mark_failed(stage_name: str, task_id: str, message: str, sub_stage: str=_core.SPEAKER_MAIN_SUB_STAGE) -> None:
    table = _core._service_table_for(stage_name)
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f'\n            UPDATE {table}\n            SET status = %s, error_message = %s, completed_at = NOW()\n            WHERE task_id = %s AND stage_name = %s AND sub_stage = %s\n            ', (_core.FAILED, message, task_id, stage_name, sub_stage))
        conn.commit()
