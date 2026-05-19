from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import mysql.connector

from . import video_info
from .config import MYSQL_CONFIG, SEGMENT_RUNNING_TIMEOUT_SECONDS
from .stages import FAILED, READY, RUNNING, SUCCESS, stage_for

HEARTBEAT_TABLE = "yd_service_heartbeat"
HEARTBEAT_DEVICE_COLUMNS = ("Macbook Air M4", "Macmini M2", "LPXB", "MY_HP", "LPXB_HP", "TXY")
OPERATOR_COLUMN = "operator"
OPERATOR_COLUMN_DEFINITION = "VARCHAR(128) NULL"
_heartbeat_schema_ready = False


def _row_value(row: Any, index: int = 0) -> Any:
    if isinstance(row, Mapping):
        return list(row.values())[index]
    return row[index]
SEGMENT_PENDING = "pending"
SEGMENT_READY = "ready"
SEGMENT_RUNNING = "running"
SEGMENT_SUCCESS = "success"
SEGMENT_FAILED = "failed"
SPEAKER_SEGMENT_EXTRA_COLUMNS = {
    "reference_wav_url": "TEXT",
    "tts_wav_url": "TEXT",
    "actual_start_time": "INT",
    "actual_end_time": "INT",
    "speed_ratio": "DOUBLE",
}


def connect():
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    return conn


def _dict_cursor(conn):
    return conn.cursor(dictionary=True)


def _quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _ensure_columns(cur, table: str, columns: Mapping[str, str]) -> None:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = %s
        """,
        (table,),
    )
    existing = {_row_value(row) for row in cur.fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def _heartbeat_device_column() -> str | None:
    device = os.environ.get("DEVICE", "").strip() or "Macbook Air M4"
    return device if device in HEARTBEAT_DEVICE_COLUMNS else None


def _operator_value() -> str:
    return os.environ.get("DEVICE", "").strip() or "Macbook Air M4"


def current_operator() -> str:
    return _operator_value()


def demucs_operator_for(task_id: str) -> str | None:
    with connect() as conn:
        cur = _dict_cursor(conn)
        _ensure_operator_columns(cur, ("yd_demucs",))
        cur.execute("SELECT `operator` FROM yd_demucs WHERE task_id = %s", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        operator = row.get("operator")
        return str(operator).strip() if operator else None


def _ensure_operator_columns(cur, tables: tuple[str, ...]) -> None:
    for table in tables:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            (table,),
        )
        if _row_value(cur.fetchone()) == 0:
            continue

        cur.execute(
            """
            SELECT COUNT(*)
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
            """,
            (table, OPERATOR_COLUMN),
        )
        if _row_value(cur.fetchone()) > 0:
            continue

        try:
            cur.execute(
                f"ALTER TABLE {_quote_identifier(table)} "
                f"ADD COLUMN {_quote_identifier(OPERATOR_COLUMN)} {OPERATOR_COLUMN_DEFINITION}"
            )
        except mysql.connector.Error as exc:
            if getattr(exc, "errno", None) != 1060:
                raise


def ensure_service_heartbeat_schema() -> None:
    global _heartbeat_schema_ready
    if _heartbeat_schema_ready:
        return

    columns_sql = ",\n                ".join(
        f"{_quote_identifier(column)} DATETIME NULL" for column in HEARTBEAT_DEVICE_COLUMNS
    )
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {HEARTBEAT_TABLE} (
                service_name VARCHAR(64) NOT NULL PRIMARY KEY,
                {columns_sql},
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
            """,
            (HEARTBEAT_TABLE,),
        )
        existing = {_row_value(row) for row in cur.fetchall()}
        for column in HEARTBEAT_DEVICE_COLUMNS:
            if column not in existing:
                try:
                    cur.execute(f"ALTER TABLE {HEARTBEAT_TABLE} ADD COLUMN {_quote_identifier(column)} DATETIME NULL")
                except mysql.connector.Error as exc:
                    if getattr(exc, "errno", None) != 1060:
                        raise
        conn.commit()
    _heartbeat_schema_ready = True


def record_service_poll(stage_name: str) -> None:
    column = _heartbeat_device_column()
    if not column:
        return

    ensure_service_heartbeat_schema()
    quoted_column = _quote_identifier(column)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO {HEARTBEAT_TABLE} (service_name, {quoted_column})
            VALUES (%s, NOW())
            ON DUPLICATE KEY UPDATE {quoted_column} = VALUES({quoted_column})
            """,
            (stage_name,),
        )
        conn.commit()


def ensure_speaker_segment_schema() -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS yd_speaker_segment (
              id BIGINT PRIMARY KEY AUTO_INCREMENT,
              task_id VARCHAR(64) NOT NULL,
              item_index INT NOT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'pending',
              src_text MEDIUMTEXT,
              dst_text MEDIUMTEXT NOT NULL,
              src_lang VARCHAR(16),
              dst_lang VARCHAR(16),
              start_time INT NOT NULL,
              end_time INT NOT NULL,
              speaker VARCHAR(64),
              reference_wav_path TEXT,
              reference_wav_url TEXT,
              tts_wav_path TEXT,
              tts_wav_url TEXT,
              actual_start_time INT,
              actual_end_time INT,
              speed_ratio DOUBLE,
              attempt_count INT NOT NULL DEFAULT 0,
              max_attempts INT NOT NULL DEFAULT 3,
              error_message TEXT,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              started_at DATETIME,
              completed_at DATETIME,
              `operator` VARCHAR(128),
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uk_speaker_segment (task_id, item_index),
              KEY idx_speaker_segment_ready (status, task_id, item_index)
            )
            """
        )
        _ensure_columns(cur, "yd_speaker_segment", SPEAKER_SEGMENT_EXTRA_COLUMNS)
        _ensure_operator_columns(cur, ("yd_speaker_segment",))
        conn.commit()


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute("SELECT * FROM yd_task WHERE id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            return None
        task["video_info"] = video_info.get(task_id)
        return task


def find_ready(stage_name: str) -> dict[str, Any] | None:
    stage = stage_for(stage_name)
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"SELECT * FROM {stage.table} WHERE status = %s ORDER BY task_id ASC LIMIT 1",
            (READY,),
        )
        return video_info.merge_into(cur.fetchone())


def find_ready_speaker_segment() -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    video_info.ensure_schema()
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT seg.*,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM yd_speaker_segment seg
            JOIN yd_speaker sp ON sp.task_id = seg.task_id
            JOIN yd_video_info vi ON vi.task_id = seg.task_id
            JOIN (
                SELECT task_id,
                       COUNT(*) AS total_segments,
                       SUM(CASE WHEN status <> %s THEN 1 ELSE 0 END) AS remaining_segments
                FROM yd_speaker_segment
                GROUP BY task_id
            ) stats ON stats.task_id = seg.task_id
            WHERE sp.status IN (%s, %s)
              AND seg.status = %s
            ORDER BY
              CASE WHEN sp.status = %s THEN 0 ELSE 1 END,
              CASE
                WHEN sp.status = %s THEN stats.remaining_segments
                ELSE stats.total_segments
              END ASC,
              seg.task_id ASC,
              seg.item_index ASC
            LIMIT 1
            """,
            (SEGMENT_SUCCESS, READY, RUNNING, SEGMENT_READY, RUNNING, RUNNING),
        )
        return video_info.merge_into(cur.fetchone())


def claim_speaker_segment(segment_id: int) -> dict[str, Any] | None:
    operator = _operator_value()
    video_info.ensure_schema()
    with connect() as conn:
        cur = conn.cursor()
        _ensure_operator_columns(cur, ("yd_task", "yd_speaker", "yd_speaker_segment"))
        cur.execute(
            """
            UPDATE yd_speaker_segment
            SET status = %s,
                attempt_count = attempt_count + 1,
                started_at = COALESCE(started_at, NOW()),
                error_message = NULL,
                `operator` = %s
            WHERE id = %s AND status = %s
            """,
            (SEGMENT_RUNNING, operator, segment_id, SEGMENT_READY),
        )
        if cur.rowcount != 1:
            conn.commit()
            return None

        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT seg.*,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM yd_speaker_segment seg
            JOIN yd_speaker sp ON sp.task_id = seg.task_id
            JOIN yd_video_info vi ON vi.task_id = seg.task_id
            WHERE seg.id = %s
            """,
            (segment_id,),
        )
        row = cur.fetchone()
        if row:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE yd_speaker
                SET status = %s,
                    started_at = COALESCE(started_at, NOW()),
                    error_message = NULL,
                    `operator` = %s
                WHERE task_id = %s AND status = %s
                """,
                (RUNNING, operator, row["task_id"], READY),
            )
            cur.execute(
                """
                UPDATE yd_task
                SET status = 'running',
                    current_stage = 'speaker',
                    started_at = COALESCE(started_at, NOW()),
                    `operator` = %s
                WHERE id = %s
                """,
                (operator, row["task_id"]),
            )
        conn.commit()
        return video_info.merge_into(row)


def list_speaker_segments(task_id: str) -> list[dict[str, Any]]:
    ensure_speaker_segment_schema()
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT id, task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,
                   start_time, end_time, speaker, reference_wav_path, reference_wav_url,
                   tts_wav_path, tts_wav_url
            FROM yd_speaker_segment
            WHERE task_id = %s
            ORDER BY item_index ASC
            """,
            (task_id,),
        )
        return list(cur.fetchall())


def list_reference_segments(task_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = _dict_cursor(conn)
        for segment_type in ("fixed", "raw"):
            try:
                cur.execute(
                    """
                    SELECT task_id, item_index, text AS src_text, start_time, end_time, speaker
                    FROM yd_asr_segment
                    WHERE task_id = %s AND segment_type = %s
                    ORDER BY item_index ASC
                    """,
                    (task_id, segment_type),
                )
            except mysql.connector.Error as exc:
                if getattr(exc, "errno", None) == 1146:
                    return []
                raise
            rows = list(cur.fetchall())
            if rows:
                return rows
    return []


def mark_speaker_segment_success(
    segment_id: int,
    reference_wav_path: str,
    reference_wav_url: str,
    tts_wav_path: str,
    tts_wav_url: str,
) -> None:
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE yd_speaker_segment
            SET status = %s,
                reference_wav_path = %s,
                reference_wav_url = %s,
                tts_wav_path = %s,
                tts_wav_url = %s,
                completed_at = NOW(),
                error_message = NULL
            WHERE id = %s
            """,
            (SEGMENT_SUCCESS, reference_wav_path, reference_wav_url, tts_wav_path, tts_wav_url, segment_id),
        )
        conn.commit()


def mark_speaker_segment_failed(segment_id: int, message: str) -> bool:
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute("SELECT attempt_count, max_attempts FROM yd_speaker_segment WHERE id = %s", (segment_id,))
        row = cur.fetchone()
        if not row:
            conn.commit()
            return True
        exhausted = int(row["attempt_count"]) >= int(row["max_attempts"])
        status = SEGMENT_FAILED if exhausted else SEGMENT_READY
        completed_at = "NOW()" if exhausted else "NULL"
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE yd_speaker_segment
            SET status = %s,
                error_message = %s,
                completed_at = {completed_at}
            WHERE id = %s
            """,
            (status, message, segment_id),
        )
        conn.commit()
        return exhausted


def recycle_stale_speaker_segments() -> tuple[int, list[str]]:
    timeout_seconds = SEGMENT_RUNNING_TIMEOUT_SECONDS
    message = f"speaker segment timed out after {timeout_seconds}s; retrying"
    exhausted_message = f"speaker segment timed out after {timeout_seconds}s; max attempts exhausted"
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT DISTINCT task_id
            FROM yd_speaker_segment
            WHERE status = %s
              AND attempt_count >= max_attempts
              AND started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, started_at, NOW()) > %s
            """,
            (SEGMENT_RUNNING, timeout_seconds),
        )
        exhausted_task_ids = [str(row["task_id"]) for row in cur.fetchall()]

        cur = conn.cursor()
        cur.execute(
            """
            UPDATE yd_speaker_segment
            SET status = %s,
                error_message = %s,
                started_at = NULL,
                completed_at = NULL,
                `operator` = NULL
            WHERE status = %s
              AND attempt_count < max_attempts
              AND started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, started_at, NOW()) > %s
            """,
            (SEGMENT_READY, message, SEGMENT_RUNNING, timeout_seconds),
        )
        retried = cur.rowcount
        cur.execute(
            """
            UPDATE yd_speaker_segment
            SET status = %s,
                error_message = %s,
                completed_at = NOW()
            WHERE status = %s
              AND attempt_count >= max_attempts
              AND started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, started_at, NOW()) > %s
            """,
            (SEGMENT_FAILED, exhausted_message, SEGMENT_RUNNING, timeout_seconds),
        )
        failed = cur.rowcount
        conn.commit()
        return int(retried) + int(failed), exhausted_task_ids


def find_finalizable_speaker_task(task_id: str | None = None) -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    task_filter = "AND sp.task_id = %s" if task_id is not None else ""
    params: list[Any] = [READY, RUNNING, SUCCESS]
    if task_id is not None:
        params.append(task_id)
    params.append(SEGMENT_SUCCESS)
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT sp.*
            FROM yd_speaker sp
            JOIN yd_translator tr ON tr.task_id = sp.task_id
            WHERE sp.status IN (%s, %s)
              AND tr.status = %s
              {task_filter}
              AND EXISTS (
                SELECT 1 FROM yd_speaker_segment seg
                WHERE seg.task_id = sp.task_id
              )
              AND NOT EXISTS (
                SELECT 1 FROM yd_speaker_segment seg
                WHERE seg.task_id = sp.task_id
                  AND seg.status <> %s
              )
            ORDER BY sp.task_id ASC
            LIMIT 1
            """,
            params,
        )
        return video_info.merge_into(cur.fetchone())


def find_terminal_failed_speaker_task(task_id: str | None = None) -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    task_filter = "AND sp.task_id = %s" if task_id is not None else ""
    params: list[Any] = [READY, RUNNING]
    if task_id is not None:
        params.append(task_id)
    params.extend([SEGMENT_FAILED, SEGMENT_PENDING, SEGMENT_READY, SEGMENT_RUNNING])
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT sp.task_id,
                   COALESCE(
                       (
                         SELECT seg.error_message
                         FROM yd_speaker_segment seg
                         WHERE seg.task_id = sp.task_id
                           AND seg.status = %s
                           AND seg.error_message IS NOT NULL
                           AND seg.error_message <> ''
                         ORDER BY seg.item_index ASC
                         LIMIT 1
                       ),
                       'one or more speaker segments failed'
                   ) AS error_message
            FROM yd_speaker sp
            WHERE sp.status IN (%s, %s)
              {task_filter}
              AND EXISTS (
                SELECT 1 FROM yd_speaker_segment seg
                WHERE seg.task_id = sp.task_id
                  AND seg.status = %s
              )
              AND NOT EXISTS (
                SELECT 1 FROM yd_speaker_segment seg
                WHERE seg.task_id = sp.task_id
                  AND seg.status IN (%s, %s, %s)
              )
            ORDER BY sp.task_id ASC
            LIMIT 1
            """,
            (SEGMENT_FAILED, *params),
        )
        return cur.fetchone()


def mark_speaker_failed_from_segment(task_id: str, message: str) -> None:
    mark_failed("speaker", task_id, message)


def mark_running(stage_name: str, task_id: str) -> bool:
    stage = stage_for(stage_name)
    operator = _operator_value()
    with connect() as conn:
        cur = conn.cursor()
        _ensure_operator_columns(cur, ("yd_task", stage.table))
        cur.execute(
            f"""
            UPDATE {stage.table}
            SET status = %s,
                started_at = COALESCE(started_at, NOW()),
                error_message = NULL,
                `operator` = %s
            WHERE task_id = %s AND status = %s
            """,
            (RUNNING, operator, task_id, READY),
        )
        stage_updated = cur.rowcount == 1
        if stage_updated:
            cur.execute(
                """
                UPDATE yd_task
                SET status = 'running',
                    current_stage = %s,
                    started_at = COALESCE(started_at, NOW()),
                    `operator` = %s
                WHERE id = %s
                """,
                (stage_name, operator, task_id),
            )
        conn.commit()
        return stage_updated


def _update_stage_fields(stage_name: str, task_id: str, fields: Mapping[str, Any]) -> None:
    stage = stage_for(stage_name)
    assignments = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values()) + [task_id]
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE {stage.table} SET {assignments} WHERE task_id = %s", values)
        conn.commit()


def set_combiner_speaker_inputs(
    task_id: str,
    translation_json_path: str,
    tts_segments_dir: str,
) -> None:
    video_info.upsert(
        task_id,
        {
            "translation_json_path": translation_json_path,
            "tts_segments_dir": tts_segments_dir,
        },
    )


def session_path_for(task_id: str) -> Path:
    task = get_task(task_id)
    if not task:
        raise RuntimeError(f"Task not found: {task_id}")
    info = task.get("video_info") or {}
    session_path = info.get("session_path")
    if not session_path:
        raise RuntimeError(f"Task missing downloader session_path: {task_id}")
    return Path(session_path)


def mark_success(stage_name: str, task_id: str, outputs: Mapping[str, Any] | None = None) -> None:
    stage = stage_for(stage_name)
    fields = dict(outputs or {})
    stage_fields = {key: value for key, value in fields.items() if key not in video_info.COLUMNS}
    assignments = ["status = %s", "completed_at = NOW()", "error_message = NULL"]
    values: list[Any] = [SUCCESS]
    for key, value in stage_fields.items():
        assignments.append(f"{key} = %s")
        values.append(value)
    values.append(task_id)

    with connect() as conn:
        cur = conn.cursor()
        video_info.upsert(task_id, fields, cur)
        cur.execute(
            f"UPDATE {stage.table} SET {', '.join(assignments)} WHERE task_id = %s",
            values,
        )
        if stage.next_table:
            cur.execute(
                f"UPDATE {stage.next_table} SET status = %s WHERE task_id = %s AND status = 'pending'",
                (READY, task_id),
            )
            cur.execute(
                "UPDATE yd_task SET current_stage = %s WHERE id = %s",
                (stage.next_name, task_id),
            )
        else:
            cur.execute(
                """
                UPDATE yd_task
                SET status = 'success', current_stage = 'done', completed_at = NOW(), error_message = NULL
                WHERE id = %s
                """,
                (task_id,),
            )
        conn.commit()


def mark_failed(stage_name: str, task_id: str, message: str) -> None:
    stage = stage_for(stage_name)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE {stage.table}
            SET status = %s, error_message = %s, completed_at = NOW()
            WHERE task_id = %s
            """,
            (FAILED, message, task_id),
        )
        cur.execute(
            """
            UPDATE yd_task
            SET status = 'failed', current_stage = %s, error_message = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (stage_name, message, task_id),
        )
        conn.commit()
