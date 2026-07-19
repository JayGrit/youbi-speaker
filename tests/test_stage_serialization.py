from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

try:
    import mysql.connector  # noqa: F401
except ModuleNotFoundError:
    mysql_module = types.ModuleType("mysql")
    connector_module = types.ModuleType("mysql.connector")
    mysql_module.connector = connector_module
    sys.modules["mysql"] = mysql_module
    sys.modules["mysql.connector"] = connector_module

from ydbi_speaker import db


class FakeCursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params = ()
        self.rowcount = 0

    def execute(self, sql, params=()) -> None:
        self.sql = sql
        self.params = params

    def executemany(self, sql, params) -> None:
        self.sql = sql
        self.params = list(params)
        self.rowcount = len(self.params)

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_value = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def cursor(self, dictionary=False):
        return self.cursor_value

    def start_transaction(self) -> None:
        return None

    def commit(self) -> None:
        return None


class RecycleCursor(FakeCursor):
    def __init__(self) -> None:
        super().__init__()
        self.executed = []

    def execute(self, sql, params=()) -> None:
        super().execute(sql, params)
        self.executed.append((sql, params))

    def fetchall(self):
        return []


class InitCursor(FakeCursor):
    def __init__(self) -> None:
        super().__init__()
        self.selected_task = False
        self.select_sql = ""

    def execute(self, sql, params=()) -> None:
        super().execute(sql, params)
        if "SELECT sp.task_id" in sql:
            self.selected_task = True
            self.select_sql = sql
        if "INSERT INTO speaker_segment" in sql:
            self.rowcount = 2

    def fetchone(self):
        if self.selected_task:
            self.selected_task = False
            return {"task_id": "task-1", "sub_stage": "main", "task_type": "dubbing"}
        return None


class NarrationInitCursor(InitCursor):
    def __init__(self) -> None:
        super().__init__()
        self.selected_sentences = False

    def execute(self, sql, params=()) -> None:
        super().execute(sql, params)
        if "FROM product_narration_sentence" in sql and "SELECT line_index" in sql:
            self.selected_sentences = True

    def fetchone(self):
        if self.selected_task:
            self.selected_task = False
            return {
                "task_id": "narration-7",
                "sub_stage": "narration",
                "task_type": "narration",
            }
        return None

    def fetchall(self):
        if self.selected_sentences:
            self.selected_sentences = False
            return [
                {"line_index": 1, "sentence_text": "第一行。", "segment_index": 1},
                {"line_index": 2, "sentence_text": "第二行。", "segment_index": 1},
                {"line_index": 3, "sentence_text": "第三行。", "segment_index": 2},
            ]
        return []


class DubbingMultiSegmentInitCursor(InitCursor):
    task_id = "task-multi"
    task_type = db.TASK_TYPE_DUBBING_MULTI_SEGMENT

    def __init__(self, existing_tables: set[str] | None = None) -> None:
        super().__init__()
        self.existing_tables = existing_tables or {db.TRANSLATOR_CHUNK_TABLE}
        self.table_exists_result: int | None = None

    def execute(self, sql, params=()) -> None:
        super().execute(sql, params)
        if "INFORMATION_SCHEMA.TABLES" in sql:
            self.table_exists_result = int(params[0] in self.existing_tables)

    def fetchone(self):
        if self.selected_task:
            self.selected_task = False
            return {
                "task_id": self.task_id,
                "sub_stage": db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                "task_type": self.task_type,
            }
        if self.table_exists_result is not None:
            result = (self.table_exists_result,)
            self.table_exists_result = None
            return result
        return None


class DubbingChunkAlignedInitCursor(DubbingMultiSegmentInitCursor):
    task_id = "task-chunk-aligned"
    task_type = db.TASK_TYPE_DUBBING_CHUNK_ALIGNED


class StageSerializationTest(unittest.TestCase):
    def test_speaker_creates_its_segments_from_translator_output(self) -> None:
        cursor = InitCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            initialized = db.initialize_ready_speaker_task()

        self.assertEqual(("task-1", 2), initialized)
        self.assertIn("sp.sub_stage = %s", cursor.select_sql)
        self.assertIn("FROM translator_segment", cursor.sql)
        self.assertEqual((db.SEGMENT_READY, "task-1"), cursor.params)

    def test_dubbing_multi_segment_creates_segments_from_translator_chunks(self) -> None:
        cursor = DubbingMultiSegmentInitCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            initialized = db.initialize_ready_speaker_task()

        self.assertEqual(("task-multi", 2), initialized)
        self.assertIn("vi.task_type IN (%s, %s)", cursor.select_sql)
        self.assertIn("FROM `translator_chunk` tc", cursor.sql)
        self.assertIn("tc.chunk_index AS item_index", cursor.sql)
        self.assertIn("MIN(tc.chunk_start_time) AS start_time", cursor.sql)
        self.assertIn("MAX(tc.chunk_end_time) AS end_time", cursor.sql)
        self.assertEqual((db.SEGMENT_READY, "task-multi"), cursor.params)

    def test_dubbing_chunk_aligned_creates_segments_from_translator_chunks(self) -> None:
        cursor = DubbingChunkAlignedInitCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            initialized = db.initialize_ready_speaker_task()

        self.assertEqual(("task-chunk-aligned", 2), initialized)
        self.assertIn("FROM `translator_chunk` tc", cursor.sql)
        self.assertIn("tc.chunk_index AS item_index", cursor.sql)
        self.assertEqual((db.SEGMENT_READY, "task-chunk-aligned"), cursor.params)

    def test_dubbing_multi_segment_falls_back_to_legacy_translator_chunk_table(self) -> None:
        cursor = DubbingMultiSegmentInitCursor(existing_tables={db.LEGACY_TRANSLATOR_CHUNK_TABLE})
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            initialized = db.initialize_ready_speaker_task()

        self.assertEqual(("task-multi", 2), initialized)
        self.assertIn("FROM `translator-chunk` tc", cursor.sql)
        self.assertEqual((db.SEGMENT_READY, "task-multi"), cursor.params)

    def test_ready_segment_query_uses_task_priority_without_translator_gate(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
            patch.object(db.task_info, "ensure_schema"),
            patch.object(db.task_info, "merge_into", side_effect=lambda row: row),
        ):
            self.assertIsNone(db.find_ready_speaker_segment())

        self.assertIn("JOIN task t ON t.id = seg.task_id", cursor.sql)
        self.assertIn("ORDER BY COALESCE(t.priority, 1) DESC, seg.task_id ASC, seg.item_index ASC", cursor.sql)
        self.assertNotIn("translator", cursor.sql)
        self.assertNotIn("tr.status", cursor.sql)
        self.assertNotIn("uploader_account", cursor.sql)
        self.assertNotIn("uploader_task", cursor.sql)
        self.assertNotIn("downloader_submission", cursor.sql)
        self.assertNotIn("WITH candidate_segments AS", cursor.sql)
        self.assertNotIn("JOIN candidate_tasks candidate_task", cursor.sql)

    def test_ready_segment_query_targets_narration_sub_stage(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
            patch.object(db.task_info, "ensure_schema"),
            patch.object(db.task_info, "merge_into", side_effect=lambda row: row),
            patch.object(db, "_ensure_staged_account_columns_cur"),
        ):
            self.assertIsNone(db.find_ready_speaker_segment())

        self.assertIn("WHEN vi.task_type = 'narration' THEN %s", cursor.sql)
        self.assertIn("WHEN vi.task_type IN (%s, %s) THEN %s", cursor.sql)
        self.assertEqual(db.SPEAKER_NARRATION_SUB_STAGE, cursor.params[0])
        self.assertEqual(db.SEGMENT_READY, cursor.params[5])

    def test_ready_segment_final_sort_uses_task_priority_and_segment_counts(self) -> None:
        class CandidateCursor(FakeCursor):
            def __init__(self) -> None:
                super().__init__()
                self.calls = []

            def execute(self, sql, params=()) -> None:
                super().execute(sql, params)
                self.calls.append((sql, params))

            def fetchall(self):
                return [{"id": 12, "task_id": "low"}, {"id": 8, "task_id": "high"}]

        cursor = CandidateCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
            patch.object(db.task_info, "ensure_schema"),
            patch.object(db.task_info, "merge_into", side_effect=lambda row: row),
        ):
            self.assertIsNone(db.find_ready_speaker_segment())

        first_sql, _ = cursor.calls[0]
        final_sql, final_params = cursor.calls[1]
        self.assertIn("ORDER BY COALESCE(t.priority, 1) DESC, seg.task_id ASC, seg.item_index ASC", first_sql)
        self.assertIn("COALESCE(t.priority, 1) AS task_priority", final_sql)
        self.assertIn("COALESCE(t.priority, 1) DESC", final_sql)
        self.assertIn("CASE WHEN sp.status = %s THEN 0 ELSE 1 END", final_sql)
        self.assertIn("stats.remaining_segments", final_sql)
        self.assertIn("stats.total_segments", final_sql)
        self.assertNotIn("translator", final_sql)
        self.assertNotIn("uploader_account", final_sql)
        self.assertNotIn("uploader_task", final_sql)
        self.assertNotIn("downloader_submission", final_sql)
        self.assertIn("high", final_params)
        self.assertIn("low", final_params)

    def test_claim_segment_filters_by_speaker_sub_stage(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db.task_info, "ensure_schema"),
            patch.object(db, "_ensure_operator_columns"),
            patch.object(db, "_operator_value", return_value="MY_HP"),
        ):
            self.assertIsNone(db.claim_speaker_segment(12))

        self.assertIn("WHEN vi.task_type = 'narration' THEN %s", cursor.sql)
        self.assertIn("sp.status IN (%s, %s)", cursor.sql)
        self.assertEqual(
            (
                db.SPEAKER_NARRATION_SUB_STAGE,
                *db.CHUNK_SPEAKER_TASK_TYPES,
                db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                db.SPEAKER_MAIN_SUB_STAGE,
                db.SEGMENT_RUNNING,
                "MY_HP",
                12,
                db.SEGMENT_READY,
                db.READY,
                db.RUNNING,
            ),
            cursor.params,
        )
        self.assertNotIn("translator", cursor.sql)

    def test_mark_segment_success_records_current_operator(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "_operator_value", return_value="MY_HP"),
        ):
            db.mark_speaker_segment_success(12, "/tmp/ref.wav", "minio://ref", "/tmp/tts.wav", "minio://tts")

        self.assertIn("started_at = COALESCE(started_at, NOW())", cursor.sql)
        self.assertIn("`operator` = %s", cursor.sql)
        self.assertEqual(
            (
                db.SEGMENT_SUCCESS,
                "/tmp/ref.wav",
                "minio://ref",
                "/tmp/tts.wav",
                "minio://tts",
                "MY_HP",
                12,
            ),
            cursor.params,
        )

    def test_recycle_uses_twenty_minute_timeout_for_narration(self) -> None:
        cursor = RecycleCursor()
        with patch.object(db, "connect", return_value=FakeConnection(cursor)):
            self.assertEqual((0, []), db.recycle_stale_speaker_segments())

        for sql, params in cursor.executed[:3]:
            self.assertIn("CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END", sql)
            self.assertEqual((20 * 60, 100), params[-2:])
        self.assertIn("timed out after 1200s", cursor.executed[1][1][1])
        self.assertIn("timed out after 100s", cursor.executed[1][1][2])

    def test_narration_groups_sentence_rows_by_segment_index(self) -> None:
        cursor = NarrationInitCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            initialized = db.initialize_ready_speaker_task()

        self.assertEqual(("narration-7", 2), initialized)
        self.assertIn("VALUES (%s, %s, %s, %s, %s", cursor.sql)
        self.assertEqual(
            [
                ("narration-7", 0, db.SEGMENT_READY, "第一行。\n第二行。", "第一行。\n第二行。"),
                ("narration-7", 1, db.SEGMENT_READY, "第三行。", "第三行。"),
            ],
            cursor.params,
        )

    def test_narration_segment_builder_rejects_non_contiguous_segment_indexes(self) -> None:
        with self.assertRaisesRegex(ValueError, "segment index is not contiguous"):
            db._build_narration_segments(
                [
                    {"line_index": 1, "sentence_text": "第一行。", "segment_index": 1},
                    {"line_index": 2, "sentence_text": "第二行。", "segment_index": 3},
                ]
            )

    def test_narration_segment_builder_requires_first_segment_to_be_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "segment index is not contiguous"):
            db._build_narration_segments(
                [{"line_index": 1, "sentence_text": "第一行。", "segment_index": 2}]
            )

    def test_narration_can_finalize_without_translator(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
            patch.object(db.task_info, "merge_into", side_effect=lambda row: row),
        ):
            self.assertIsNone(db.find_finalizable_speaker_task("narration-7"))

        self.assertIn("LEFT JOIN translator", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type = 'narration'", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type IN (%s, %s) AND tr.status = %s", cursor.sql)
        self.assertIn("vi.task_type NOT IN (%s, %s) AND tr.status = %s", cursor.sql)

    def test_terminal_failed_task_returns_sub_stage(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            self.assertIsNone(db.find_terminal_failed_speaker_task("narration-7"))

        self.assertIn("SELECT sp.task_id", cursor.sql)
        self.assertIn("sp.sub_stage", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type = 'narration'", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type IN (%s, %s)", cursor.sql)


if __name__ == "__main__":
    unittest.main()
