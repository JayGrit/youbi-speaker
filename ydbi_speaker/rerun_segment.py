from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ydbi_speaker import db, storage
from ydbi_speaker.main import handle_dubbing_multi_segment, publish_segment_outputs


log = logging.getLogger(__name__)


def _segment_cache_paths(task_id: str, item_index: int) -> list[Path]:
    session = storage.task_work_dir(task_id)
    filename = f"{item_index + 1:04d}.wav"
    return [
        session / "input" / "vocals.wav",
        session / "input" / "vocals.webm",
        session / "segments" / "tts" / filename,
        session / "segments" / "tts_adjusted" / filename,
    ]


def clear_segment_cache(task_id: str, item_index: int) -> None:
    for path in _segment_cache_paths(task_id, item_index):
        if path.exists():
            path.unlink()
            log.info("removed cached segment file: %s", path)


def _local_ref(path: str | Path) -> str:
    local_path = Path(path).expanduser().resolve()
    if not local_path.exists() or local_path.stat().st_size <= 0:
        raise FileNotFoundError(f"local vocals file does not exist or is empty: {local_path}")
    return f"local:{local_path}"


def rerun_dubbing_multi_segment(
    task_id: str,
    item_index: int,
    *,
    clear_cache: bool = True,
    vocals_path: str | Path | None = None,
) -> dict[str, str]:
    row = db.get_speaker_segment(task_id, item_index)
    if not row:
        raise RuntimeError(f"speaker_segment not found: task_id={task_id} item_index={item_index}")
    if row.get("speaker_sub_stage") != db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE:
        raise RuntimeError(
            "rerun_segment only supports speaker sub_stage="
            f"{db.SPEAKER_DUBBING_MULTI_SEGMENT_SUB_STAGE}; got {row.get('speaker_sub_stage')}"
        )

    if clear_cache:
        clear_segment_cache(task_id, item_index)
    if vocals_path:
        row["audio_vocals_url"] = _local_ref(vocals_path)
        row["audio_source_url"] = ""

    reference, output = handle_dubbing_multi_segment(row)
    reference_path, reference_url, output_path, output_url = publish_segment_outputs(task_id, reference, output)
    db.mark_speaker_segment_success(int(row["id"]), reference_path, reference_url, output_path, output_url)
    return {
        "task_id": task_id,
        "item_index": str(item_index),
        "reference_url": reference_url,
        "tts_url": output_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Rerun one dubbing_multi_segment speaker segment and write DB outputs.")
    parser.add_argument("task_id")
    parser.add_argument("item_index", type=int, help="Zero-based speaker_segment.item_index. 0005.wav is item_index 4.")
    parser.add_argument("--keep-cache", action="store_true", help="Reuse local cached segment files if present.")
    parser.add_argument("--vocals", help="Local audio_vocals.wav path to use instead of the DB/MinIO vocals URL.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = rerun_dubbing_multi_segment(
        args.task_id,
        args.item_index,
        clear_cache=not args.keep_cache,
        vocals_path=args.vocals,
    )
    print(f"rerun complete: task_id={result['task_id']} item_index={result['item_index']}")
    print(f"reference_url={result['reference_url']}")
    print(f"tts_url={result['tts_url']}")


if __name__ == "__main__":
    main()
