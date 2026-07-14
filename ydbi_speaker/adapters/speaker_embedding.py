from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ydbi_speaker.adapters.speechbrain_compat import suppress_optional_speechbrain_integrations
from ydbi_speaker.config import SPEECHBRAIN_SPEAKER_MODEL, SPEECHBRAIN_SPEAKER_MODEL_DIR

_ENCODER = None
_ENCODER_LOCK = threading.RLock()


def _model_source_and_savedir() -> tuple[str, str]:
    model_dir = SPEECHBRAIN_SPEAKER_MODEL_DIR.expanduser()
    if (model_dir / "hyperparams.yaml").exists():
        return str(model_dir), str(model_dir)
    return SPEECHBRAIN_SPEAKER_MODEL, str(model_dir)


def _load_encoder():
    global _ENCODER
    with _ENCODER_LOCK:
        if _ENCODER is None:
            suppress_optional_speechbrain_integrations()
            try:
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError:
                from speechbrain.pretrained import EncoderClassifier

            suppress_optional_speechbrain_integrations()
            source, savedir = _model_source_and_savedir()
            _ENCODER = EncoderClassifier.from_hparams(
                source=source,
                savedir=savedir,
            )
            suppress_optional_speechbrain_integrations()
    return _ENCODER


def embedding(path: Path) -> np.ndarray:
    with _ENCODER_LOCK:
        encoder = _load_encoder()
        if hasattr(encoder, "encode_file"):
            encoded = encoder.encode_file(str(path))
        else:
            audio = encoder.load_audio(str(path))
            encoded = encoder.encode_batch(audio.unsqueeze(0))
    if hasattr(encoded, "detach"):
        encoded = encoded.detach().cpu().numpy()
    return np.asarray(encoded, dtype=np.float32).reshape(-1)


def save_embedding(path: Path, value: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, value)
