from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from ydbi_speaker import storage


class StorageDownloadTest(unittest.TestCase):
    def test_concurrent_download_same_destination_reuses_completed_file(self) -> None:
        calls = 0
        active = 0
        max_active = 0
        lock = threading.Lock()
        first_download_started = threading.Event()
        finish_download = threading.Event()

        class Client:
            def fget_object(self, _bucket: str, _object_name: str, file_path: str) -> None:
                nonlocal calls, active, max_active
                with lock:
                    calls += 1
                    active += 1
                    max_active = max(max_active, active)
                first_download_started.set()
                self.assertTrue(finish_download.wait(timeout=1))
                Path(file_path).write_bytes(b"audio")
                with lock:
                    active -= 1

        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "input" / "narration-reference.wav"
            ref = "http://120.53.92.66:9000/youbi-assets/assets/reference.wav"

            with patch.object(storage, "_minio_client", return_value=Client()):
                with ThreadPoolExecutor(max_workers=2) as executor:
                    first = executor.submit(storage.download, ref, destination)
                    self.assertTrue(first_download_started.wait(timeout=1))
                    second = executor.submit(storage.download, ref, destination)
                    finish_download.set()
                    results = [first.result(timeout=1), second.result(timeout=1)]

            self.assertEqual([destination, destination], results)
            self.assertEqual(b"audio", destination.read_bytes())

        self.assertEqual(1, calls)
        self.assertEqual(1, max_active)


if __name__ == "__main__":
    unittest.main()
