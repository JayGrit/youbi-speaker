from __future__ import annotations
import os
import json
import socket
import uuid
from collections.abc import Mapping
from typing import Any
import mysql.connector
from . import task_info
from .config import MYSQL_CONFIG, NARRATION_SEGMENT_RUNNING_TIMEOUT_SECONDS, SEGMENT_RUNNING_TIMEOUT_SECONDS
from .service import FAILED, READY, RUNNING, SERVICE_NAME, SERVICE_TABLE, SUCCESS
HEARTBEAT_TABLE = 'service_instance_heartbeat'
SUBMISSION_TABLE = 'downloader_submission'
UPLOADER_ACCOUNT_TABLE = 'uploader_account'
UPLOAD_SUBMISSION_TABLES = ('uploader_task',)
PRODUCT_NARRATION_SENTENCE_TABLE = 'product_narration_sentence'
PRODUCT_BLESSING_TABLE = 'product_blessing'
PRODUCT_PPT_TABLE = 'product_ppt'
ASSETS_TABLE = 'asseter_static'
MAX_NARRATION_SEGMENT_CHARS = 500
OPERATOR_COLUMN = 'operator'
OPERATOR_COLUMN_DEFINITION = 'VARCHAR(128) NULL'
_speaker_stage_schema_ready = False
READY_SPEAKER_SEGMENT_CANDIDATE_LIMIT = 2000
MYSQL_NETWORK_ERROR_CODES = {2002, 2003, 2005, 2013, 2055}
SPEAKER_TASK_INFO_FIELDS = {'task_type', 'target_language', 'audio_vocals_url', 'audio_source_url', 'translation_json_path', 'tts_segments_dir'}

def is_mysql_connection_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, mysql.connector.Error):
            if getattr(current, 'errno', None) in MYSQL_NETWORK_ERROR_CODES:
                return True
            message = str(current).lower()
            if "can't connect to mysql server" in message or 'lost connection to mysql server' in message:
                return True
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return False

def _row_value(row: Any, index: int=0) -> Any:
    if isinstance(row, Mapping):
        return list(row.values())[index]
    return row[index]

def _service_table_for(stage_name: str) -> str:
    if stage_name != SERVICE_NAME:
        raise ValueError(f'{SERVICE_NAME} service cannot handle stage: {stage_name}')
    return SERVICE_TABLE

def _task_has_upload_submission_cur(cur, task_id: str, topic: str) -> bool:
    if not task_id or not topic:
        return False
    for table in UPLOAD_SUBMISSION_TABLES:
        cur.execute(f'\n            SELECT 1\n            FROM {table}\n            WHERE task_id = %s AND topic = %s\n            LIMIT 1\n            ', (task_id, topic))
        if cur.fetchone():
            return True
    return False

def _apply_staged_pipeline_failure_cur(cur, task_id: str, old_task_status: str | None) -> None:
    return
SEGMENT_PENDING = 'pending'
SEGMENT_READY = 'ready'
SEGMENT_RUNNING = 'running'
SEGMENT_SUCCESS = 'success'
SEGMENT_FAILED = 'failed'
TRANSLATOR_SEGMENT_TABLE = 'translator_segment'
TRANSLATOR_CHUNK_TABLE = 'translator_chunk'
LEGACY_TRANSLATOR_CHUNK_TABLE = 'translator-chunk'
_segment_schema_ready = False
_profile_schema_ready = False
SPEAKER_VOICE_PROFILE_TABLE = 'speaker_voice_profile'
SPEAKER_SEGMENT_SIMILARITY_TABLE = 'speaker_segment_similarity'
SPEAKER_SEGMENT_EXTRA_COLUMNS = {'reference_wav_url': 'TEXT', 'tts_wav_url': 'TEXT', 'actual_start_time': 'INT', 'actual_end_time': 'INT', 'speed_ratio': 'DOUBLE'}
SPEAKER_MAIN_SUB_STAGE = 'main'
SPEAKER_NARRATION_SUB_STAGE = 'narration'
SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE = 'dubbing_multi_segment'
SPEAKER_BLESSING_SUB_STAGE = 'blessing'
SPEAKER_PPT_DIALOGUE_SUB_STAGE = 'ppt_dialogue'
BLESSING_REFERENCE_VOICE_REMARK = 'blessing_reference_voice_20260709'
PPT_FEMALE_REFERENCE_VOICE_REMARK = 'ppt_dialogue_female_reference_voice_20260717'
PPT_MALE_REFERENCE_VOICE_REMARK = 'ppt_dialogue_male_reference_voice_20260717'
TASK_TYPE_DUBBING_MULTI_SEGMENT = 'dubbing_multi_segment'
TASK_TYPE_DUBBING_CHUNK_ALIGNED = 'dubbing_chunk_aligned'
CHUNK_SPEAKER_TASK_TYPES = (TASK_TYPE_DUBBING_MULTI_SEGMENT, TASK_TYPE_DUBBING_CHUNK_ALIGNED)
CHUNK_SPEAKER_TASK_TYPE_PLACEHOLDERS = ', '.join(['%s'] * len(CHUNK_SPEAKER_TASK_TYPES))

def _translator_chunk_table_cur(cur) -> str:
    return TRANSLATOR_CHUNK_TABLE

def connect():
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    return conn

def _dict_cursor(conn):
    return conn.cursor(dictionary=True)

def _quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"

def _heartbeat_device_name() -> str:
    return os.environ.get('DEVICE', '').strip() or 'Macbook Air M4'

def _heartbeat_instance_id(stage_name: str) -> str:
    global _HEARTBEAT_INSTANCE_ID
    if _HEARTBEAT_INSTANCE_ID is None:
        _HEARTBEAT_INSTANCE_ID = f'{stage_name}:{_heartbeat_device_name()}:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}'
    return _HEARTBEAT_INSTANCE_ID

def _operator_value() -> str:
    return os.environ.get('DEVICE', '').strip() or 'Macbook Air M4'

def current_operator() -> str:
    return _operator_value()

def _ensure_operator_columns(cur, tables: tuple[str, ...]) -> None:
    return

def record_service_poll(stage_name: str) -> None:
    device = _heartbeat_device_name()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute("\n            INSERT INTO service_instance_heartbeat (\n                service_name, instance_id, device_name, host_name, process_id,\n                runtime_role, status, last_seen_at, heartbeat_interval_seconds,\n                metadata_json, started_at\n            )\n            VALUES (%s, %s, %s, %s, %s, 'worker', 'running', NOW(), 10, JSON_OBJECT('source', 'service_worker'), NOW())\n            ON DUPLICATE KEY UPDATE\n                device_name = VALUES(device_name),\n                host_name = VALUES(host_name),\n                process_id = VALUES(process_id),\n                runtime_role = VALUES(runtime_role),\n                status = VALUES(status),\n                last_seen_at = VALUES(last_seen_at),\n                heartbeat_interval_seconds = VALUES(heartbeat_interval_seconds),\n                metadata_json = VALUES(metadata_json)\n            ", (stage_name, _heartbeat_instance_id(stage_name), device, socket.gethostname(), os.getpid()))
        conn.commit()
from .repositories.profiles import get_voice_profile, upsert_segment_similarity, upsert_voice_profile
from .services.initialization import _build_narration_segments, _build_ppt_dialogue_segments, initialize_ready_speaker_task
from .services.claiming import claim_speaker_segment, find_ready_speaker_segment, recycle_stale_speaker_segments
from .repositories.segments import get_speaker_segment, list_speaker_segments, mark_speaker_segment_failed, mark_speaker_segment_success, reset_speaker_segment_after_worker_crash
from .services.finalization import find_finalizable_speaker_task, find_terminal_failed_speaker_task, list_successful_speaker_task_ids, mark_speaker_failed_from_segment
from .repositories.references import _asset_voice_url_by_remark, blessing_reference_voice_url, demucs_operator_for, list_reference_segments, ppt_reference_voice_url
from .repositories.special_stages import claim_ready_blessing_task, mark_blessing_failed, mark_blessing_success, mark_ppt_dialogue_failed, mark_ppt_dialogue_success
from .repositories.stages import _update_stage_fields, find_ready, get_task, mark_failed, mark_running, mark_success, set_combiner_speaker_inputs
