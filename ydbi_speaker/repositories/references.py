from __future__ import annotations

from .. import db as _core

def demucs_operator_for(task_id: str) -> str | None:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        cur.execute("\n            SELECT `operator`\n            FROM distributor_task_stages\n            WHERE task_id = %s AND stage_name = 'demucs' AND sub_stage = 'main'\n            ", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        operator = row.get('operator')
        return str(operator).strip() if operator else None

def blessing_reference_voice_url() -> str:
    configured = _core.os.environ.get('BLESSING_REFERENCE_VOICE_URL', '').strip()
    if configured:
        return configured
    return _core._asset_voice_url_by_remark(_core.BLESSING_REFERENCE_VOICE_REMARK)

def _asset_voice_url_by_remark(remark: str) -> str:
    with _core.connect() as conn:
        cur = conn.cursor()
        cur.execute(f"\n            SELECT content\n            FROM {_core.ASSETS_TABLE}\n            WHERE type = 'voice'\n              AND remark = %s\n            ORDER BY id DESC\n            LIMIT 1\n            ", (remark,))
        row = cur.fetchone()
        return str(_core._row_value(row) or '').strip() if row else ''

def ppt_reference_voice_url(speaker: int) -> str:
    if int(speaker) == 0:
        configured = _core.os.environ.get('PPT_FEMALE_REFERENCE_VOICE_URL', '').strip()
        return configured or _core._asset_voice_url_by_remark(_core.PPT_FEMALE_REFERENCE_VOICE_REMARK)
    configured = _core.os.environ.get('PPT_MALE_REFERENCE_VOICE_URL', '').strip()
    return configured or _core._asset_voice_url_by_remark(_core.PPT_MALE_REFERENCE_VOICE_REMARK)

def list_reference_segments(task_id: str) -> list[dict[str, _core.Any]]:
    with _core.connect() as conn:
        cur = _core._dict_cursor(conn)
        try:
            cur.execute('\n                SELECT task_id, item_index, text AS src_text, start_time, end_time, speaker\n                FROM whisper_asr_segment\n                WHERE task_id = %s\n                ORDER BY item_index ASC\n                ', (task_id,))
        except _core.mysql.connector.Error as exc:
            if getattr(exc, 'errno', None) == 1146:
                return []
            raise
        rows = list(cur.fetchall())
        if rows:
            return rows
    return []
