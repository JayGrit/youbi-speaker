from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ydbi_speaker import db
from ydbi_speaker import storage
from ydbi_speaker.adapters.audio import split_audio_segment, split_audio_segments
from ydbi_speaker.adapters.audio_adjust import balance_generated_audio, stabilize_narration_audio
from ydbi_speaker.adapters.reference import select_global_reference
from ydbi_speaker.adapters.speaker_similarity import record_similarity
from ydbi_speaker.adapters.voxcpm import fallback_reference, generate_tts_segment, sanitize_target_text
from ydbi_speaker.adapters.voice_profile import get_or_create_profile
from ydbi_speaker.config import (
    DUBBING_MULTI_SEGMENT_PROFILE_ENABLED,
    NARRATION_REFERENCE_AUDIO_URL,
    POLL_INTERVAL_SECONDS,
    SPEAKER_MAX_IN_FLIGHT_SEGMENTS,
    SPEAKER_TTS_CONCURRENCY,
)
from ydbi_speaker.service import SERVICE_NAME

log = logging.getLogger(__name__)
_CLEANUP_INTERVAL_SECONDS = 10 * 60
TtsRunner = Callable[..., Path]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _log_segment_timing(
    task_id: str,
    item_index: int,
    step: str,
    started_at: float,
    total_started_at: float | None = None,
    **fields: object,
) -> None:
    duration = time.perf_counter() - started_at
    total = duration if total_started_at is None else time.perf_counter() - total_started_at
    suffix = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    log.info(
        "speaker timing task=%s index=%d step=%s at=%s duration_s=%.3f total_s=%.3f%s%s",
        task_id,
        item_index,
        step,
        _timestamp(),
        duration,
        total,
        " " if suffix else "",
        suffix,
    )


def _is_empty_target_text_error(exc: Exception) -> bool:
    return "target text must be a non-empty string" in str(exc)


def _vocals_object_candidates(task_id: str) -> tuple[str, ...]:
    return (
        f"{task_id}/media/audio_vocals.wav",
        f"{task_id}/demucs/audio_vocals.wav",
        f"{task_id}/audio_vocals.wav",
    )


def _translation_object_candidates(task_id: str) -> tuple[str, ...]:
    return ()


def _download_destination(session: Path, source_ref: str) -> Path:
    suffix = Path(source_ref.split("?", 1)[0]).suffix or ".wav"
    return session / "input" / f"vocals{suffix}"


def _input_refs(row: dict) -> tuple[tuple[str, str], ...]:
    refs: list[tuple[str, str]] = []
    for key, label in (
        ("audio_vocals_url", "vocals url"),
        ("audio_vocals_path", "vocals path"),
        ("speaker_audio_vocals_path", "speaker vocals path"),
    ):
        value = str(row.get(key) or "").strip()
        if value:
            refs.append((value, label))

    for key, label in (
        ("audio_source_url", "source audio url"),
        ("audio_source_path", "source audio path"),
    ):
        value = str(row.get(key) or "").strip()
        if value:
            refs.append((value, label))

    return tuple(refs)


def _download_vocals(row: dict, session: Path) -> Path:
    task_id = row["task_id"]
    candidates = _vocals_object_candidates(task_id)
    errors: list[str] = []
    for input_ref, input_label in _input_refs(row):
        destination = _download_destination(session, input_ref)
        if destination.exists() and destination.stat().st_size > 0:
            return destination

        log.info(
            "speaker task=%s downloading %s=%s destination=%s",
            task_id,
            input_label,
            input_ref,
            destination,
        )
        try:
            return storage.download(input_ref, destination, object_candidates=candidates)
        except FileNotFoundError as exc:
            errors.append(str(exc))

    detail = "; ".join(errors)
    suffix = f"; {detail}" if detail else ""
    raise FileNotFoundError(f"audio_vocals_url is missing or unavailable for task: {task_id}{suffix}")


def _download_narration_reference(session: Path) -> Path:
    destination = session / "input" / "narration-reference.wav"
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    return storage.download(NARRATION_REFERENCE_AUDIO_URL, destination)


def handle(row: dict) -> dict[str, str]:
    raise RuntimeError("speaker uses speaker_segment rows; batch translation JSON input is no longer supported")


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


def handle_narration_segment(row: dict, tts_runner: TtsRunner | None = None) -> tuple[Path, Path]:
    tts_runner = tts_runner or generate_tts_segment
    task_id = row["task_id"]
    total_started_at = time.perf_counter()
    session = storage.task_work_dir(task_id)
    item_index = int(row["item_index"])
    step_started_at = time.perf_counter()
    reference = _download_narration_reference(session)
    _log_segment_timing(task_id, item_index, "narration_reference_ready", step_started_at, total_started_at)
    target_text = sanitize_target_text(row.get("dst_text"))
    step_started_at = time.perf_counter()
    output = tts_runner(
        target_text,
        item_index,
        reference,
        reference,
        session,
        progress_label=f"{task_id}:{item_index}",
    )
    _log_segment_timing(task_id, item_index, "tts_completed", step_started_at, total_started_at)
    step_started_at = time.perf_counter()
    stabilized = stabilize_narration_audio(output, session)
    _log_segment_timing(task_id, item_index, "audio_adjusted", step_started_at, total_started_at)
    _log_segment_timing(task_id, item_index, "handle_completed", total_started_at, total_started_at)
    return reference, stabilized


def handle_main_segment(row: dict, tts_runner: TtsRunner | None = None) -> tuple[Path, Path]:
    tts_runner = tts_runner or generate_tts_segment
    task_id = row["task_id"]
    total_started_at = time.perf_counter()
    session = storage.task_work_dir(task_id)
    item_index = int(row["item_index"])
    step_started_at = time.perf_counter()
    vocals = _download_vocals(row, session)
    _log_segment_timing(task_id, item_index, "vocals_downloaded", step_started_at, total_started_at)
    vocals_dir = session / "segments" / "vocals"
    step_started_at = time.perf_counter()
    global_reference, segment_paths = _prepare_references(task_id, vocals, session)
    _log_segment_timing(task_id, item_index, "references_prepared", step_started_at, total_started_at)

    step_started_at = time.perf_counter()
    segment_reference = segment_paths.get(item_index) or split_audio_segment(
        vocals,
        item_index,
        int(row["start_time"]),
        int(row["end_time"]),
        session,
    )
    _log_segment_timing(task_id, item_index, "segment_reference_ready", step_started_at, total_started_at)
    target_text = sanitize_target_text(row.get("dst_text"))
    if not target_text:
        log.info("speaker task=%s index=%d using original audio segment", task_id, item_index)
        _log_segment_timing(task_id, item_index, "original_audio_selected", total_started_at, total_started_at)
        return segment_reference, segment_reference

    fallback = fallback_reference(vocals_dir)
    try:
        step_started_at = time.perf_counter()
        output = tts_runner(
            target_text,
            item_index,
            global_reference,
            fallback,
            session,
            progress_label=f"{task_id}:{item_index}",
        )
        _log_segment_timing(task_id, item_index, "tts_completed", step_started_at, total_started_at)
    except ValueError as exc:
        if not _is_empty_target_text_error(exc):
            raise
        log.warning(
            "speaker task=%s index=%d got empty target text from TTS; using original audio segment",
            task_id,
            item_index,
        )
        _log_segment_timing(task_id, item_index, "original_audio_selected", total_started_at, total_started_at)
        return segment_reference, segment_reference
    _log_segment_timing(task_id, item_index, "handle_completed", total_started_at, total_started_at)
    return segment_reference, output


def handle_dubbing_multi_segment(row: dict, tts_runner: TtsRunner | None = None) -> tuple[Path, Path]:
    tts_runner = tts_runner or generate_tts_segment
    task_id = row["task_id"]
    total_started_at = time.perf_counter()
    session = storage.task_work_dir(task_id)
    item_index = int(row["item_index"])
    step_started_at = time.perf_counter()
    vocals = _download_vocals(row, session)
    _log_segment_timing(task_id, item_index, "vocals_downloaded", step_started_at, total_started_at)
    if not DUBBING_MULTI_SEGMENT_PROFILE_ENABLED:
        vocals_dir = session / "segments" / "vocals"
        step_started_at = time.perf_counter()
        global_reference, _segment_paths = _prepare_references(task_id, vocals, session)
        _log_segment_timing(task_id, item_index, "references_prepared", step_started_at, total_started_at)

        target_text = sanitize_target_text(row.get("dst_text"))
        if not target_text:
            log.info("speaker task=%s chunk=%d has no target text; using original chunk audio", task_id, item_index)
            step_started_at = time.perf_counter()
            chunk_reference = split_audio_segment(
                vocals,
                item_index,
                int(row["start_time"]),
                int(row["end_time"]),
                session,
            )
            _log_segment_timing(task_id, item_index, "segment_reference_ready", step_started_at, total_started_at)
            step_started_at = time.perf_counter()
            adjusted = balance_generated_audio(chunk_reference, session)
            _log_segment_timing(task_id, item_index, "audio_adjusted", step_started_at, total_started_at)
            _log_segment_timing(task_id, item_index, "handle_completed", total_started_at, total_started_at)
            return global_reference, adjusted

        fallback = fallback_reference(vocals_dir)
        step_started_at = time.perf_counter()
        output = tts_runner(
            target_text,
            item_index,
            global_reference,
            fallback,
            session,
            progress_label=f"{task_id}:chunk:{item_index}",
        )
        _log_segment_timing(task_id, item_index, "tts_completed", step_started_at, total_started_at)
        step_started_at = time.perf_counter()
        adjusted = balance_generated_audio(output, session)
        _log_segment_timing(task_id, item_index, "audio_adjusted", step_started_at, total_started_at)
        _log_segment_timing(task_id, item_index, "handle_completed", total_started_at, total_started_at)
        return global_reference, adjusted

    step_started_at = time.perf_counter()
    profile = get_or_create_profile(task_id, vocals, session)
    _log_segment_timing(task_id, item_index, "profile_ready", step_started_at, total_started_at)

    target_text = sanitize_target_text(row.get("dst_text"))
    if not target_text:
        log.info("speaker task=%s chunk=%d has no target text; using original chunk audio", task_id, item_index)
        step_started_at = time.perf_counter()
        chunk_reference = split_audio_segment(
            vocals,
            item_index,
            int(row["start_time"]),
            int(row["end_time"]),
            session,
        )
        _log_segment_timing(task_id, item_index, "segment_reference_ready", step_started_at, total_started_at)
        step_started_at = time.perf_counter()
        adjusted = balance_generated_audio(chunk_reference, session)
        _log_segment_timing(task_id, item_index, "audio_adjusted", step_started_at, total_started_at)
        step_started_at = time.perf_counter()
        record_similarity(profile=profile, row=row, generated_wav=adjusted, session=session)
        _log_segment_timing(task_id, item_index, "similarity_recorded", step_started_at, total_started_at)
        _log_segment_timing(task_id, item_index, "handle_completed", total_started_at, total_started_at)
        return profile.reference_wav, adjusted

    step_started_at = time.perf_counter()
    output = tts_runner(
        target_text,
        item_index,
        profile.reference_wav,
        profile.reference_wav,
        session,
        progress_label=f"{task_id}:chunk:{item_index}",
        generation_options_override=profile.generation_options,
    )
    _log_segment_timing(task_id, item_index, "tts_completed", step_started_at, total_started_at)
    step_started_at = time.perf_counter()
    adjusted = balance_generated_audio(output, session)
    _log_segment_timing(task_id, item_index, "audio_adjusted", step_started_at, total_started_at)
    step_started_at = time.perf_counter()
    record_similarity(profile=profile, row=row, generated_wav=adjusted, session=session)
    _log_segment_timing(task_id, item_index, "similarity_recorded", step_started_at, total_started_at)
    _log_segment_timing(task_id, item_index, "handle_completed", total_started_at, total_started_at)
    return profile.reference_wav, adjusted


def handle_segment(row: dict, tts_runner: TtsRunner | None = None) -> tuple[Path, Path]:
    if row.get("speaker_sub_stage") == db.SPEAKER_NARRATION_SUB_STAGE or row.get("task_type") == "narration":
        return handle_narration_segment(row, tts_runner)
    if (
        row.get("speaker_sub_stage") == db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE
        or row.get("task_type") in db.CHUNK_SPEAKER_TASK_TYPES
    ):
        return handle_dubbing_multi_segment(row, tts_runner)
    return handle_main_segment(row, tts_runner)


def publish_segment_outputs(task_id: str, reference: Path, output: Path) -> tuple[str, str, str, str]:
    reference_object = f"{task_id}/speaker/vocals/{reference.name}"
    reference_upload = storage.upload_once if reference.name in {"reference.wav", "narration-reference.wav"} else storage.upload
    reference_url = reference_upload(reference, reference_object, "audio/wav")
    output_url = storage.upload(
        output,
        f"{task_id}/speaker/tts/{output.name}",
        "audio/wav",
    )
    return "", reference_url, "", output_url


def process_blessing_task(row: dict) -> None:
    task_id = str(row["task_id"])
    text = sanitize_target_text(row.get("tts_text"))
    if not text:
        raise ValueError(f"product_blessing.tts_text is empty for task: {task_id}")
    reference_url = db.blessing_reference_voice_url()
    if not reference_url:
        raise FileNotFoundError(
            "blessing reference voice is missing; configure BLESSING_REFERENCE_VOICE_URL "
            f"or asseter_static.remark={db.BLESSING_REFERENCE_VOICE_REMARK!r}"
        )
    session = storage.task_work_dir(task_id)
    reference = storage.download(reference_url, session / "input" / "blessing-reference.wav")
    output = generate_tts_segment(
        text,
        0,
        reference,
        reference,
        session,
        progress_label=f"{task_id}:blessing",
    )
    output_url = storage.upload(
        output,
        f"{task_id}/speaker/blessing/{output.name}",
        "audio/wav",
    )
    db.mark_blessing_success(task_id, output_url)
    shutil.rmtree(storage.task_work_path(task_id), ignore_errors=True)
    log.info("speaker blessing task=%s succeeded audio=%s", task_id, output_url)


def finalize_task(row: dict) -> None:
    task_id = row["task_id"]
    sub_stage = str(row.get("sub_stage") or row.get("speaker_sub_stage") or db.SPEAKER_MAIN_SUB_STAGE)
    tts_dir = storage.object_prefix(f"{task_id}/speaker/tts")
    translation_ref = f"db://speaker_segment/{task_id}"
    fields = {
        "translation_json_path": translation_ref,
        "tts_segments_dir": tts_dir,
    }
    db.mark_success(SERVICE_NAME, task_id, fields, sub_stage)
    shutil.rmtree(storage.task_work_path(task_id), ignore_errors=True)
    log.info("speaker task %s finalized", task_id)


def cleanup_successful_task_work_dirs() -> int:
    work_root = storage.WORK_DIR
    if not work_root.exists():
        return 0

    task_ids = [path.name for path in work_root.iterdir() if path.is_dir()]
    successful_task_ids = db.list_successful_speaker_task_ids(task_ids)
    cleaned = 0
    for task_id in successful_task_ids:
        path = storage.task_work_path(task_id)
        if not path.exists():
            continue
        shutil.rmtree(path, ignore_errors=True)
        cleaned += 1
        log.info("speaker task=%s removed successful task work dir=%s", task_id, path)
    return cleaned


def _serial_tts_runner(tts_executor: ThreadPoolExecutor) -> TtsRunner:
    def run(*args, **kwargs) -> Path:
        return tts_executor.submit(generate_tts_segment, *args, **kwargs).result()

    return run


def _process_claimed_segment(claimed: dict, tts_executor: ThreadPoolExecutor) -> None:
    task_id = claimed["task_id"]
    item_index = int(claimed["item_index"])
    total_started_at = time.perf_counter()
    log.info("speaker timing task=%s index=%d step=segment_started at=%s", task_id, item_index, _timestamp())
    try:
        step_started_at = time.perf_counter()
        reference, output = handle_segment(claimed, _serial_tts_runner(tts_executor))
        _log_segment_timing(task_id, item_index, "handle_returned", step_started_at, total_started_at)
        step_started_at = time.perf_counter()
        reference_path, reference_url, output_path, output_url = publish_segment_outputs(
            task_id,
            reference,
            output,
        )
        _log_segment_timing(task_id, item_index, "published_outputs", step_started_at, total_started_at)
        step_started_at = time.perf_counter()
        db.mark_speaker_segment_success(
            int(claimed["id"]),
            reference_path,
            reference_url,
            output_path,
            output_url,
        )
        _log_segment_timing(task_id, item_index, "db_marked_success", step_started_at, total_started_at)
        step_started_at = time.perf_counter()
        finalizable = db.find_finalizable_speaker_task(task_id)
        _log_segment_timing(task_id, item_index, "finalizable_checked", step_started_at, total_started_at)
        if finalizable:
            step_started_at = time.perf_counter()
            finalize_task(finalizable)
            _log_segment_timing(task_id, item_index, "task_finalized", step_started_at, total_started_at)
        _log_segment_timing(task_id, item_index, "segment_completed", total_started_at, total_started_at)
    except Exception as exc:
        _log_segment_timing(task_id, item_index, "segment_failed", total_started_at, total_started_at)
        log.exception("speaker segment failed task=%s index=%d", task_id, item_index)
        step_started_at = time.perf_counter()
        exhausted = db.mark_speaker_segment_failed(int(claimed["id"]), str(exc))
        _log_segment_timing(
            task_id,
            item_index,
            "db_marked_failed",
            step_started_at,
            total_started_at,
            exhausted=exhausted,
        )
        if exhausted:
            step_started_at = time.perf_counter()
            failed = db.find_terminal_failed_speaker_task(task_id)
            _log_segment_timing(task_id, item_index, "terminal_failure_checked", step_started_at, total_started_at)
            if failed:
                step_started_at = time.perf_counter()
                db.mark_speaker_failed_from_segment(
                    failed["task_id"],
                    failed["error_message"],
                    str(failed.get("sub_stage") or db.SPEAKER_MAIN_SUB_STAGE),
                )
                _log_segment_timing(task_id, item_index, "task_marked_failed", step_started_at, total_started_at)


def _collect_finished_segments(inflight: dict[Future, dict]) -> int:
    completed = 0
    for future in list(inflight):
        if not future.done():
            continue
        claimed = inflight.pop(future)
        completed += 1
        try:
            future.result()
        except Exception:
            log.exception(
                "speaker segment worker crashed task=%s index=%s",
                claimed.get("task_id"),
                claimed.get("item_index"),
            )
    return completed


def _claim_ready_segments(
    inflight: dict[Future, dict],
    segment_executor: ThreadPoolExecutor,
    tts_executor: ThreadPoolExecutor,
    max_inflight: int,
) -> int:
    claimed_count = 0
    while len(inflight) < max_inflight:
        row = db.find_ready_speaker_segment()
        if not row:
            break
        claimed = db.claim_speaker_segment(int(row["id"]))
        if not claimed:
            continue
        future = segment_executor.submit(_process_claimed_segment, claimed, tts_executor)
        inflight[future] = claimed
        claimed_count += 1
    return claimed_count


def run_segment_worker() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.ensure_speaker_segment_schema()
    db.ensure_speaker_profile_schema()
    max_inflight = max(1, SPEAKER_MAX_IN_FLIGHT_SEGMENTS)
    tts_concurrency = max(1, SPEAKER_TTS_CONCURRENCY)
    log.info(
        "speaker service started; polling segments every %ss max_inflight=%d tts_concurrency=%d",
        POLL_INTERVAL_SECONDS,
        max_inflight,
        tts_concurrency,
    )
    next_cleanup_at = 0.0
    with (
        ThreadPoolExecutor(max_workers=max_inflight, thread_name_prefix="speaker-segment") as segment_executor,
        ThreadPoolExecutor(max_workers=tts_concurrency, thread_name_prefix="speaker-tts") as tts_executor,
    ):
        inflight: dict[Future, dict] = {}
        while True:
            did_work = False
            try:
                db.record_service_poll(SERVICE_NAME)
                if _collect_finished_segments(inflight):
                    did_work = True
                now = time.monotonic()
                if now >= next_cleanup_at:
                    cleaned = cleanup_successful_task_work_dirs()
                    if cleaned:
                        log.info("speaker cleaned %d successful task work dir(s)", cleaned)
                    next_cleanup_at = now + _CLEANUP_INTERVAL_SECONDS
                if not inflight:
                    recycled, _exhausted_task_ids = db.recycle_stale_speaker_segments()
                    if recycled:
                        log.warning("speaker recycled %d stale running/failed segment(s)", recycled)
                        did_work = True
                initialized = db.initialize_ready_speaker_task()
                if initialized:
                    task_id, segment_count = initialized
                    if segment_count == 0:
                        db.mark_failed(
                            SERVICE_NAME,
                            task_id,
                            f"speaker input text is empty for task: {task_id}",
                            db.SPEAKER_NARRATION_SUB_STAGE
                            if task_id.startswith("narration-")
                            else db.SPEAKER_MAIN_SUB_STAGE,
                        )
                        did_work = True
                        continue
                    log.info("speaker task=%s initialized %d segment(s)", task_id, segment_count)
                    did_work = True
                finalizable = db.find_finalizable_speaker_task()
                if finalizable:
                    finalize_task(finalizable)
                    did_work = True
                    continue

                blessing = db.claim_ready_blessing_task()
                if blessing:
                    try:
                        process_blessing_task(blessing)
                    except Exception as exc:
                        log.exception("speaker blessing failed task=%s", blessing.get("task_id"))
                        db.mark_blessing_failed(str(blessing.get("task_id")), str(exc))
                    did_work = True
                    continue

                failed = db.find_terminal_failed_speaker_task()
                if failed:
                    db.mark_speaker_failed_from_segment(
                        failed["task_id"],
                        failed["error_message"],
                        str(failed.get("sub_stage") or db.SPEAKER_MAIN_SUB_STAGE),
                    )
                    did_work = True
                    continue

                if _claim_ready_segments(inflight, segment_executor, tts_executor, max_inflight):
                    did_work = True
            except Exception as exc:
                if db.is_mysql_connection_error(exc):
                    log.warning(
                        "speaker failed to poll segment queue: network connection failed; retrying in %ss",
                        POLL_INTERVAL_SECONDS,
                    )
                else:
                    log.exception("speaker failed to poll segment queue; retrying in %ss", POLL_INTERVAL_SECONDS)
            if not did_work:
                time.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    run_segment_worker()


if __name__ == "__main__":
    main()
