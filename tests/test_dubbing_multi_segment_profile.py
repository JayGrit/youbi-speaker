from __future__ import annotations

import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ydbi_speaker import db
from ydbi_speaker.adapters import speaker_similarity, voice_profile, voxcpm
from ydbi_speaker.adapters.voice_profile import VoiceProfile
from ydbi_speaker.main import handle_dubbing_multi_segment, handle_segment


class DubbingMultiSegmentProfileTest(unittest.TestCase):
    def test_voxcpm_combined_cloning_passes_prompt_and_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            reference = session / "reference.wav"
            reference.write_bytes(b"wav")
            calls: list[dict] = []

            class Model:
                tts_model = type("TtsModel", (), {"sample_rate": 24000})()

                def generate(self, **kwargs):
                    calls.append(kwargs)
                    return [0.0, 0.0]

            with (
                patch.object(voxcpm, "_load_model", return_value=Model()),
                patch.object(voxcpm.AudioSegment, "from_file", return_value=type("Audio", (), {"__len__": lambda self: 2000})()),
                patch.object(voxcpm.sf, "write", side_effect=lambda path, *_args, **_kwargs: Path(path).write_bytes(b"out")),
            ):
                output = voxcpm.generate_tts_segment(
                    "hello",
                    3,
                    reference,
                    reference,
                    session,
                    prompt_text="source prompt",
                    combined_cloning=True,
                )
                output_exists = output.exists()

        self.assertTrue(output_exists)
        self.assertEqual("hello", calls[0]["text"])
        self.assertEqual(str(reference), calls[0]["prompt_wav_path"])
        self.assertEqual("source prompt", calls[0]["prompt_text"])
        self.assertEqual(str(reference), calls[0]["reference_wav_path"])
        self.assertIn("cfg_value", calls[0])
        self.assertIn("inference_timesteps", calls[0])

    def test_dubbing_multi_segment_uses_profile_reference_without_combined_cloning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            vocals = session / "vocals.wav"
            vocals.write_bytes(b"vocals")
            reference = session / "profile-reference.wav"
            reference.write_bytes(b"ref")
            generated = session / "generated.wav"
            generated.write_bytes(b"gen")
            adjusted = session / "adjusted.wav"
            adjusted.write_bytes(b"adj")
            profile = VoiceProfile(
                task_id="task-1",
                sub_stage=db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                profile_version=1,
                reference_item_index=7,
                reference_text="original source",
                reference_wav=reference,
                reference_wav_url="http://example/ref.wav",
                reference_embedding_url="http://example/ref.npy",
                generation_options={"cfg_value": 2.0},
                similarity_threshold=0.7,
            )
            generate_calls: list[dict] = []
            similarity_calls: list[dict] = []

            def fake_generate(*args, **kwargs):
                generate_calls.append({"args": args, "kwargs": kwargs})
                return generated

            row = {
                "id": 12,
                "task_id": "task-1",
                "item_index": 2,
                "start_time": 0,
                "end_time": 1000,
                "dst_text": " target ",
            }
            with (
                patch("ydbi_speaker.main.storage.task_work_dir", return_value=session),
                patch("ydbi_speaker.main._download_vocals", return_value=vocals),
                patch("ydbi_speaker.main.get_or_create_profile", return_value=profile),
                patch("ydbi_speaker.main.generate_tts_segment", side_effect=fake_generate),
                patch("ydbi_speaker.main.balance_generated_audio", return_value=adjusted),
                patch("ydbi_speaker.main.record_similarity", side_effect=lambda **kwargs: similarity_calls.append(kwargs)),
            ):
                reference_result, output_result = handle_dubbing_multi_segment(row)

        self.assertEqual(reference, reference_result)
        self.assertEqual(adjusted, output_result)
        self.assertNotIn("combined_cloning", generate_calls[0]["kwargs"])
        self.assertNotIn("prompt_text", generate_calls[0]["kwargs"])
        self.assertEqual(reference, generate_calls[0]["args"][2])
        self.assertEqual(reference, generate_calls[0]["args"][3])
        self.assertEqual(adjusted, similarity_calls[0]["generated_wav"])

    def test_handle_segment_routes_non_dubbing_to_existing_paths(self) -> None:
        with (
            patch("ydbi_speaker.main.handle_main_segment", return_value=("main-ref", "main-out")) as main_segment,
            patch("ydbi_speaker.main.handle_dubbing_multi_segment", return_value=("dub-ref", "dub-out")) as dubbing_segment,
            patch("ydbi_speaker.main.handle_narration_segment", return_value=("nar-ref", "nar-out")) as narration_segment,
        ):
            self.assertEqual(("main-ref", "main-out"), handle_segment({"task_type": "normal"}))
            self.assertEqual(
                ("dub-ref", "dub-out"),
                handle_segment({"task_type": db.TASK_TYPE_DUBBING_MULTI_SEGMENT}),
            )
            self.assertEqual(("nar-ref", "nar-out"), handle_segment({"task_type": "narration"}))

        main_segment.assert_called_once()
        dubbing_segment.assert_called_once()
        narration_segment.assert_called_once()

    def test_voice_profile_reuses_existing_db_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)

            def fake_download(_ref, destination, *args, **kwargs):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"ref")
                return destination

            with (
                patch.object(voice_profile.db, "get_voice_profile", return_value={
                    "task_id": "task-1",
                    "sub_stage": db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                    "profile_version": 1,
                    "reference_item_index": 5,
                    "reference_text": "source text",
                    "reference_wav_url": "http://120.53.92.66:9000/ydbi/task-1/speaker/profile/dubbing_multi_segment/reference.wav",
                    "reference_embedding_url": "http://120.53.92.66:9000/ydbi/task-1/speaker/profile/dubbing_multi_segment/reference_embedding.npy",
                    "generation_options_json": '{"cfg_value": 2.0}',
                    "similarity_threshold": 0.7,
                }),
                patch.object(voice_profile.storage, "download", side_effect=fake_download),
                patch.object(voice_profile.db, "upsert_voice_profile") as upsert,
            ):
                profile = voice_profile.get_or_create_profile("task-1", session / "vocals.wav", session)
                reference_exists = profile.reference_wav.exists()

        self.assertEqual(5, profile.reference_item_index)
        self.assertEqual("source text", profile.reference_text)
        self.assertTrue(reference_exists)
        upsert.assert_not_called()

    def test_voice_profile_creates_db_record_and_uploads_minio_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            vocals = session / "vocals.wav"
            vocals.write_bytes(b"vocals")
            selected = session / "selected.wav"
            selected.write_bytes(b"selected")
            uploads: list[str] = []
            upserts: list[dict] = []

            with (
                patch.object(voice_profile.db, "get_voice_profile", return_value=None),
                patch.object(voice_profile.storage, "download", side_effect=FileNotFoundError("missing")),
                patch.object(voice_profile.db, "list_reference_segments", return_value=[]),
                patch.object(voice_profile.db, "list_speaker_segments", return_value=[
                    {"item_index": 1, "src_text": "chosen source", "start_time": 0, "end_time": 1000},
                ]),
                patch.object(voice_profile, "split_audio_segments", return_value={1: selected}),
                patch.object(voice_profile, "select_global_reference", return_value=(selected, [{"item_index": 1, "score": 91.0}])),
                patch.object(voice_profile.storage, "upload", side_effect=lambda _path, object_name, _content_type: uploads.append(object_name) or f"http://minio/{object_name}"),
                patch.object(voice_profile.db, "upsert_voice_profile", side_effect=lambda **kwargs: upserts.append(kwargs)),
            ):
                profile = voice_profile.get_or_create_profile("task-1", vocals, session)

        self.assertEqual(1, profile.reference_item_index)
        self.assertEqual("chosen source", profile.reference_text)
        self.assertIn("task-1/speaker/profile/dubbing_multi_segment/reference.wav", uploads)
        self.assertIn("task-1/speaker/profile/dubbing_multi_segment/profile.json", uploads)
        self.assertEqual("task-1", upserts[0]["task_id"])

    def test_voice_profile_creation_is_serialized_per_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            vocals = session / "vocals.wav"
            vocals.write_bytes(b"vocals")
            selected = session / "selected.wav"
            selected.write_bytes(b"selected")
            created_profiles: list[VoiceProfile] = []
            embedding_calls = 0

            def fake_load_existing(task_id: str, existing_session: Path) -> VoiceProfile | None:
                self.assertEqual("task-concurrent", task_id)
                self.assertEqual(session, existing_session)
                return created_profiles[0] if created_profiles else None

            def fake_embedding(_path: Path) -> np.ndarray:
                nonlocal embedding_calls
                embedding_calls += 1
                time.sleep(0.02)
                return np.array([1.0, 0.0], dtype=np.float32)

            def fake_upsert(**kwargs) -> None:
                if kwargs["status"] != "ready" or created_profiles:
                    return
                created_profiles.append(
                    VoiceProfile(
                        task_id=kwargs["task_id"],
                        sub_stage=kwargs["sub_stage"],
                        profile_version=kwargs["profile_version"],
                        reference_item_index=kwargs["reference_item_index"],
                        reference_text=kwargs["reference_text"],
                        reference_wav=session / "profile" / db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE / "reference.wav",
                        reference_wav_url=kwargs["reference_wav_url"],
                        reference_embedding_url=kwargs["reference_embedding_url"],
                        generation_options=kwargs["generation_options"],
                        similarity_threshold=kwargs["similarity_threshold"],
                    )
                )

            with (
                patch.object(voice_profile, "_load_existing_profile", side_effect=fake_load_existing),
                patch.object(voice_profile.storage, "download", side_effect=FileNotFoundError("missing")),
                patch.object(voice_profile.db, "list_reference_segments", return_value=[]),
                patch.object(voice_profile.db, "list_speaker_segments", return_value=[
                    {"item_index": 1, "src_text": "chosen source", "start_time": 0, "end_time": 1000},
                ]),
                patch.object(voice_profile, "split_audio_segments", return_value={1: selected}),
                patch.object(voice_profile, "select_global_reference", return_value=(selected, [{"item_index": 1, "score": 91.0}])),
                patch.object(voice_profile.storage, "upload", side_effect=lambda _path, object_name, _content_type: f"http://minio/{object_name}"),
                patch.object(voice_profile.storage, "upload_once", side_effect=lambda _path, object_name, _content_type: f"http://minio/{object_name}"),
                patch.object(voice_profile, "embedding", side_effect=fake_embedding),
                patch.object(voice_profile.db, "upsert_voice_profile", side_effect=fake_upsert),
            ):
                with ThreadPoolExecutor(max_workers=3) as executor:
                    profiles = list(
                        executor.map(
                            lambda _index: voice_profile.get_or_create_profile("task-concurrent", vocals, session),
                            range(3),
                        )
                    )

        self.assertEqual(1, embedding_calls)
        self.assertEqual(1, len(created_profiles))
        self.assertTrue(all(profile.task_id == "task-concurrent" for profile in profiles))

    def test_similarity_success_upserts_segment_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            reference = session / "reference.wav"
            generated = session / "generated.wav"
            reference.write_bytes(b"ref")
            generated.write_bytes(b"gen")
            profile = VoiceProfile(
                task_id="task-1",
                sub_stage=db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                profile_version=1,
                reference_item_index=1,
                reference_text="source",
                reference_wav=reference,
                reference_wav_url="http://minio/ref.wav",
                reference_embedding_url="http://minio/ref.npy",
                generation_options={},
                similarity_threshold=0.7,
            )
            upserts: list[dict] = []

            with (
                patch.object(speaker_similarity, "_load_or_create_reference_embedding", return_value=(session / "ref.npy", "http://minio/ref.npy", np.array([1.0, 0.0]))),
                patch.object(speaker_similarity, "_embedding", return_value=np.array([0.8, 0.2])),
                patch.object(speaker_similarity.storage, "upload", side_effect=lambda _path, object_name, _content_type: f"http://minio/{object_name}"),
                patch.object(speaker_similarity.db, "upsert_segment_similarity", side_effect=lambda **kwargs: upserts.append(kwargs)),
            ):
                speaker_similarity.record_similarity(
                    profile=profile,
                    row={"id": 42, "item_index": 3},
                    generated_wav=generated,
                    session=session,
                )

        self.assertEqual("task-1", upserts[0]["task_id"])
        self.assertEqual(3, upserts[0]["item_index"])
        self.assertGreater(upserts[0]["similarity_score"], 0.7)
        self.assertTrue(upserts[0]["passed"])

    def test_similarity_failure_records_error_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            reference = session / "reference.wav"
            generated = session / "generated.wav"
            reference.write_bytes(b"ref")
            generated.write_bytes(b"gen")
            profile = VoiceProfile(
                task_id="task-1",
                sub_stage=db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE,
                profile_version=1,
                reference_item_index=1,
                reference_text="source",
                reference_wav=reference,
                reference_wav_url="http://minio/ref.wav",
                reference_embedding_url="http://minio/ref.npy",
                generation_options={},
                similarity_threshold=0.7,
            )
            upserts: list[dict] = []

            with (
                patch.object(speaker_similarity, "_load_or_create_reference_embedding", side_effect=RuntimeError("encoder failed")),
                patch.object(speaker_similarity.storage, "upload", return_value="http://minio/error.json"),
                patch.object(speaker_similarity.db, "upsert_segment_similarity", side_effect=lambda **kwargs: upserts.append(kwargs)),
            ):
                speaker_similarity.record_similarity(
                    profile=profile,
                    row={"id": 42, "item_index": 3},
                    generated_wav=generated,
                    session=session,
                )

        self.assertIn("encoder failed", upserts[0]["error_message"])
        self.assertIsNone(upserts[0]["similarity_score"])


if __name__ == "__main__":
    unittest.main()
