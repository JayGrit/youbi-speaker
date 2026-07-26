from __future__ import annotations

from .. import db as _core

def _build_narration_segments(sentence_rows: list[dict[str, _core.Any]]) -> list[str]:
    if not sentence_rows:
        raise ValueError('narration sentence rows are required')
    segments: list[str] = []
    current_segment_index = 1
    current_lines: list[str] = []
    expected_line_index = 1
    for row in sentence_rows:
        line_index = int(row['line_index'])
        segment_index = int(row['segment_index'])
        sentence_text = str(row.get('sentence_text') or '').strip()
        if line_index != expected_line_index:
            raise ValueError(f'narration sentence line index is not contiguous at {line_index}')
        if not sentence_text:
            raise ValueError(f'narration sentence {line_index} is empty')
        allowed_segment_indexes = {current_segment_index} if not current_lines else {current_segment_index, current_segment_index + 1}
        if segment_index not in allowed_segment_indexes:
            raise ValueError(f'narration segment index is not contiguous at line {line_index}')
        if segment_index == current_segment_index + 1:
            segment_text = '\n'.join(current_lines)
            if len(segment_text) > _core.MAX_NARRATION_SEGMENT_CHARS:
                raise ValueError(f'narration segment {current_segment_index} exceeds 500 characters')
            segments.append(segment_text)
            current_segment_index = segment_index
            current_lines = []
        current_lines.append(sentence_text)
        expected_line_index += 1
    segment_text = '\n'.join(current_lines)
    if len(segment_text) > _core.MAX_NARRATION_SEGMENT_CHARS:
        raise ValueError(f'narration segment {current_segment_index} exceeds 500 characters')
    segments.append(segment_text)
    return segments

def _build_ppt_dialogue_segments(raw_json: str) -> list[dict[str, _core.Any]]:
    try:
        data = _core.json.loads(raw_json)
    except _core.json.JSONDecodeError as exc:
        raise ValueError('product_ppt.ppt_dialogue_json is not valid JSON') from exc
    if not isinstance(data, list) or not data:
        raise ValueError('product_ppt.ppt_dialogue_json must be a non-empty array')
    segments: list[dict[str, _core.Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f'ppt dialogue item {index} must be an object')
        try:
            speaker = int(item.get('speaker'))
        except (TypeError, ValueError) as exc:
            raise ValueError(f'ppt dialogue item {index} has invalid speaker') from exc
        if speaker not in {0, 1}:
            raise ValueError(f'ppt dialogue item {index} speaker must be 0 or 1')
        content = str(item.get('content') or '').strip()
        if not content:
            raise ValueError(f'ppt dialogue item {index} content is empty')
        segments.append({'speaker': speaker, 'content': content})
    return segments

def initialize_ready_speaker_task() -> tuple[str, int] | None:
    with _core.connect() as conn:
        conn.start_transaction()
        cur = _core._dict_cursor(conn)
        cur.execute("\n            SELECT sp.task_id, sp.sub_stage, vi.task_type, pp.ppt_dialogue_json\n            FROM distributor_task_stages sp\n            JOIN task vi ON vi.id = sp.task_id\n            LEFT JOIN product_ppt pp ON pp.task_id = sp.task_id\n            LEFT JOIN distributor_task_stages tr ON tr.task_id = sp.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'\n            WHERE sp.stage_name = 'speaker'\n              AND sp.status = %s\n              AND (\n                (\n                  sp.sub_stage = %s\n                  AND vi.task_type = 'narration'\n                  AND EXISTS (\n                    SELECT 1\n                    FROM product_narration_sentence narration_sentence\n                    WHERE narration_sentence.task_id = sp.task_id\n                  )\n                )\n                OR (\n                  sp.sub_stage = %s\n                  AND vi.task_type IN (%s, %s)\n                  AND tr.status = %s\n                )\n                OR (\n                  sp.sub_stage = %s\n                  AND vi.task_type = 'ppt'\n                  AND NULLIF(TRIM(COALESCE(pp.ppt_dialogue_json, '')), '') IS NOT NULL\n                )\n                OR (\n                  sp.sub_stage = %s\n                  AND vi.task_type <> 'narration'\n                  AND vi.task_type <> 'ppt'\n                  AND vi.task_type NOT IN (%s, %s)\n                  AND tr.status = %s\n                )\n              )\n              AND NOT EXISTS (\n                SELECT 1\n                FROM speaker_segment seg\n                WHERE seg.task_id = sp.task_id\n              )\n            ORDER BY sp.task_id ASC\n            LIMIT 1\n            FOR UPDATE\n            ", (_core.READY, _core.SPEAKER_NARRATION_SUB_STAGE, _core.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES, _core.SUCCESS, _core.SPEAKER_PPT_DIALOGUE_SUB_STAGE, _core.SPEAKER_MAIN_SUB_STAGE, *_core.CHUNK_SPEAKER_TASK_TYPES, _core.SUCCESS))
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        task_id = str(row['task_id'])
        cur = conn.cursor()
        if row.get('sub_stage') == _core.SPEAKER_NARRATION_SUB_STAGE:
            sentence_cur = _core._dict_cursor(conn)
            sentence_cur.execute(f'\n                SELECT line_index, sentence_text, segment_index\n                FROM {_core.PRODUCT_NARRATION_SENTENCE_TABLE}\n                WHERE task_id = %s\n                ORDER BY line_index ASC\n                ', (task_id,))
            segments = _core._build_narration_segments(list(sentence_cur.fetchall()))
            cur.executemany("\n                INSERT INTO speaker_segment\n                  (\n                    task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,\n                    start_time, end_time, speaker\n                  )\n                VALUES (%s, %s, %s, %s, %s, 'zh', 'zh', 0, 0, NULL)\n                ", [(task_id, item_index, _core.SEGMENT_READY, segment_text, segment_text) for item_index, segment_text in enumerate(segments)])
            inserted = int(cur.rowcount)
            conn.commit()
            return (task_id, inserted)
        if row.get('sub_stage') == _core.SPEAKER_PPT_DIALOGUE_SUB_STAGE:
            segments = _core._build_ppt_dialogue_segments(str(row.get('ppt_dialogue_json') or ''))
            cur.executemany("\n                INSERT INTO speaker_segment\n                  (\n                    task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,\n                    start_time, end_time, speaker\n                  )\n                VALUES (%s, %s, %s, %s, %s, 'zh', 'zh', 0, 0, %s)\n                ", [(task_id, item_index, _core.SEGMENT_READY, item['content'], item['content'], str(item['speaker'])) for item_index, item in enumerate(segments)])
            inserted = int(cur.rowcount)
            conn.commit()
            return (task_id, inserted)
        if row.get('sub_stage') == _core.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE:
            chunk_table = _core._quote_identifier(_core._translator_chunk_table_cur(cur))
            cur.execute(f"\n                INSERT INTO speaker_segment\n                  (\n                    task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,\n                    start_time, end_time, speaker\n                  )\n                SELECT\n                  tc.task_id,\n                  tc.chunk_index AS item_index,\n                  %s AS status,\n                  COALESCE(GROUP_CONCAT(NULLIF(TRIM(COALESCE(ts.src_text, tc.text)), '') ORDER BY tc.row_order SEPARATOR '\\n'), '') AS src_text,\n                  COALESCE(GROUP_CONCAT(NULLIF(TRIM(ts.dst_text), '') ORDER BY tc.row_order SEPARATOR '\\n'), '') AS dst_text,\n                  MIN(ts.src_lang) AS src_lang,\n                  MAX(ts.dst_lang) AS dst_lang,\n                  MIN(tc.chunk_start_time) AS start_time,\n                  MAX(tc.chunk_end_time) AS end_time,\n                  SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(ts.speaker, '') ORDER BY tc.row_order SEPARATOR ','), ',', 1) AS speaker\n                FROM {chunk_table} tc\n                JOIN {_core.TRANSLATOR_SEGMENT_TABLE} ts\n                  ON ts.task_id = tc.task_id\n                 AND ts.item_index = tc.item_index\n                WHERE tc.task_id = %s\n                  AND tc.row_role = 'normal'\n                GROUP BY tc.task_id, tc.chunk_index\n                ORDER BY tc.chunk_index ASC\n                ", (_core.SEGMENT_READY, task_id))
            inserted = int(cur.rowcount)
            conn.commit()
            return (task_id, inserted)
        cur.execute(f'\n            INSERT INTO speaker_segment\n              (\n                task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,\n                start_time, end_time, speaker\n              )\n            SELECT\n              task_id, item_index, %s, src_text, dst_text, src_lang, dst_lang,\n              start_time, end_time, speaker\n            FROM {_core.TRANSLATOR_SEGMENT_TABLE}\n            WHERE task_id = %s\n            ORDER BY item_index ASC\n            ', (_core.SEGMENT_READY, task_id))
        inserted = int(cur.rowcount)
        conn.commit()
        return (task_id, inserted)
