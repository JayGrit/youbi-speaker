from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import mysql.connector

from . import video_info
from .config import MYSQL_CONFIG, SEGMENT_RUNNING_TIMEOUT_SECONDS
from .service import FAILED, READY, RUNNING, SERVICE_NAME, SERVICE_TABLE, SUCCESS

HEARTBEAT_TABLE = "service_heartbeat"
SUBMISSION_TABLE = "downloader_submission"
UPLOADER_ACCOUNT_TABLE = "uploader_account"
UPLOAD_SUBMISSION_TABLES = (
    "uploader_task_bilibili",
    "uploader_task_douyin",
    "uploader_task_xiaohongshu",
    "uploader_task_shipinhao",
    "uploader_task_kuaishou",
    "uploader_task_jinritoutiao",
)
HEARTBEAT_DEVICE_COLUMNS = ("Macbook Air M4", "Macmini M2", "LPXB", "MY_HP", "LPXB_HP", "TXY")
OPERATOR_COLUMN = "operator"
OPERATOR_COLUMN_DEFINITION = "VARCHAR(128) NULL"
_heartbeat_schema_ready = False


def _row_value(row: Any, index: int = 0) -> Any:
    if isinstance(row, Mapping):
        return list(row.values())[index]
    return row[index]


def _service_table_for(stage_name: str) -> str:
    if stage_name != SERVICE_NAME:
        raise ValueError(f"{SERVICE_NAME} service cannot handle stage: {stage_name}")
    return SERVICE_TABLE


def _staged_table_exists_cur(cur, table: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
        """,
        (table,),
    )
    row = cur.fetchone()
    return bool(row and int(_row_value(row)) > 0)


def _staged_column_exists_cur(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    row = cur.fetchone()
    return bool(row and int(_row_value(row)) > 0)


def _ensure_staged_account_columns_cur(cur) -> bool:
    if not _staged_table_exists_cur(cur, UPLOADER_ACCOUNT_TABLE):
        return False
    if not _staged_column_exists_cur(cur, UPLOADER_ACCOUNT_TABLE, "downloader_max_staged_count"):
        cur.execute(
            f"""
            ALTER TABLE {UPLOADER_ACCOUNT_TABLE}
            ADD COLUMN downloader_max_staged_count INT NOT NULL DEFAULT 5
            """
        )
    if not _staged_column_exists_cur(cur, UPLOADER_ACCOUNT_TABLE, "staged_running_count"):
        cur.execute(
            f"""
            ALTER TABLE {UPLOADER_ACCOUNT_TABLE}
            ADD COLUMN staged_running_count INT NOT NULL DEFAULT 0
            """
        )
    if not _staged_column_exists_cur(cur, UPLOADER_ACCOUNT_TABLE, "staged_failed_count"):
        cur.execute(
            f"""
            ALTER TABLE {UPLOADER_ACCOUNT_TABLE}
            ADD COLUMN staged_failed_count INT NOT NULL DEFAULT 0
            """
        )
    return True


def _task_has_upload_submission_cur(cur, task_id: str, account_key: str) -> bool:
    if not task_id or not account_key:
        return False
    for table in UPLOAD_SUBMISSION_TABLES:
        if not _staged_table_exists_cur(cur, table):
            continue
        cur.execute(
            f"""
            SELECT 1
            FROM {table}
            WHERE task_id = %s AND account_key = %s
            LIMIT 1
            """,
            (task_id, account_key),
        )
        if cur.fetchone():
            return True
    return False


def _apply_staged_pipeline_failure_cur(cur, task_id: str, old_task_status: str | None) -> None:
    if str(old_task_status or "").strip().lower() == FAILED:
        return
    if not _ensure_staged_account_columns_cur(cur) or not _staged_table_exists_cur(cur, SUBMISSION_TABLE):
        return
    cur.execute(
        f"""
        SELECT type
        FROM {SUBMISSION_TABLE}
        WHERE task_id = %s
          AND status = %s
          AND NULLIF(type, '') IS NOT NULL
        FOR UPDATE
        """,
        (task_id, SUCCESS),
    )
    row = cur.fetchone()
    account_key = str(_row_value(row) if row else "").strip()
    if not account_key or _task_has_upload_submission_cur(cur, task_id, account_key):
        return
    cur.execute(
        f"""
        UPDATE {UPLOADER_ACCOUNT_TABLE}
        SET staged_running_count = GREATEST(staged_running_count - 1, 0),
            staged_failed_count = staged_failed_count + 1,
            metrics_updated_at = NOW(),
            updated_at = NOW()
        WHERE account_key = %s
        """,
        (account_key,),
    )


SEGMENT_PENDING = "pending"
SEGMENT_READY = "ready"
SEGMENT_RUNNING = "running"
SEGMENT_SUCCESS = "success"
SEGMENT_FAILED = "failed"
TRANSLATOR_SEGMENT_TABLE = "translator_segment"
_segment_schema_ready = False
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
    return

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
        _ensure_operator_columns(cur, ("demucs",))
        cur.execute("SELECT `operator` FROM demucs WHERE task_id = %s", (task_id,))
        row = cur.fetchone()
        if not row:
            return None
        operator = row.get("operator")
        return str(operator).strip() if operator else None


def _ensure_operator_columns(cur, tables: tuple[str, ...]) -> None:
    return


def ensure_service_heartbeat_schema() -> None:
    global _heartbeat_schema_ready
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
    global _segment_schema_ready
    if _segment_schema_ready:
        return
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TRANSLATOR_SEGMENT_TABLE} (
              task_id VARCHAR(64) NOT NULL,
              item_index INT NOT NULL,
              src_text MEDIUMTEXT NULL,
              dst_text MEDIUMTEXT NOT NULL,
              src_lang VARCHAR(16) NULL,
              dst_lang VARCHAR(16) NULL,
              start_time INT NOT NULL,
              end_time INT NOT NULL,
              speaker VARCHAR(64) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (task_id, item_index)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        conn.commit()
    _segment_schema_ready = True


def initialize_ready_speaker_task() -> tuple[str, int] | None:
    ensure_speaker_segment_schema()
    with connect() as conn:
        conn.start_transaction()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT sp.task_id, vi.task_type, pn.text AS narration_text
            FROM speaker sp
            JOIN task t ON t.id = sp.task_id
            JOIN video_info vi ON vi.task_id = sp.task_id
            LEFT JOIN translator tr ON tr.task_id = sp.task_id
            LEFT JOIN product_narration pn ON pn.task_id = sp.task_id
            WHERE sp.status = %s
              AND (
                (vi.task_type = 'narration' AND NULLIF(TRIM(pn.text), '') IS NOT NULL)
                OR (vi.task_type <> 'narration' AND tr.status = %s)
              )
              AND t.status <> 'failed'
              AND NOT EXISTS (
                SELECT 1
                FROM speaker_segment seg
                WHERE seg.task_id = sp.task_id
              )
            ORDER BY sp.task_id ASC
            LIMIT 1
            FOR UPDATE
            """,
            (READY, SUCCESS),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        task_id = str(row["task_id"])
        cur = conn.cursor()
        if row.get("task_type") == "narration":
            lines = [line.strip() for line in str(row.get("narration_text") or "").splitlines() if line.strip()]
            cur.executemany(
                """
                INSERT INTO speaker_segment
                  (
                    task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,
                    start_time, end_time, speaker
                  )
                VALUES (%s, %s, %s, %s, %s, 'zh', 'zh', 0, 0, NULL)
                """,
                [
                    (task_id, item_index, SEGMENT_READY, line, line)
                    for item_index, line in enumerate(lines)
                ],
            )
            inserted = int(cur.rowcount)
            conn.commit()
            return task_id, inserted
        cur.execute(
            f"""
            INSERT INTO speaker_segment
              (
                task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,
                start_time, end_time, speaker
              )
            SELECT
              task_id, item_index, %s, src_text, dst_text, src_lang, dst_lang,
              start_time, end_time, speaker
            FROM {TRANSLATOR_SEGMENT_TABLE}
            WHERE task_id = %s
            ORDER BY item_index ASC
            """,
            (SEGMENT_READY, task_id),
        )
        inserted = int(cur.rowcount)
        conn.commit()
        return task_id, inserted

def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute("SELECT * FROM task WHERE id = %s", (task_id,))
        task = cur.fetchone()
        if not task:
            return None
        task["video_info"] = video_info.get(task_id)
        return task


def find_ready(stage_name: str) -> dict[str, Any] | None:
    table = _service_table_for(stage_name)
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT s.*
            FROM {table} s
            JOIN task t ON t.id = s.task_id
            WHERE s.status = %s
              AND t.status <> 'failed'
            ORDER BY s.task_id ASC
            LIMIT 1
            """,
            (READY,),
        )
        return video_info.merge_into(cur.fetchone())


def find_ready_speaker_segment() -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    video_info.ensure_schema()
    with connect() as conn:
        cur = _dict_cursor(conn)
        _ensure_staged_account_columns_cur(cur)
        cur.execute(
            """
            SELECT seg.*,
                   vi.task_type AS task_type,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM speaker_segment seg
            JOIN speaker sp ON sp.task_id = seg.task_id
            LEFT JOIN translator tr ON tr.task_id = seg.task_id
            JOIN task t ON t.id = seg.task_id
            JOIN video_info vi ON vi.task_id = seg.task_id
            JOIN (
                SELECT task_id,
                       COUNT(*) AS total_segments,
                       SUM(CASE WHEN status <> %s THEN 1 ELSE 0 END) AS remaining_segments
                FROM speaker_segment
                GROUP BY task_id
            ) stats ON stats.task_id = seg.task_id
            LEFT JOIN (
                SELECT submission.task_id,
                       MAX(
                           CASE
                             WHEN account.cooldown_waiting_count < account.downloader_max_staged_count
                             THEN 1
                             ELSE 0
                           END
                       ) AS has_cooldown_capacity,
                       MIN(
                           CASE
                             WHEN account.cooldown_waiting_count < account.downloader_max_staged_count
                             THEN account.cooldown_waiting_count
                             ELSE NULL
                           END
                       ) AS min_available_cooldown
                FROM downloader_submission submission
                JOIN uploader_account account ON account.account_key = submission.type
                WHERE submission.status = 'success'
                  AND NULLIF(submission.type, '') IS NOT NULL
                GROUP BY submission.task_id
            ) account_priority ON account_priority.task_id = seg.task_id
            WHERE sp.status IN (%s, %s)
              AND seg.status = %s
              AND (vi.task_type = 'narration' OR tr.status = %s)
              AND t.status <> 'failed'
            ORDER BY
              CASE WHEN tr.status = %s THEN 0 ELSE 1 END,
              CASE WHEN COALESCE(account_priority.has_cooldown_capacity, 0) = 1 THEN 0 ELSE 1 END,
              account_priority.min_available_cooldown ASC,
              CASE WHEN sp.status = %s THEN 0 ELSE 1 END,
              CASE
                WHEN sp.status = %s THEN stats.remaining_segments
                ELSE stats.total_segments
              END ASC,
              seg.task_id ASC,
              seg.item_index ASC
            LIMIT 1
            """,
            (SEGMENT_SUCCESS, READY, RUNNING, SEGMENT_READY, SUCCESS, SUCCESS, RUNNING, RUNNING),
        )
        return video_info.merge_into(cur.fetchone())


def claim_speaker_segment(segment_id: int) -> dict[str, Any] | None:
    operator = _operator_value()
    video_info.ensure_schema()
    with connect() as conn:
        cur = conn.cursor()
        _ensure_operator_columns(cur, ("speaker", "speaker_segment"))
        cur.execute(
            """
            UPDATE speaker_segment seg
            JOIN task t ON t.id = seg.task_id
            JOIN video_info vi ON vi.task_id = seg.task_id
            LEFT JOIN translator tr ON tr.task_id = seg.task_id
            SET seg.status = %s,
                seg.attempt_count = seg.attempt_count + 1,
                seg.started_at = COALESCE(seg.started_at, NOW()),
                seg.error_message = NULL,
                seg.`operator` = %s
            WHERE seg.id = %s
              AND seg.status = %s
              AND (vi.task_type = 'narration' OR tr.status = %s)
              AND t.status <> 'failed'
            """,
            (SEGMENT_RUNNING, operator, segment_id, SEGMENT_READY, SUCCESS),
        )
        if cur.rowcount != 1:
            conn.commit()
            return None

        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT seg.*,
                   vi.task_type AS task_type,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM speaker_segment seg
            JOIN speaker sp ON sp.task_id = seg.task_id
            JOIN video_info vi ON vi.task_id = seg.task_id
            WHERE seg.id = %s
            """,
            (segment_id,),
        )
        row = cur.fetchone()
        if row:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE speaker
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
                UPDATE task
                SET status = 'running',
                    current_stage = 'speaker',
                    started_at = COALESCE(started_at, NOW())
                WHERE id = %s
                """,
                (row["task_id"],),
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
            FROM speaker_segment
            WHERE task_id = %s
            ORDER BY item_index ASC
            """,
            (task_id,),
        )
        return list(cur.fetchall())


def list_reference_segments(task_id: str) -> list[dict[str, Any]]:
    with connect() as conn:
        cur = _dict_cursor(conn)
        try:
            cur.execute(
                """
                SELECT task_id, item_index, text AS src_text, start_time, end_time, speaker
                FROM asr_segment
                WHERE task_id = %s
                ORDER BY item_index ASC
                """,
                (task_id,),
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
            UPDATE speaker_segment
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
        cur.execute("SELECT attempt_count, max_attempts FROM speaker_segment WHERE id = %s", (segment_id,))
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
            UPDATE speaker_segment
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
    failed_recycle_message = "speaker failed segment recycled; retrying"
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT DISTINCT task_id
            FROM speaker_segment
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
            UPDATE speaker_segment
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
            UPDATE speaker_segment
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
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT DISTINCT seg.task_id
            FROM speaker_segment seg
            JOIN speaker sp ON sp.task_id = seg.task_id
            JOIN task t ON t.id = seg.task_id
            WHERE seg.status = %s
              AND sp.status IN (%s, %s, %s)
              AND (t.status <> 'failed' OR t.current_stage = 'speaker')
              AND (
                  seg.error_message IS NULL
                  OR seg.error_message NOT LIKE 'translator api task failed:%%'
              )
            """,
            (SEGMENT_FAILED, READY, RUNNING, FAILED),
        )
        recycled_failed_task_ids = [str(row["task_id"]) for row in cur.fetchall()]
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE speaker_segment seg
            JOIN speaker sp ON sp.task_id = seg.task_id
            JOIN task t ON t.id = seg.task_id
            SET seg.status = %s,
                seg.attempt_count = 0,
                seg.error_message = %s,
                seg.started_at = NULL,
                seg.completed_at = NULL,
                seg.`operator` = NULL
            WHERE seg.status = %s
              AND sp.status IN (%s, %s, %s)
              AND (t.status <> 'failed' OR t.current_stage = 'speaker')
              AND (
                  seg.error_message IS NULL
                  OR seg.error_message NOT LIKE 'translator api task failed:%%'
              )
            """,
            (SEGMENT_READY, failed_recycle_message, SEGMENT_FAILED, READY, RUNNING, FAILED),
        )
        recycled_failed = cur.rowcount
        if recycled_failed_task_ids:
            placeholders = ", ".join(["%s"] * len(recycled_failed_task_ids))
            cur.execute(
                f"""
                UPDATE speaker sp
                JOIN task t ON t.id = sp.task_id
                SET sp.status = %s,
                    sp.completed_at = NULL,
                    sp.error_message = NULL,
                    t.status = 'running',
                    t.current_stage = 'speaker',
                    t.completed_at = NULL,
                    t.error_message = NULL
                WHERE sp.task_id IN ({placeholders})
                  AND sp.status = %s
                  AND t.current_stage = 'speaker'
                """,
                (RUNNING, *recycled_failed_task_ids, FAILED),
            )
        conn.commit()
        return int(retried) + int(failed) + int(recycled_failed), exhausted_task_ids


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
            FROM speaker sp
            JOIN task t ON t.id = sp.task_id
            JOIN video_info vi ON vi.task_id = sp.task_id
            LEFT JOIN translator tr ON tr.task_id = sp.task_id
            WHERE sp.status IN (%s, %s)
              AND (vi.task_type = 'narration' OR tr.status = %s)
              AND t.status <> 'failed'
              {task_filter}
              AND EXISTS (
                SELECT 1 FROM speaker_segment seg
                WHERE seg.task_id = sp.task_id
              )
              AND NOT EXISTS (
                SELECT 1 FROM speaker_segment seg
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
                         FROM speaker_segment seg
                         WHERE seg.task_id = sp.task_id
                           AND seg.status = %s
                           AND seg.error_message IS NOT NULL
                           AND seg.error_message <> ''
                         ORDER BY seg.item_index ASC
                         LIMIT 1
                       ),
                       'one or more speaker segments failed'
                   ) AS error_message
            FROM speaker sp
            JOIN task t ON t.id = sp.task_id
            WHERE sp.status IN (%s, %s)
              AND t.status <> 'failed'
              {task_filter}
              AND EXISTS (
                SELECT 1 FROM speaker_segment seg
                WHERE seg.task_id = sp.task_id
                  AND seg.status = %s
              )
              AND NOT EXISTS (
                SELECT 1 FROM speaker_segment seg
                WHERE seg.task_id = sp.task_id
                  AND seg.status IN (%s, %s, %s)
              )
            ORDER BY sp.task_id ASC
            LIMIT 1
            """,
            (SEGMENT_FAILED, *params),
        )
        return cur.fetchone()


def list_successful_speaker_task_ids(task_ids: list[str]) -> set[str]:
    if not task_ids:
        return set()
    placeholders = ", ".join(["%s"] * len(task_ids))
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT task_id
            FROM speaker
            WHERE status = %s
              AND task_id IN ({placeholders})
            """,
            (SUCCESS, *task_ids),
        )
        return {str(row["task_id"]) for row in cur.fetchall()}


def mark_speaker_failed_from_segment(task_id: str, message: str) -> None:
    mark_failed(SERVICE_NAME, task_id, message)


def mark_running(stage_name: str, task_id: str) -> bool:
    table = _service_table_for(stage_name)
    operator = _operator_value()
    with connect() as conn:
        cur = conn.cursor()
        _ensure_operator_columns(cur, (table,))
        cur.execute(
            f"""
            UPDATE {table}
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
                UPDATE task
                SET status = 'running',
                    current_stage = %s,
                    started_at = COALESCE(started_at, NOW())
                WHERE id = %s
                """,
                (stage_name, task_id),
            )
        conn.commit()
        return stage_updated


def _update_stage_fields(stage_name: str, task_id: str, fields: Mapping[str, Any]) -> None:
    table = _service_table_for(stage_name)
    assignments = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values()) + [task_id]
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE {table} SET {assignments} WHERE task_id = %s", values)
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


def mark_success(stage_name: str, task_id: str, outputs: Mapping[str, Any] | None = None) -> None:
    table = _service_table_for(stage_name)
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
        cur.execute("SELECT status FROM task WHERE id = %s", (task_id,))
        task_row = cur.fetchone()
        if not task_row or task_row[0] == "failed":
            conn.commit()
            return
        video_info.upsert(task_id, fields, cur)
        cur.execute(
            f"UPDATE {table} SET {', '.join(assignments)} WHERE task_id = %s",
            values,
        )
        conn.commit()


def mark_failed(stage_name: str, task_id: str, message: str) -> None:
    table = _service_table_for(stage_name)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status FROM task WHERE id = %s FOR UPDATE", (task_id,))
        task_row = cur.fetchone()
        old_task_status = _row_value(task_row) if task_row else None
        cur.execute(
            f"""
            UPDATE {table}
            SET status = %s, error_message = %s, completed_at = NOW()
            WHERE task_id = %s
            """,
            (FAILED, message, task_id),
        )
        cur.execute(
            """
            UPDATE task
            SET status = 'failed', current_stage = %s, error_message = %s, completed_at = NOW()
            WHERE id = %s
            """,
            (stage_name, message, task_id),
        )
        _apply_staged_pipeline_failure_cur(cur, task_id, old_task_status)
        conn.commit()
