from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from ydbi_speaker.adapters.audio_adjust import stabilize_narration_audio
from ydbi_speaker.main import handle_segment


class NarrationAudioAdjustTests(unittest.TestCase):
    def test_stabilize_narration_audio_writes_adjusted_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            session = Path(temporary_dir)
            input_path = session / "segments" / "tts" / "0001.wav"
            input_path.parent.mkdir(parents=True)
            sample_rate = 16_000
            time = np.arange(sample_rate * 10) / sample_rate
            quiet = 0.02 * np.sin(2 * np.pi * 220 * time[: sample_rate * 5])
            loud = 0.3 * np.sin(2 * np.pi * 220 * time[sample_rate * 5 :])
            sf.write(input_path, np.concatenate([quiet, loud]), sample_rate)

            output_path = stabilize_narration_audio(input_path, session)

            self.assertEqual(session / "segments" / "tts_adjusted" / "0001.wav", output_path)
            self.assertTrue(output_path.exists())
            self.assertNotEqual(input_path.read_bytes(), output_path.read_bytes())

    def test_handle_segment_adjusts_only_narration_output(self) -> None:
        reference = Path("/tmp/reference.wav")
        generated = Path("/tmp/generated.wav")
        adjusted = Path("/tmp/adjusted.wav")
        session = Path("/tmp/narration-task")
        row = {
            "task_id": "narration-task",
            "task_type": "narration",
            "item_index": 0,
            "dst_text": "旁白文本",
        }

        with (
            patch("ydbi_speaker.main.storage.task_work_dir", return_value=session),
            patch("ydbi_speaker.main._download_narration_reference", return_value=reference),
            patch("ydbi_speaker.main.generate_tts_segment", return_value=generated),
            patch("ydbi_speaker.main.stabilize_narration_audio", return_value=adjusted) as stabilize,
        ):
            result = handle_segment(row)

        self.assertEqual((reference, adjusted), result)
        stabilize.assert_called_once_with(generated, session)


if __name__ == "__main__":
    unittest.main()
