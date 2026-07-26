from __future__ import annotations

from .. import db as _core

def find_finalizable_speaker_task(task_id: str | None=None) -> dict[str, _core.Any] | None:
    task_filter = 'AND sp.task_id = %s' if task_id is not None else ''
    params: list[_core.Any] = ['speaker', _core.READY, _core.RUNNING, _core.SPEAKER_NARRATION_SUB_STAGE, _core.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES, _core.SUCCESS, _core.SPEAKER_PPT_DIALOGUE_SUB_STAGE, _core.SPEAKER_MAIN_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES, _core.SUCCESS]
    if task_id is not None:
        params.append(task_id)
    params.append(_core.SEGMENT_SUCCESS)
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute(f"\n            SELECT sp.*\n            FROM distributor_task_stages sp\n            JOIN task vi ON vi.id = sp.task_id\n            LEFT JOIN distributor_task_stages tr ON tr.task_id = sp.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'\n            WHERE sp.stage_name = %s\n              AND sp.status IN (%s, %s)\n              AND (\n                (sp.sub_stage = %s AND vi.task_type = 'narration')\n                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s) AND tr.status = %s)\n                OR (sp.sub_stage = %s AND vi.task_type = 'ppt')\n                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s) AND tr.status = %s)\n              )\n              {task_filter}\n              AND EXISTS (\n                SELECT 1 FROM speaker_segment seg\n                WHERE seg.task_id = sp.task_id\n              )\n              AND NOT EXISTS (\n                SELECT 1 FROM speaker_segment seg\n                WHERE seg.task_id = sp.task_id\n                  AND seg.status <> %s\n              )\n            ORDER BY sp.task_id ASC\n            LIMIT 1\n            ", params)
        return _core.task_info.merge_into(cur.fetchone(), fields=_core.SPEAKER_TASK_INFO_FIELDS)

def find_terminal_failed_speaker_task(task_id: str | None=None) -> dict[str, _core.Any] | None:
    task_filter = 'AND sp.task_id = %s' if task_id is not None else ''
    params: list[_core.Any] = [_core.SEGMENT_FAILED, 'speaker', _core.READY, _core.RUNNING, _core.SPEAKER_NARRATION_SUB_STAGE, _core.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES, _core.SPEAKER_PPT_DIALOGUE_SUB_STAGE, _core.SPEAKER_MAIN_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES]
    if task_id is not None:
        params.append(task_id)
    params.extend([_core.SEGMENT_FAILED, _core.SEGMENT_PENDING, _core.SEGMENT_READY, _core.SEGMENT_RUNNING])
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute(f"\n            SELECT sp.task_id,\n                   sp.sub_stage,\n                   COALESCE(\n                       (\n                         SELECT seg.error_message\n                         FROM speaker_segment seg\n                         WHERE seg.task_id = sp.task_id\n                           AND seg.status = %s\n                           AND seg.error_message IS NOT NULL\n                           AND seg.error_message <> ''\n                         ORDER BY seg.item_index ASC\n                         LIMIT 1\n                       ),\n                       'one or more speaker segments failed'\n                   ) AS error_message\n            FROM distributor_task_stages sp\n            JOIN task vi ON vi.id = sp.task_id\n            WHERE sp.stage_name = %s\n              AND sp.status IN (%s, %s)\n              AND (\n                (sp.sub_stage = %s AND vi.task_type = 'narration')\n                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s))\n                OR (sp.sub_stage = %s AND vi.task_type = 'ppt')\n                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s))\n              )\n              {task_filter}\n              AND EXISTS (\n                SELECT 1 FROM speaker_segment seg\n                WHERE seg.task_id = sp.task_id\n                  AND seg.status = %s\n              )\n              AND NOT EXISTS (\n                SELECT 1 FROM speaker_segment seg\n                WHERE seg.task_id = sp.task_id\n                  AND seg.status IN (%s, %s, %s)\n              )\n            ORDER BY sp.task_id ASC\n            LIMIT 1\n            ", params)
        return cur.fetchone()

def list_successful_speaker_task_ids(task_ids: list[str]) -> set[str]:
    if not task_ids:
        return set()
    placeholders = ', '.join(['%s'] * len(task_ids))
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute(f"\n            SELECT task_id\n            FROM distributor_task_stages\n            WHERE stage_name = 'speaker'\n              AND status = %s\n              AND task_id IN ({placeholders})\n            ", (_core.SUCCESS, *task_ids))
        return {str(row['task_id']) for row in cur.fetchall()}

def mark_speaker_failed_from_segment(task_id: str, message: str, sub_stage: str=_core.SPEAKER_MAIN_SUB_STAGE) -> None:
    if sub_stage == _core.SPEAKER_PPT_DIALOGUE_SUB_STAGE:
        _core.mark_ppt_dialogue_failed(task_id, message)
    _core.mark_failed(_core.SERVICE_NAME, task_id, message, sub_stage)
