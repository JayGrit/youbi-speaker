from __future__ import annotations

import logging
import time
from pathlib import Path

from ydbi_speaker import db
from ydbi_speaker import storage
from ydbi_speaker.adapters.audio import split_audio_segment
from ydbi_speaker.adapters.voxcpm import fallback_reference, generate_tts_segment
from ydbi_speaker.config import POLL_INTERVAL_SECONDS

log = logging.getLogger(__name__)


def _vocals_object_candidates(task_id: str) -> tuple[str, ...]:
    return (
        f"{task_id}/media/audio_vocals.wav",
        f"{task_id}/demucs/audio_vocals.wav",
        f"{task_id}/audio_vocals.wav",
    )


def _translation_object_candidates(task_id: str) -> tuple[str, ...]:
    return ()


def _download_vocals(row: dict, session: Path) -> Path:
    task_id = row["task_id"]
    destination = session / "input" / "vocals.wav"
    candidates = _vocals_object_candidates(task_id)
    primary = row["audio_vocals_path"]
    try:
        return storage.download(primary, destination, object_candidates=candidates)
    except FileNotFoundError:
        fallback = row.get("speaker_audio_vocals_path")
        if fallback and str(fallback) != str(primary):
            return storage.download(fallback, destination, object_candidates=candidates)
        raise


def handle(row: dict) -> dict[str, str]:
    raise RuntimeError("speaker uses yd_speaker_segment rows; batch translation JSON input is no longer supported")


def handle_segment(row: dict) -> tuple[Path, Path]:
    task_id = row["task_id"]
    session = storage.task_work_dir(task_id)
    item_index = int(row["item_index"])
    vocals = _download_vocals(row, session)
    vocals_dir = session / "segments" / "vocals"
    tts_dir = session / "segments" / "tts"

    reference = split_audio_segment(
        vocals,
        item_index,
        int(row["start_time"]),
        int(row["end_time"]),
        session,
    )
    fallback = fallback_reference(vocals_dir)
    output = generate_tts_segment(str(row["dst_text"] or ""), item_index, reference, fallback, session)
    return reference, output


def publish_segment_outputs(task_id: str, reference: Path, output: Path) -> tuple[str, str]:
    reference_ref = storage.upload(
        reference,
        f"{task_id}/speaker/vocals/{reference.name}",
        "audio/wav",
    )
    output_ref = storage.upload(
        output,
        f"{task_id}/speaker/tts/{output.name}",
        "audio/wav",
    )
    return reference_ref, output_ref


def finalize_task(row: dict) -> None:
    task_id = row["task_id"]
    vocals_dir = storage.object_prefix(f"{task_id}/speaker/vocals")
    tts_dir = storage.object_prefix(f"{task_id}/speaker/tts")
    translation_ref = f"db://yd_speaker_segment/{task_id}"
    fields = {
        "vocals_segments_dir": vocals_dir,
        "tts_segments_dir": tts_dir,
    }
    db.set_combiner_speaker_inputs(task_id, translation_ref, tts_dir)
    db.mark_success("speaker", task_id, fields)
    log.info("speaker task %s finalized", task_id)


def run_segment_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.ensure_speaker_segment_schema()
    log.info("speaker service started; polling segments every %ss", POLL_INTERVAL_SECONDS)
    while True:
        try:
            db.record_service_poll("speaker")
            row = db.find_ready_speaker_segment()
            if row:
                claimed = db.claim_speaker_segment(int(row["id"]))
                if not claimed:
                    continue
                task_id = claimed["task_id"]
                item_index = int(claimed["item_index"])
                log.info("speaker segment started task=%s index=%d", task_id, item_index)
                try:
                    reference, output = handle_segment(claimed)
                    reference_ref, output_ref = publish_segment_outputs(task_id, reference, output)
                    db.mark_speaker_segment_success(int(claimed["id"]), reference_ref, output_ref)
                    log.info("speaker segment succeeded task=%s index=%d output=%s", task_id, item_index, output_ref)
                except Exception as exc:
                    log.exception("speaker segment failed task=%s index=%d", task_id, item_index)
                    exhausted = db.mark_speaker_segment_failed(int(claimed["id"]), str(exc))
                    if exhausted:
                        db.mark_speaker_failed_from_segment(task_id, str(exc))
                continue

            finalizable = db.find_finalizable_speaker_task()
            if finalizable:
                finalize_task(finalizable)
                continue
        except Exception:
            log.exception("speaker failed to poll segment queue; retrying in %ss", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    run_segment_worker()


if __name__ == "__main__":
    main()
