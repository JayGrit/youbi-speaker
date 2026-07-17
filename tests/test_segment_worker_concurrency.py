from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ydbi_speaker import db
from ydbi_speaker import main


class SegmentWorkerConcurrencyTest(unittest.TestCase):
    def test_collect_finished_segments_leaves_running_future_inflight(self) -> None:
        future = Future()
        claimed = {"id": 1, "task_id": "task-running", "item_index": 0}
        inflight = {future: claimed}

        self.assertEqual(0, main._collect_finished_segments(inflight))
        self.assertEqual({future: claimed}, inflight)

    def test_claim_ready_segments_caps_inflight_at_requested_limit(self) -> None:
        rows = [{"id": index} for index in range(1, 5)]
        futures = [Future() for _ in range(3)]
        submitted: list[dict] = []

        class FakeExecutor:
            def submit(self, _func, claimed, _tts_executor):
                submitted.append(claimed)
                return futures[len(submitted) - 1]

        def claim(segment_id: int) -> dict:
            return {"id": segment_id, "task_id": f"task-{segment_id}", "item_index": segment_id}

        with (
            patch.object(main.db, "find_ready_speaker_segment", side_effect=rows),
            patch.object(main.db, "claim_speaker_segment", side_effect=claim),
        ):
            inflight: dict[Future, dict] = {}
            claimed_count = main._claim_ready_segments(inflight, FakeExecutor(), object(), 3)

        self.assertEqual(3, claimed_count)
        self.assertEqual(3, len(inflight))
        self.assertEqual([1, 2, 3], [row["id"] for row in submitted])

    def test_process_claimed_segments_run_tts_serially(self) -> None:
        active_tts = 0
        max_active_tts = 0
        lock = threading.Lock()

        def fake_generate(*_args, **_kwargs) -> Path:
            nonlocal active_tts, max_active_tts
            with lock:
                active_tts += 1
                max_active_tts = max(max_active_tts, active_tts)
            time.sleep(0.02)
            with lock:
                active_tts -= 1
            return Path("/tmp/generated.wav")

        def fake_handle(row: dict, tts_runner) -> tuple[Path, Path]:
            output = tts_runner(
                "text",
                int(row["item_index"]),
                Path("/tmp/reference.wav"),
                Path("/tmp/reference.wav"),
                Path("/tmp/session"),
            )
            return Path("/tmp/reference.wav"), output

        claimed_rows = [
            {"id": index, "task_id": "task-serial", "item_index": index}
            for index in range(3)
        ]
        with (
            ThreadPoolExecutor(max_workers=3) as segment_executor,
            ThreadPoolExecutor(max_workers=1) as tts_executor,
            patch.object(main, "generate_tts_segment", side_effect=fake_generate),
            patch.object(main, "handle_segment", side_effect=fake_handle),
            patch.object(main, "publish_segment_outputs", return_value=("", "ref-url", "", "out-url")),
            patch.object(main.db, "mark_speaker_segment_success"),
            patch.object(main.db, "find_finalizable_speaker_task", return_value=None),
        ):
            futures = [
                segment_executor.submit(main._process_claimed_segment, row, tts_executor)
                for row in claimed_rows
            ]
            for future in futures:
                future.result()

        self.assertEqual(1, max_active_tts)

    def test_slow_upload_does_not_block_another_segment_tts(self) -> None:
        first_upload_started = threading.Event()
        second_tts_started = threading.Event()
        generate_calls = 0
        lock = threading.Lock()

        def fake_generate(*_args, **_kwargs) -> Path:
            nonlocal generate_calls
            with lock:
                generate_calls += 1
                if generate_calls == 2:
                    second_tts_started.set()
            return Path("/tmp/generated.wav")

        def fake_handle(row: dict, tts_runner) -> tuple[Path, Path]:
            output = tts_runner(
                "text",
                int(row["item_index"]),
                Path("/tmp/reference.wav"),
                Path("/tmp/reference.wav"),
                Path("/tmp/session"),
            )
            return Path("/tmp/reference.wav"), output

        def fake_publish(task_id: str, _reference: Path, _output: Path) -> tuple[str, str, str, str]:
            if task_id == "task-1":
                first_upload_started.set()
                self.assertTrue(second_tts_started.wait(timeout=1))
            return "", "ref-url", "", "out-url"

        claimed_rows = [
            {"id": 1, "task_id": "task-1", "item_index": 1},
            {"id": 2, "task_id": "task-2", "item_index": 2},
        ]
        with (
            ThreadPoolExecutor(max_workers=2) as segment_executor,
            ThreadPoolExecutor(max_workers=1) as tts_executor,
            patch.object(main, "generate_tts_segment", side_effect=fake_generate),
            patch.object(main, "handle_segment", side_effect=fake_handle),
            patch.object(main, "publish_segment_outputs", side_effect=fake_publish),
            patch.object(main.db, "mark_speaker_segment_success"),
            patch.object(main.db, "find_finalizable_speaker_task", return_value=None),
        ):
            futures = [
                segment_executor.submit(main._process_claimed_segment, row, tts_executor)
                for row in claimed_rows
            ]
            for future in futures:
                future.result()

        self.assertTrue(first_upload_started.is_set())
        self.assertTrue(second_tts_started.is_set())

    def test_segment_exception_marks_failed_without_escaping_worker(self) -> None:
        claimed = {"id": 9, "task_id": "task-fail", "item_index": 4}

        with (
            ThreadPoolExecutor(max_workers=1) as tts_executor,
            patch.object(main, "handle_segment", side_effect=RuntimeError("boom")),
            patch.object(main.db, "mark_speaker_segment_failed", return_value=False) as mark_failed,
        ):
            main._process_claimed_segment(claimed, tts_executor)

        mark_failed.assert_called_once_with(9, "boom")

    def test_cuda_oom_exception_releases_segment_and_exits_worker(self) -> None:
        claimed = {"id": 9, "task_id": "task-oom", "item_index": 4, "attempt_count": 2}
        error = RuntimeError("CUDA out of memory. Tried to allocate 566.00 MiB.")

        with (
            ThreadPoolExecutor(max_workers=1) as tts_executor,
            patch.object(main, "handle_segment", side_effect=error),
            patch.object(main.db, "reset_speaker_segment_after_worker_crash", return_value=True) as reset_segment,
            patch.object(main.db, "mark_speaker_segment_failed") as mark_failed,
            patch.object(main.os, "_exit", side_effect=SystemExit) as exit_process,
        ):
            with self.assertRaises(SystemExit):
                main._process_claimed_segment(claimed, tts_executor)

        reset_segment.assert_called_once()
        self.assertIn("CUDA out of memory", reset_segment.call_args.args[1])
        reset_segment.assert_called_once_with(9, reset_segment.call_args.args[1], 2)
        exit_process.assert_called_once_with(main.CUDA_OOM_EXIT_CODE)
        mark_failed.assert_not_called()

    def test_cuda_oom_detection_checks_exception_chain(self) -> None:
        root = RuntimeError("CUDA out of memory. Tried to allocate 566.00 MiB.")
        wrapped = RuntimeError("tts failed")
        wrapped.__cause__ = root

        self.assertTrue(main._is_cuda_out_of_memory_error(wrapped))

    def test_exhausted_segment_marks_task_failed(self) -> None:
        claimed = {"id": 9, "task_id": "task-fail", "item_index": 4}
        failed_row = {
            "task_id": "task-fail",
            "error_message": "boom",
            "sub_stage": db.SPEAKER_MAIN_SUB_STAGE,
        }

        with (
            ThreadPoolExecutor(max_workers=1) as tts_executor,
            patch.object(main, "handle_segment", side_effect=RuntimeError("boom")),
            patch.object(main.db, "mark_speaker_segment_failed", return_value=True),
            patch.object(main.db, "find_terminal_failed_speaker_task", return_value=failed_row),
            patch.object(main.db, "mark_speaker_failed_from_segment") as mark_task_failed,
        ):
            main._process_claimed_segment(claimed, tts_executor)

        mark_task_failed.assert_called_once_with("task-fail", "boom", db.SPEAKER_MAIN_SUB_STAGE)


if __name__ == "__main__":
    unittest.main()
