from __future__ import annotations

import unittest
from unittest.mock import patch

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

    def test_ready_segment_query_requires_translator_success(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
            patch.object(db.video_info, "ensure_schema"),
            patch.object(db.video_info, "merge_into", side_effect=lambda row: row),
            patch.object(db, "_ensure_staged_account_columns_cur"),
        ):
            self.assertIsNone(db.find_ready_speaker_segment())

        self.assertIn("sp.sub_stage = %s AND vi.task_type <> 'narration' AND tr.status = %s", cursor.sql)
        self.assertEqual(db.SUCCESS, cursor.params[8])

    def test_ready_segment_query_targets_narration_sub_stage(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
            patch.object(db.video_info, "ensure_schema"),
            patch.object(db.video_info, "merge_into", side_effect=lambda row: row),
            patch.object(db, "_ensure_staged_account_columns_cur"),
        ):
            self.assertIsNone(db.find_ready_speaker_segment())

        self.assertIn("WHEN vi.task_type = 'narration' THEN %s", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type = 'narration'", cursor.sql)
        self.assertEqual(db.SPEAKER_NARRATION_SUB_STAGE, cursor.params[1])
        self.assertEqual(db.SPEAKER_NARRATION_SUB_STAGE, cursor.params[6])

    def test_claim_segment_filters_by_speaker_sub_stage(self) -> None:
        cursor = FakeCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db.video_info, "ensure_schema"),
            patch.object(db, "_ensure_operator_columns"),
            patch.object(db, "_operator_value", return_value="MY_HP"),
        ):
            self.assertIsNone(db.claim_speaker_segment(12))

        self.assertIn("WHEN vi.task_type = 'narration' THEN %s", cursor.sql)
        self.assertIn("sp.status IN (%s, %s)", cursor.sql)
        self.assertEqual(
            (
                db.SPEAKER_NARRATION_SUB_STAGE,
                db.SPEAKER_MAIN_SUB_STAGE,
                db.SEGMENT_RUNNING,
                "MY_HP",
                12,
                db.SEGMENT_READY,
                db.READY,
                db.RUNNING,
                db.SPEAKER_NARRATION_SUB_STAGE,
                db.SPEAKER_MAIN_SUB_STAGE,
                db.SUCCESS,
            ),
            cursor.params,
        )

    def test_recycle_uses_twenty_minute_timeout_for_narration(self) -> None:
        cursor = RecycleCursor()
        with patch.object(db, "connect", return_value=FakeConnection(cursor)):
            self.assertEqual((0, []), db.recycle_stale_speaker_segments())

        for sql, params in cursor.executed[:3]:
            self.assertIn("CASE WHEN vi.task_type = 'narration' THEN %s ELSE %s END", sql)
            self.assertEqual((20 * 60, 3 * 60), params[-2:])
        self.assertIn("timed out after 1200s", cursor.executed[1][1][1])
        self.assertIn("timed out after 180s", cursor.executed[1][1][2])

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
            patch.object(db.video_info, "merge_into", side_effect=lambda row: row),
        ):
            self.assertIsNone(db.find_finalizable_speaker_task("narration-7"))

        self.assertIn("LEFT JOIN translator", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type = 'narration'", cursor.sql)
        self.assertIn("sp.sub_stage = %s AND vi.task_type <> 'narration' AND tr.status = %s", cursor.sql)

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


if __name__ == "__main__":
    unittest.main()
