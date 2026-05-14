from __future__ import annotations

import logging
import time
from pathlib import Path

from ydbi_speaker import db
from ydbi_speaker import storage
from ydbi_speaker.adapters.audio import split_audio_segment, split_audio_segments
from ydbi_speaker.adapters.reference import select_global_reference
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
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    candidates = _vocals_object_candidates(task_id)
    local_vocals = row.get("audio_vocals_path") or row.get("speaker_audio_vocals_path")
    demucs_operator = db.demucs_operator_for(task_id)
    current_operator = db.current_operator()
    if demucs_operator == current_operator and local_vocals:
        return storage.download(local_vocals, destination, object_candidates=candidates)

    vocals_url = str(row.get("audio_vocals_url") or "").strip()
    if vocals_url:
        log.info(
            "speaker task=%s downloading vocals from minio url=%s destination=%s",
            task_id,
            vocals_url,
            destination,
        )
        return storage.download(vocals_url, destination, object_candidates=candidates)

    if local_vocals:
        return storage.download(local_vocals, destination, object_candidates=candidates)
    raise FileNotFoundError(f"audio_vocals_url is missing for task: {task_id}")


def handle(row: dict) -> dict[str, str]:
    raise RuntimeError("speaker uses yd_speaker_segment rows; batch translation JSON input is no longer supported")


def _prepare_references(task_id: str, vocals: Path, session: Path) -> tuple[Path, dict[int, Path]]:
    segment_rows = db.list_reference_segments(task_id) or db.list_speaker_segments(task_id)
    if not segment_rows:
        raise RuntimeError(f"speaker has no segment rows for task: {task_id}")

    segment_paths = split_audio_segments(vocals, segment_rows, session)
    try:
        global_reference, candidates = select_global_reference(segment_paths, segment_rows, session)
    except FileNotFoundError:
        log.warning("speaker task=%s could not select a scored reference; using legacy fallback", task_id)
        return fallback_reference(session / "segments" / "vocals"), segment_paths
    top = candidates[0] if candidates else {}
    log.debug(
        "speaker task=%s selected global reference=%s source_index=%s score=%s",
        task_id,
        global_reference,
        top.get("item_index"),
        top.get("score"),
    )
    return global_reference, segment_paths


def handle_segment(row: dict) -> tuple[Path, Path]:
    task_id = row["task_id"]
    session = storage.task_work_dir(task_id)
    item_index = int(row["item_index"])
    vocals = _download_vocals(row, session)
    vocals_dir = session / "segments" / "vocals"
    global_reference, segment_paths = _prepare_references(task_id, vocals, session)

    segment_reference = segment_paths.get(item_index) or split_audio_segment(
        vocals,
        item_index,
        int(row["start_time"]),
        int(row["end_time"]),
        session,
    )
    fallback = fallback_reference(vocals_dir)
    output = generate_tts_segment(str(row["dst_text"] or ""), item_index, global_reference, fallback, session)
    return segment_reference, output


def publish_segment_outputs(task_id: str, reference: Path, output: Path) -> tuple[str, str, str, str]:
    reference_url = storage.upload(
        reference,
        f"{task_id}/speaker/vocals/{reference.name}",
        "audio/wav",
    )
    output_url = storage.upload(
        output,
        f"{task_id}/speaker/tts/{output.name}",
        "audio/wav",
    )
    return str(reference), reference_url, str(output), output_url


def finalize_task(row: dict) -> None:
    task_id = row["task_id"]
    vocals_dir = storage.object_prefix(f"{task_id}/speaker/vocals")
    tts_dir = storage.object_prefix(f"{task_id}/speaker/tts")
    translation_ref = f"db://yd_speaker_segment/{task_id}"
    fields = {
        "translation_json_path": translation_ref,
        "vocals_segments_dir": vocals_dir,
        "tts_segments_dir": tts_dir,
    }
    db.mark_success("speaker", task_id, fields)
    log.info("speaker task %s finalized", task_id)


def run_segment_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.ensure_speaker_segment_schema()
    log.info("speaker service started; polling segments every %ss", POLL_INTERVAL_SECONDS)
    while True:
        try:
            db.record_service_poll("speaker")
            finalizable = db.find_finalizable_speaker_task()
            if finalizable:
                finalize_task(finalizable)
                continue

            row = db.find_ready_speaker_segment()
            if row:
                claimed = db.claim_speaker_segment(int(row["id"]))
                if not claimed:
                    continue
                task_id = claimed["task_id"]
                item_index = int(claimed["item_index"])
                log.debug("speaker segment started task=%s index=%d", task_id, item_index)
                try:
                    reference, output = handle_segment(claimed)
                    reference_path, reference_url, output_path, output_url = publish_segment_outputs(
                        task_id,
                        reference,
                        output,
                    )
                    db.mark_speaker_segment_success(
                        int(claimed["id"]),
                        reference_path,
                        reference_url,
                        output_path,
                        output_url,
                    )
                    log.info("%s:%d succeeded", task_id, item_index)
                    finalizable = db.find_finalizable_speaker_task(task_id)
                    if finalizable:
                        finalize_task(finalizable)
                except Exception as exc:
                    log.exception("speaker segment failed task=%s index=%d", task_id, item_index)
                    exhausted = db.mark_speaker_segment_failed(int(claimed["id"]), str(exc))
                    if exhausted:
                        db.mark_speaker_failed_from_segment(task_id, str(exc))
                continue
        except Exception:
            log.exception("speaker failed to poll segment queue; retrying in %ss", POLL_INTERVAL_SECONDS)
        time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    run_segment_worker()


if __name__ == "__main__":
    main()
