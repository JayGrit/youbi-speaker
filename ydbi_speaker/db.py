from __future__ import annotations

import os
import json
from collections.abc import Mapping
from typing import Any

import mysql.connector

from . import video_info
from .config import (
    MYSQL_CONFIG,
    NARRATION_SEGMENT_RUNNING_TIMEOUT_SECONDS,
    SEGMENT_RUNNING_TIMEOUT_SECONDS,
)
from .service import FAILED, READY, RUNNING, SERVICE_NAME, SERVICE_TABLE, SUCCESS

HEARTBEAT_TABLE = "service_heartbeat"
SUBMISSION_TABLE = "downloader_submission"
UPLOADER_ACCOUNT_TABLE = "uploader_account"
UPLOAD_SUBMISSION_TABLES = (
    "uploader_task",
)
HEARTBEAT_DEVICE_COLUMNS = ("Macbook Air M4", "Macmini M2", "LPXB", "MY_HP", "LPXB_HP", "TXY")
PRODUCT_NARRATION_SENTENCE_TABLE = "product_narration_sentence"
MAX_NARRATION_SEGMENT_CHARS = 500
OPERATOR_COLUMN = "operator"
OPERATOR_COLUMN_DEFINITION = "VARCHAR(128) NULL"
_heartbeat_schema_ready = False
_speaker_stage_schema_ready = False
READY_SPEAKER_SEGMENT_CANDIDATE_LIMIT = 2000


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


def _index_exists_cur(cur, table: str, index_name: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND INDEX_NAME = %s
        """,
        (table, index_name),
    )
    row = cur.fetchone()
    return bool(row and int(_row_value(row)) > 0)


def _ensure_index_cur(cur, table: str, index_name: str, columns_sql: str) -> None:
    if not _staged_table_exists_cur(cur, table):
        return
    if _index_exists_cur(cur, table, index_name):
        return
    cur.execute(f"CREATE INDEX {index_name} ON {_quote_identifier(table)} ({columns_sql})")


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
    return


SEGMENT_PENDING = "pending"
SEGMENT_READY = "ready"
SEGMENT_RUNNING = "running"
SEGMENT_SUCCESS = "success"
SEGMENT_FAILED = "failed"
TRANSLATOR_SEGMENT_TABLE = "translator_segment"
TRANSLATOR_CHUNK_TABLE = "translator-chunk"
_segment_schema_ready = False
_profile_schema_ready = False
SPEAKER_VOICE_PROFILE_TABLE = "speaker_voice_profile"
SPEAKER_SEGMENT_SIMILARITY_TABLE = "speaker_segment_similarity"
SPEAKER_SEGMENT_EXTRA_COLUMNS = {
    "reference_wav_url": "TEXT",
    "tts_wav_url": "TEXT",
    "actual_start_time": "INT",
    "actual_end_time": "INT",
    "speed_ratio": "DOUBLE",
}
SPEAKER_MAIN_SUB_STAGE = "main"
SPEAKER_NARRATION_SUB_STAGE = "narration"
SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE = "dubbing_multi_segment"
TASK_TYPE_DUBBING_MULTI_SEGMENT = "dubbing_multi_segment"
TASK_TYPE_DUBBING_CHUNK_ALIGNED = "dubbing_chunk_aligned"
CHUNK_SPEAKER_TASK_TYPES = (
    TASK_TYPE_DUBBING_MULTI_SEGMENT,
    TASK_TYPE_DUBBING_CHUNK_ALIGNED,
)
CHUNK_SPEAKER_TASK_TYPE_PLACEHOLDERS = ", ".join(["%s"] * len(CHUNK_SPEAKER_TASK_TYPES))


def connect():
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    return conn


def _dict_cursor(conn):
    return conn.cursor(dictionary=True)


def _quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def _ensure_columns(cur, table: str, columns: Mapping[str, str]) -> None:
    if not _staged_table_exists_cur(cur, table):
        return
    for column, definition in columns.items():
        if _staged_column_exists_cur(cur, table, column):
            continue
        cur.execute(f"ALTER TABLE {_quote_identifier(table)} ADD COLUMN {_quote_identifier(column)} {definition}")


def ensure_speaker_stage_schema() -> None:
    global _speaker_stage_schema_ready
    if _speaker_stage_schema_ready:
        return
    with connect() as conn:
        cur = conn.cursor()
        _ensure_speaker_stage_schema_cur(cur)
        conn.commit()
    _speaker_stage_schema_ready = True


def _ensure_speaker_stage_schema_cur(cur) -> None:
    cur.execute(
        """
        UPDATE distributor_task_stages sp
        JOIN video_info vi ON vi.task_id = sp.task_id
        SET sp.sub_stage = %s
        WHERE sp.stage_name = 'speaker'
          AND vi.task_type = 'narration'
          AND sp.sub_stage = %s
        """,
        (SPEAKER_NARRATION_SUB_STAGE, SPEAKER_MAIN_SUB_STAGE),
    )
    cur.execute(
        """
        UPDATE distributor_task_stages sp
        JOIN video_info vi ON vi.task_id = sp.task_id
        SET sp.sub_stage = %s
        WHERE sp.stage_name = 'speaker'
          AND vi.task_type IN (%s, %s)
          AND sp.sub_stage = %s
        """,
        (
            SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
            *CHUNK_SPEAKER_TASK_TYPES,
            SPEAKER_MAIN_SUB_STAGE,
        ),
    )

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
        cur.execute(
            """
            SELECT `operator`
            FROM distributor_task_stages
            WHERE task_id = %s AND stage_name = 'demucs' AND sub_stage = 'main'
            """,
            (task_id,),
        )
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
        _ensure_speaker_stage_schema_cur(cur)
        _ensure_speaker_profile_schema_cur(cur)
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
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PRODUCT_NARRATION_SENTENCE_TABLE} (
              id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
              narration_id BIGINT UNSIGNED NOT NULL,
              task_id VARCHAR(64) NOT NULL,
              line_index INT UNSIGNED NOT NULL,
              sentence_text TEXT NOT NULL,
              segment_index INT UNSIGNED NOT NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              UNIQUE KEY uk_product_narration_sentence_line (task_id, line_index),
              KEY idx_product_narration_sentence_segment (task_id, segment_index, line_index),
              CONSTRAINT fk_product_narration_sentence_narration
                FOREIGN KEY (narration_id) REFERENCES product_narration (id)
                ON UPDATE CASCADE ON DELETE CASCADE,
              CONSTRAINT fk_product_narration_sentence_task
                FOREIGN KEY (task_id) REFERENCES task (id)
                ON UPDATE CASCADE ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        _ensure_index_cur(
            cur,
            "speaker_segment",
            "idx_speaker_segment_status_task_item",
            "`status`, `task_id`, `item_index`",
        )
        _ensure_index_cur(
            cur,
            SERVICE_TABLE,
            "idx_speaker_status_task_substage",
            "`status`, `task_id`, `sub_stage`",
        )
        _ensure_index_cur(
            cur,
            "translator",
            "idx_translator_task_status",
            "`task_id`, `status`",
        )
        _ensure_index_cur(
            cur,
            SUBMISSION_TABLE,
            "idx_downloader_submission_status_type_task",
            "`status`, `type`, `task_id`",
        )
        _ensure_index_cur(
            cur,
            "uploader_task",
            "idx_uploader_task_account_status",
            "`account_key`, `status`",
        )
        conn.commit()
    _segment_schema_ready = True


def ensure_speaker_profile_schema() -> None:
    global _profile_schema_ready
    if _profile_schema_ready:
        return
    with connect() as conn:
        cur = conn.cursor()
        _ensure_speaker_profile_schema_cur(cur)
        conn.commit()
    _profile_schema_ready = True


def _ensure_speaker_profile_schema_cur(cur) -> None:
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SPEAKER_VOICE_PROFILE_TABLE} (
          task_id VARCHAR(64) NOT NULL,
          sub_stage VARCHAR(64) NOT NULL,
          profile_version INT NOT NULL,
          reference_item_index INT NULL,
          reference_text MEDIUMTEXT NULL,
          reference_wav_url TEXT NULL,
          reference_embedding_url TEXT NULL,
          generation_options_json JSON NULL,
          similarity_threshold DOUBLE NULL,
          status VARCHAR(32) NOT NULL DEFAULT 'ready',
          error_message TEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          PRIMARY KEY (task_id, sub_stage)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SPEAKER_SEGMENT_SIMILARITY_TABLE} (
          task_id VARCHAR(64) NOT NULL,
          segment_id BIGINT UNSIGNED NULL,
          item_index INT NOT NULL,
          sub_stage VARCHAR(64) NOT NULL,
          reference_embedding_url TEXT NULL,
          generated_embedding_url TEXT NULL,
          similarity_score DOUBLE NULL,
          threshold DOUBLE NULL,
          passed TINYINT(1) NULL,
          metrics_json JSON NULL,
          error_message TEXT NULL,
          created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          UNIQUE KEY uk_speaker_segment_similarity_task_item_stage (task_id, item_index, sub_stage)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
    )


def get_voice_profile(task_id: str, sub_stage: str) -> dict[str, Any] | None:
    ensure_speaker_profile_schema()
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT task_id, sub_stage, profile_version, reference_item_index, reference_text,
                   reference_wav_url, reference_embedding_url, generation_options_json,
                   similarity_threshold, status, error_message
            FROM {SPEAKER_VOICE_PROFILE_TABLE}
            WHERE task_id = %s AND sub_stage = %s
            """,
            (task_id, sub_stage),
        )
        return cur.fetchone()


def upsert_voice_profile(
    *,
    task_id: str,
    sub_stage: str,
    profile_version: int,
    reference_item_index: int | None,
    reference_text: str | None,
    reference_wav_url: str | None,
    reference_embedding_url: str | None,
    generation_options: Mapping[str, Any] | None,
    similarity_threshold: float | None,
    status: str = "ready",
    error_message: str | None = None,
) -> None:
    ensure_speaker_profile_schema()
    generation_options_json = json.dumps(generation_options, ensure_ascii=False) if generation_options is not None else None
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO {SPEAKER_VOICE_PROFILE_TABLE}
              (
                task_id, sub_stage, profile_version, reference_item_index, reference_text,
                reference_wav_url, reference_embedding_url, generation_options_json,
                similarity_threshold, status, error_message
              )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              profile_version = VALUES(profile_version),
              reference_item_index = VALUES(reference_item_index),
              reference_text = VALUES(reference_text),
              reference_wav_url = VALUES(reference_wav_url),
              reference_embedding_url = VALUES(reference_embedding_url),
              generation_options_json = VALUES(generation_options_json),
              similarity_threshold = VALUES(similarity_threshold),
              status = VALUES(status),
              error_message = VALUES(error_message)
            """,
            (
                task_id,
                sub_stage,
                profile_version,
                reference_item_index,
                reference_text,
                reference_wav_url,
                reference_embedding_url,
                generation_options_json,
                similarity_threshold,
                status,
                error_message,
            ),
        )
        conn.commit()


def upsert_segment_similarity(
    *,
    task_id: str,
    segment_id: int | None,
    item_index: int,
    sub_stage: str,
    reference_embedding_url: str | None,
    generated_embedding_url: str | None,
    similarity_score: float | None,
    threshold: float | None,
    passed: bool | None,
    metrics: Mapping[str, Any] | None,
    error_message: str | None = None,
) -> None:
    ensure_speaker_profile_schema()
    metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics is not None else None
    passed_value = None if passed is None else int(passed)
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            INSERT INTO {SPEAKER_SEGMENT_SIMILARITY_TABLE}
              (
                task_id, segment_id, item_index, sub_stage, reference_embedding_url,
                generated_embedding_url, similarity_score, threshold, passed,
                metrics_json, error_message
              )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              segment_id = VALUES(segment_id),
              reference_embedding_url = VALUES(reference_embedding_url),
              generated_embedding_url = VALUES(generated_embedding_url),
              similarity_score = VALUES(similarity_score),
              threshold = VALUES(threshold),
              passed = VALUES(passed),
              metrics_json = VALUES(metrics_json),
              error_message = VALUES(error_message)
            """,
            (
                task_id,
                segment_id,
                item_index,
                sub_stage,
                reference_embedding_url,
                generated_embedding_url,
                similarity_score,
                threshold,
                passed_value,
                metrics_json,
                error_message,
            ),
        )
        conn.commit()


def _build_narration_segments(sentence_rows: list[dict[str, Any]]) -> list[str]:
    if not sentence_rows:
        raise ValueError("narration sentence rows are required")
    segments: list[str] = []
    current_segment_index = 1
    current_lines: list[str] = []
    expected_line_index = 1
    for row in sentence_rows:
        line_index = int(row["line_index"])
        segment_index = int(row["segment_index"])
        sentence_text = str(row.get("sentence_text") or "").strip()
        if line_index != expected_line_index:
            raise ValueError(f"narration sentence line index is not contiguous at {line_index}")
        if not sentence_text:
            raise ValueError(f"narration sentence {line_index} is empty")
        allowed_segment_indexes = (
            {current_segment_index}
            if not current_lines
            else {current_segment_index, current_segment_index + 1}
        )
        if segment_index not in allowed_segment_indexes:
            raise ValueError(f"narration segment index is not contiguous at line {line_index}")
        if segment_index == current_segment_index + 1:
            segment_text = "\n".join(current_lines)
            if len(segment_text) > MAX_NARRATION_SEGMENT_CHARS:
                raise ValueError(f"narration segment {current_segment_index} exceeds 500 characters")
            segments.append(segment_text)
            current_segment_index = segment_index
            current_lines = []
        current_lines.append(sentence_text)
        expected_line_index += 1
    segment_text = "\n".join(current_lines)
    if len(segment_text) > MAX_NARRATION_SEGMENT_CHARS:
        raise ValueError(f"narration segment {current_segment_index} exceeds 500 characters")
    segments.append(segment_text)
    return segments


def initialize_ready_speaker_task() -> tuple[str, int] | None:
    ensure_speaker_segment_schema()
    with connect() as conn:
        conn.start_transaction()
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT sp.task_id, sp.sub_stage, vi.task_type
            FROM distributor_task_stages sp
            JOIN task t ON t.id = sp.task_id
            JOIN video_info vi ON vi.task_id = sp.task_id
            LEFT JOIN distributor_task_stages tr ON tr.task_id = sp.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'
            WHERE sp.stage_name = 'speaker'
              AND sp.status = %s
              AND (
                (
                  sp.sub_stage = %s
                  AND vi.task_type = 'narration'
                  AND EXISTS (
                    SELECT 1
                    FROM product_narration_sentence narration_sentence
                    WHERE narration_sentence.task_id = sp.task_id
                  )
                )
                OR (
                  sp.sub_stage = %s
                  AND vi.task_type IN (%s, %s)
                  AND tr.status = %s
                )
                OR (
                  sp.sub_stage = %s
                  AND vi.task_type <> 'narration'
                  AND vi.task_type NOT IN (%s, %s)
                  AND tr.status = %s
                )
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
            (
                READY,
                SPEAKER_NARRATION_SUB_STAGE,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
                SPEAKER_MAIN_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
            ),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        task_id = str(row["task_id"])
        cur = conn.cursor()
        if row.get("sub_stage") == SPEAKER_NARRATION_SUB_STAGE:
            sentence_cur = _dict_cursor(conn)
            sentence_cur.execute(
                f"""
                SELECT line_index, sentence_text, segment_index
                FROM {PRODUCT_NARRATION_SENTENCE_TABLE}
                WHERE task_id = %s
                ORDER BY line_index ASC
                """,
                (task_id,),
            )
            segments = _build_narration_segments(list(sentence_cur.fetchall()))
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
                    (task_id, item_index, SEGMENT_READY, segment_text, segment_text)
                    for item_index, segment_text in enumerate(segments)
                ],
            )
            inserted = int(cur.rowcount)
            conn.commit()
            return task_id, inserted
        if row.get("sub_stage") == SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE:
            chunk_table = _quote_identifier(TRANSLATOR_CHUNK_TABLE)
            cur.execute(
                f"""
                INSERT INTO speaker_segment
                  (
                    task_id, item_index, status, src_text, dst_text, src_lang, dst_lang,
                    start_time, end_time, speaker
                  )
                SELECT
                  tc.task_id,
                  tc.chunk_index AS item_index,
                  %s AS status,
                  COALESCE(GROUP_CONCAT(NULLIF(TRIM(COALESCE(ts.src_text, tc.text)), '') ORDER BY tc.row_order SEPARATOR '\\n'), '') AS src_text,
                  COALESCE(GROUP_CONCAT(NULLIF(TRIM(ts.dst_text), '') ORDER BY tc.row_order SEPARATOR '\\n'), '') AS dst_text,
                  MIN(ts.src_lang) AS src_lang,
                  MAX(ts.dst_lang) AS dst_lang,
                  MIN(tc.chunk_start_time) AS start_time,
                  MAX(tc.chunk_end_time) AS end_time,
                  SUBSTRING_INDEX(GROUP_CONCAT(NULLIF(ts.speaker, '') ORDER BY tc.row_order SEPARATOR ','), ',', 1) AS speaker
                FROM {chunk_table} tc
                JOIN {TRANSLATOR_SEGMENT_TABLE} ts
                  ON ts.task_id = tc.task_id
                 AND ts.item_index = tc.item_index
                WHERE tc.task_id = %s
                  AND tc.row_role = 'normal'
                GROUP BY tc.task_id, tc.chunk_index
                ORDER BY tc.chunk_index ASC
                """,
                (SEGMENT_READY, task_id),
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
            WHERE s.stage_name = %s
              AND s.status = %s
              AND t.status <> 'failed'
            ORDER BY s.task_id ASC
            LIMIT 1
            """,
            (stage_name, READY),
        )
        return video_info.merge_into(cur.fetchone())


def find_ready_speaker_segment() -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    video_info.ensure_schema()
    with connect() as conn:
        cur = _dict_cursor(conn)
        _ensure_staged_account_columns_cur(cur)
        cur.execute(
            f"""
            SELECT seg.id, seg.task_id, seg.item_index
            FROM speaker_segment seg FORCE INDEX (idx_speaker_segment_status_task_item)
            JOIN video_info vi ON vi.task_id = seg.task_id
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
             AND sp.sub_stage = CASE
                   WHEN vi.task_type = 'narration' THEN %s
                   WHEN vi.task_type IN (%s, %s) THEN %s
                   ELSE %s
                 END
            LEFT JOIN distributor_task_stages tr ON tr.task_id = seg.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'
            JOIN task t ON t.id = seg.task_id
            WHERE seg.status = %s
              AND sp.status IN (%s, %s)
              AND (
                (sp.sub_stage = %s AND vi.task_type = 'narration')
                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s) AND tr.status = %s)
                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s) AND tr.status = %s)
              )
              AND t.status <> 'failed'
            ORDER BY seg.task_id ASC, seg.item_index ASC
            LIMIT {READY_SPEAKER_SEGMENT_CANDIDATE_LIMIT}
            """,
            (
                SPEAKER_NARRATION_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                SPEAKER_MAIN_SUB_STAGE,
                SEGMENT_READY,
                READY,
                RUNNING,
                SPEAKER_NARRATION_SUB_STAGE,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
                SPEAKER_MAIN_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
            ),
        )
        candidate_rows = cur.fetchall()
        if not candidate_rows:
            return None

        candidate_segment_ids = [int(row["id"]) for row in candidate_rows]
        candidate_task_ids = sorted({str(row["task_id"]) for row in candidate_rows})
        segment_placeholders = ", ".join(["%s"] * len(candidate_segment_ids))
        task_placeholders = ", ".join(["%s"] * len(candidate_task_ids))

        cur.execute(
            f"""
            SELECT seg.*,
                   vi.task_type AS task_type,
                   sp.sub_stage AS speaker_sub_stage,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
             AND sp.sub_stage = CASE
                   WHEN vi.task_type = 'narration' THEN %s
                   WHEN vi.task_type IN (%s, %s) THEN %s
                   ELSE %s
                 END
            LEFT JOIN distributor_task_stages tr ON tr.task_id = seg.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'
            JOIN task t ON t.id = seg.task_id
            JOIN (
                SELECT seg_stats.task_id,
                       COUNT(*) AS total_segments,
                       SUM(CASE WHEN seg_stats.status <> %s THEN 1 ELSE 0 END) AS remaining_segments
                FROM speaker_segment seg_stats
                WHERE seg_stats.task_id IN ({task_placeholders})
                GROUP BY seg_stats.task_id
            ) stats ON stats.task_id = seg.task_id
            LEFT JOIN (
                SELECT submission.task_id,
                       MAX(
                           CASE
                             WHEN COALESCE(upload_capacity.active_count, 0) < account.downloader_max_staged_count
                             THEN 1
                             ELSE 0
                           END
                       ) AS has_cooldown_capacity,
                       MIN(
                           CASE
                             WHEN COALESCE(upload_capacity.active_count, 0) < account.downloader_max_staged_count
                             THEN COALESCE(upload_capacity.active_count, 0)
                             ELSE NULL
                           END
                       ) AS min_available_cooldown
                FROM downloader_submission submission FORCE INDEX (idx_downloader_submission_status_type_task)
                JOIN uploader_account account ON account.account_key = submission.type
                LEFT JOIN (
                    SELECT upload_submission.account_key,
                           COUNT(*) AS active_count
                    FROM uploader_task upload_submission
                    WHERE upload_submission.status IN (%s, %s)
                    GROUP BY upload_submission.account_key
                ) upload_capacity ON upload_capacity.account_key = account.account_key
                WHERE submission.status = %s
                  AND NULLIF(submission.type, '') IS NOT NULL
                  AND submission.task_id IN ({task_placeholders})
                GROUP BY submission.task_id
            ) account_priority ON account_priority.task_id = seg.task_id
            WHERE sp.status IN (%s, %s)
              AND seg.status = %s
              AND seg.id IN ({segment_placeholders})
              AND (
                (sp.sub_stage = %s AND vi.task_type = 'narration')
                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s) AND tr.status = %s)
                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s) AND tr.status = %s)
              )
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
            (
                SPEAKER_NARRATION_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                SPEAKER_MAIN_SUB_STAGE,
                SEGMENT_SUCCESS,
                *candidate_task_ids,
                READY,
                RUNNING,
                SUCCESS,
                *candidate_task_ids,
                READY,
                RUNNING,
                SEGMENT_READY,
                *candidate_segment_ids,
                SPEAKER_NARRATION_SUB_STAGE,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
                SPEAKER_MAIN_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
                SUCCESS,
                RUNNING,
                RUNNING,
            ),
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
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
             AND sp.sub_stage = CASE
                   WHEN vi.task_type = 'narration' THEN %s
                   WHEN vi.task_type IN (%s, %s) THEN %s
                   ELSE %s
                 END
            LEFT JOIN distributor_task_stages tr ON tr.task_id = seg.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'
            SET seg.status = %s,
                seg.attempt_count = seg.attempt_count + 1,
                seg.started_at = COALESCE(seg.started_at, NOW()),
                seg.error_message = NULL,
                seg.`operator` = %s
            WHERE seg.id = %s
              AND seg.status = %s
              AND sp.status IN (%s, %s)
              AND (
                (sp.sub_stage = %s AND vi.task_type = 'narration')
                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s) AND tr.status = %s)
                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s) AND tr.status = %s)
              )
              AND t.status <> 'failed'
            """,
            (
                SPEAKER_NARRATION_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                SPEAKER_MAIN_SUB_STAGE,
                SEGMENT_RUNNING,
                operator,
                segment_id,
                SEGMENT_READY,
                READY,
                RUNNING,
                SPEAKER_NARRATION_SUB_STAGE,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
                SPEAKER_MAIN_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SUCCESS,
            ),
        )
        if cur.rowcount != 1:
            conn.commit()
            return None

        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT seg.*,
                   vi.task_type AS task_type,
                   sp.sub_stage AS speaker_sub_stage,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM speaker_segment seg
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
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
                UPDATE distributor_task_stages
                SET status = %s,
                    started_at = COALESCE(started_at, NOW()),
                    error_message = NULL,
                    `operator` = %s
                WHERE task_id = %s AND stage_name = 'speaker' AND sub_stage = %s AND status = %s
                """,
                (RUNNING, operator, row["task_id"], row["speaker_sub_stage"], READY),
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


def get_speaker_segment(task_id: str, item_index: int) -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    video_info.ensure_schema()
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT seg.*,
                   vi.task_type AS task_type,
                   sp.sub_stage AS speaker_sub_stage,
                   vi.audio_vocals_path AS speaker_audio_vocals_path,
                   vi.translation_json_path AS translation_json_path
            FROM speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
             AND sp.sub_stage = CASE
                   WHEN vi.task_type = 'narration' THEN %s
                   WHEN vi.task_type IN (%s, %s) THEN %s
                   ELSE %s
                 END
            WHERE seg.task_id = %s
              AND seg.item_index = %s
            LIMIT 1
            """,
            (
                SPEAKER_NARRATION_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                SPEAKER_MAIN_SUB_STAGE,
                task_id,
                item_index,
            ),
        )
        return video_info.merge_into(cur.fetchone())


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
    operator = _operator_value()
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
                started_at = COALESCE(started_at, NOW()),
                completed_at = NOW(),
                error_message = NULL,
                `operator` = %s
            WHERE id = %s
            """,
            (
                SEGMENT_SUCCESS,
                reference_wav_path,
                reference_wav_url,
                tts_wav_path,
                tts_wav_url,
                operator,
                segment_id,
            ),
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
    narration_timeout_seconds = NARRATION_SEGMENT_RUNNING_TIMEOUT_SECONDS
    message = f"speaker segment timed out after {timeout_seconds}s; retrying"
    narration_message = f"speaker narration segment timed out after {narration_timeout_seconds}s; retrying"
    exhausted_message = f"speaker segment timed out after {timeout_seconds}s; max attempts exhausted"
    narration_exhausted_message = (
        f"speaker narration segment timed out after {narration_timeout_seconds}s; max attempts exhausted"
    )
    failed_recycle_message = "speaker failed segment recycled; retrying"
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT DISTINCT seg.task_id
            FROM speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            WHERE seg.status = %s
              AND seg.attempt_count >= seg.max_attempts
              AND seg.started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, seg.started_at, NOW()) >
                  CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END
            """,
            (SEGMENT_RUNNING, narration_timeout_seconds, timeout_seconds),
        )
        exhausted_task_ids = [str(row["task_id"]) for row in cur.fetchall()]

        cur = conn.cursor()
        cur.execute(
            """
            UPDATE speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            SET seg.status = %s,
                seg.error_message = CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END,
                seg.started_at = NULL,
                seg.completed_at = NULL,
                seg.`operator` = NULL
            WHERE seg.status = %s
              AND seg.attempt_count < seg.max_attempts
              AND seg.started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, seg.started_at, NOW()) >
                  CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END
            """,
            (
                SEGMENT_READY,
                narration_message,
                message,
                SEGMENT_RUNNING,
                narration_timeout_seconds,
                timeout_seconds,
            ),
        )
        retried = cur.rowcount
        cur.execute(
            """
            UPDATE speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            SET seg.status = %s,
                seg.error_message = CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END,
                seg.completed_at = NOW()
            WHERE seg.status = %s
              AND seg.attempt_count >= seg.max_attempts
              AND seg.started_at IS NOT NULL
              AND TIMESTAMPDIFF(SECOND, seg.started_at, NOW()) >
                  CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END
            """,
            (
                SEGMENT_FAILED,
                narration_exhausted_message,
                exhausted_message,
                SEGMENT_RUNNING,
                narration_timeout_seconds,
                timeout_seconds,
            ),
        )
        failed = cur.rowcount
        cur = _dict_cursor(conn)
        cur.execute(
            """
            SELECT DISTINCT seg.task_id
            FROM speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
             AND sp.sub_stage = CASE
                   WHEN vi.task_type = 'narration' THEN %s
                   WHEN vi.task_type IN (%s, %s) THEN %s
                   ELSE %s
                 END
            JOIN task t ON t.id = seg.task_id
            WHERE seg.status = %s
              AND sp.status IN (%s, %s, %s)
              AND (t.status <> 'failed' OR t.current_stage = 'speaker')
              AND (
                  seg.error_message IS NULL
                  OR seg.error_message NOT LIKE 'translator api task failed:%%'
              )
            """,
            (
                SPEAKER_NARRATION_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                SPEAKER_MAIN_SUB_STAGE,
                SEGMENT_FAILED,
                READY,
                RUNNING,
                FAILED,
            ),
        )
        recycled_failed_task_ids = [str(row["task_id"]) for row in cur.fetchall()]
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE speaker_segment seg
            JOIN video_info vi ON vi.task_id = seg.task_id
            JOIN distributor_task_stages sp
              ON sp.task_id = seg.task_id
             AND sp.stage_name = 'speaker'
             AND sp.sub_stage = CASE
                   WHEN vi.task_type = 'narration' THEN %s
                   WHEN vi.task_type IN (%s, %s) THEN %s
                   ELSE %s
                 END
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
            (
                SPEAKER_NARRATION_SUB_STAGE,
                *CHUNK_SPEAKER_TASK_TYPES,
                SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                SPEAKER_MAIN_SUB_STAGE,
                SEGMENT_READY,
                failed_recycle_message,
                SEGMENT_FAILED,
                READY,
                RUNNING,
                FAILED,
            ),
        )
        recycled_failed = cur.rowcount
        if recycled_failed_task_ids:
            placeholders = ", ".join(["%s"] * len(recycled_failed_task_ids))
            cur.execute(
                f"""
                UPDATE distributor_task_stages sp
                JOIN task t ON t.id = sp.task_id
                SET sp.status = %s,
                    sp.completed_at = NULL,
                    sp.error_message = NULL,
                    t.status = 'running',
                    t.current_stage = 'speaker',
                    t.completed_at = NULL,
                    t.error_message = NULL
                WHERE sp.task_id IN ({placeholders})
                  AND sp.stage_name = 'speaker'
                  AND sp.sub_stage = CASE
                        WHEN EXISTS (
                          SELECT 1 FROM video_info vi
                          WHERE vi.task_id = sp.task_id AND vi.task_type = 'narration'
                        ) THEN %s
                        WHEN EXISTS (
                          SELECT 1 FROM video_info vi
                          WHERE vi.task_id = sp.task_id AND vi.task_type IN (%s, %s)
                        ) THEN %s
                        ELSE %s
                      END
                  AND sp.status = %s
                  AND t.current_stage = 'speaker'
                """,
                (
                    RUNNING,
                    *recycled_failed_task_ids,
                    SPEAKER_NARRATION_SUB_STAGE,
                    *CHUNK_SPEAKER_TASK_TYPES,
                    SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                    SPEAKER_MAIN_SUB_STAGE,
                    FAILED,
                ),
            )
        conn.commit()
        return int(retried) + int(failed) + int(recycled_failed), exhausted_task_ids


def find_finalizable_speaker_task(task_id: str | None = None) -> dict[str, Any] | None:
    ensure_speaker_segment_schema()
    task_filter = "AND sp.task_id = %s" if task_id is not None else ""
    params: list[Any] = [
        "speaker",
        READY,
        RUNNING,
        SPEAKER_NARRATION_SUB_STAGE,
        SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
        *CHUNK_SPEAKER_TASK_TYPES,
        SUCCESS,
        SPEAKER_MAIN_SUB_STAGE,
        *CHUNK_SPEAKER_TASK_TYPES,
        SUCCESS,
    ]
    if task_id is not None:
        params.append(task_id)
    params.append(SEGMENT_SUCCESS)
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT sp.*
            FROM distributor_task_stages sp
            JOIN task t ON t.id = sp.task_id
            JOIN video_info vi ON vi.task_id = sp.task_id
            LEFT JOIN distributor_task_stages tr ON tr.task_id = sp.task_id AND tr.stage_name = 'translator' AND tr.sub_stage = 'main'
            WHERE sp.stage_name = %s
              AND sp.status IN (%s, %s)
              AND (
                (sp.sub_stage = %s AND vi.task_type = 'narration')
                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s) AND tr.status = %s)
                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s) AND tr.status = %s)
              )
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
    params: list[Any] = [
        SEGMENT_FAILED,
        "speaker",
        READY,
        RUNNING,
        SPEAKER_NARRATION_SUB_STAGE,
        SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
        *CHUNK_SPEAKER_TASK_TYPES,
        SPEAKER_MAIN_SUB_STAGE,
        *CHUNK_SPEAKER_TASK_TYPES,
    ]
    if task_id is not None:
        params.append(task_id)
    params.extend([SEGMENT_FAILED, SEGMENT_PENDING, SEGMENT_READY, SEGMENT_RUNNING])
    with connect() as conn:
        cur = _dict_cursor(conn)
        cur.execute(
            f"""
            SELECT sp.task_id,
                   sp.sub_stage,
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
            FROM distributor_task_stages sp
            JOIN task t ON t.id = sp.task_id
            JOIN video_info vi ON vi.task_id = sp.task_id
            WHERE sp.stage_name = %s
              AND sp.status IN (%s, %s)
              AND (
                (sp.sub_stage = %s AND vi.task_type = 'narration')
                OR (sp.sub_stage = %s AND vi.task_type IN (%s, %s))
                OR (sp.sub_stage = %s AND vi.task_type <> 'narration' AND vi.task_type NOT IN (%s, %s))
              )
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
            params,
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
            FROM distributor_task_stages
            WHERE stage_name = 'speaker'
              AND status = %s
              AND task_id IN ({placeholders})
            """,
            (SUCCESS, *task_ids),
        )
        return {str(row["task_id"]) for row in cur.fetchall()}


def mark_speaker_failed_from_segment(
    task_id: str,
    message: str,
    sub_stage: str = SPEAKER_MAIN_SUB_STAGE,
) -> None:
    mark_failed(SERVICE_NAME, task_id, message, sub_stage)


def mark_running(
    stage_name: str,
    task_id: str,
    sub_stage: str = SPEAKER_MAIN_SUB_STAGE,
) -> bool:
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
            WHERE task_id = %s AND stage_name = %s AND sub_stage = %s AND status = %s
            """,
            (RUNNING, operator, task_id, stage_name, sub_stage, READY),
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


def _update_stage_fields(
    stage_name: str,
    task_id: str,
    fields: Mapping[str, Any],
    sub_stage: str = SPEAKER_MAIN_SUB_STAGE,
) -> None:
    return
    table = _service_table_for(stage_name)
    assignments = ", ".join(f"{key} = %s" for key in fields)
    values = list(fields.values()) + [task_id, sub_stage]
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE {table} SET {assignments} WHERE task_id = %s AND sub_stage = %s", values)
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


def mark_success(
    stage_name: str,
    task_id: str,
    outputs: Mapping[str, Any] | None = None,
    sub_stage: str = SPEAKER_MAIN_SUB_STAGE,
) -> None:
    table = _service_table_for(stage_name)
    fields = dict(outputs or {})
    stage_fields: dict[str, Any] = {}
    assignments = ["status = %s", "completed_at = NOW()", "error_message = NULL"]
    values: list[Any] = [SUCCESS]
    for key, value in stage_fields.items():
        assignments.append(f"{key} = %s")
        values.append(value)
    values.extend([task_id, stage_name, sub_stage])

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT status FROM task WHERE id = %s", (task_id,))
        task_row = cur.fetchone()
        if not task_row:
            conn.commit()
            return
        # Another stage may fail while this stage is still running. Preserve
        # the task failure, but persist this stage's result and outputs.
        video_info.upsert(task_id, fields, cur)
        cur.execute(
            f"UPDATE {table} SET {', '.join(assignments)} WHERE task_id = %s AND stage_name = %s AND sub_stage = %s",
            tuple(values),
        )
        conn.commit()


def mark_failed(
    stage_name: str,
    task_id: str,
    message: str,
    sub_stage: str = SPEAKER_MAIN_SUB_STAGE,
) -> None:
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
            WHERE task_id = %s AND stage_name = %s AND sub_stage = %s
            """,
            (FAILED, message, task_id, stage_name, sub_stage),
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
