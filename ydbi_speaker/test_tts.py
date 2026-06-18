from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from ydbi_speaker.config import WORK_DIR


def synthesize_from_reference(
    reference_audio_path: str | Path,
    text_file_path: str | Path,
    output_path: str | Path | None = None,
) -> Path:
    """Generate a test TTS WAV using the same VoxCPM path as production segments."""
    from ydbi_speaker.adapters.voxcpm import generate_tts_segment

    reference = Path(reference_audio_path).expanduser().resolve()
    if not reference.exists() or not reference.is_file():
        raise FileNotFoundError(f"reference audio file does not exist: {reference}")
    if reference.suffix.lower() != ".wav":
        raise ValueError("reference audio must be a WAV file")

    text_file = Path(text_file_path).expanduser().resolve()
    if not text_file.exists() or not text_file.is_file():
        raise FileNotFoundError(f"text file does not exist: {text_file}")
    text = text_file.read_text(encoding="utf-8").strip()

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    session = WORK_DIR / "manual-test" / run_id
    generated = generate_tts_segment(text, 0, reference, reference, session)

    if output_path is None:
        return generated

    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated, output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a test speaker WAV from a reference WAV and text file.")
    parser.add_argument("reference_audio_path", help="Path to the reference WAV.")
    parser.add_argument("text_file_path", help="Path to a UTF-8 text file to synthesize.")
    parser.add_argument("-o", "--output", dest="output_path", help="Output WAV path.")
    args = parser.parse_args()

    output = synthesize_from_reference(args.reference_audio_path, args.text_file_path, args.output_path)
    print(output)


if __name__ == "__main__":
    main()
