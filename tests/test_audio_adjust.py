from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from ydbi_speaker.adapters.audio_adjust import stabilize_narration_audio
from ydbi_speaker.adapters.voice_profile import VoiceProfile
from ydbi_speaker import db
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

    def test_handle_segment_balances_dubbing_multi_segment_output(self) -> None:
        vocals = Path("/tmp/vocals.wav")
        global_reference = Path("/tmp/global-reference.wav")
        generated = Path("/tmp/generated.wav")
        adjusted = Path("/tmp/adjusted.wav")
        session = Path("/tmp/dubbing-multi-task")
        profile = VoiceProfile(
            task_id="task-multi",
            sub_stage=db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
            profile_version=1,
            reference_item_index=0,
            reference_text="原文",
            reference_wav=global_reference,
            reference_wav_url="http://example/reference.wav",
            reference_embedding_url="http://example/reference.npy",
            generation_options={},
            similarity_threshold=0.7,
        )
        row = {
            "task_id": "task-multi",
            "task_type": "dubbing_multi_segment",
            "speaker_sub_stage": "dubbing_multi_segment",
            "item_index": 3,
            "start_time": 1000,
            "end_time": 4000,
            "dst_text": "中文片段",
        }

        with (
            patch("ydbi_speaker.main.storage.task_work_dir", return_value=session),
            patch("ydbi_speaker.main._download_vocals", return_value=vocals),
            patch("ydbi_speaker.main.get_or_create_profile", return_value=profile),
            patch("ydbi_speaker.main.generate_tts_segment", return_value=generated) as generate,
            patch("ydbi_speaker.main.balance_generated_audio", return_value=adjusted) as balance,
            patch("ydbi_speaker.main.record_similarity") as similarity,
        ):
            result = handle_segment(row)

        self.assertEqual((global_reference, adjusted), result)
        generate.assert_called_once_with(
            "中文片段",
            3,
            global_reference,
            global_reference,
            session,
            progress_label="task-multi:chunk:3",
            prompt_text="原文",
            combined_cloning=True,
            generation_options_override={},
        )
        balance.assert_called_once_with(generated, session)
        similarity.assert_called_once()


if __name__ == "__main__":
    unittest.main()
