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


class StageSerializationTest(unittest.TestCase):
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
