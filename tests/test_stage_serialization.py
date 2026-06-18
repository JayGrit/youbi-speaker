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


class InitCursor(FakeCursor):
    def __init__(self) -> None:
        super().__init__()
        self.selected_task = False

    def execute(self, sql, params=()) -> None:
        super().execute(sql, params)
        if "SELECT sp.task_id" in sql:
            self.selected_task = True
        if "INSERT INTO speaker_segment" in sql:
            self.rowcount = 2

    def fetchone(self):
        if self.selected_task:
            self.selected_task = False
            return {"task_id": "task-1"}
        return None


class StageSerializationTest(unittest.TestCase):
    def test_speaker_creates_its_segments_from_translator_output(self) -> None:
        cursor = InitCursor()
        with (
            patch.object(db, "connect", return_value=FakeConnection(cursor)),
            patch.object(db, "ensure_speaker_segment_schema"),
        ):
            initialized = db.initialize_ready_speaker_task()

        self.assertEqual(("task-1", 2), initialized)
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

        self.assertIn("AND tr.status = %s", cursor.sql)
        self.assertEqual(db.SUCCESS, cursor.params[4])


if __name__ == "__main__":
    unittest.main()
