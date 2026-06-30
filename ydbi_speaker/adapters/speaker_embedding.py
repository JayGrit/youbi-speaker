from __future__ import annotations

from pathlib import Path

import numpy as np

from ydbi_speaker.adapters.speechbrain_compat import suppress_optional_k2_lazy_import
from ydbi_speaker.config import MODEL_CACHE_DIR

_ENCODER = None


def _load_encoder():
    global _ENCODER
    if _ENCODER is None:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:
            from speechbrain.pretrained import EncoderClassifier

        suppress_optional_k2_lazy_import()
        _ENCODER = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(MODEL_CACHE_DIR / "speechbrain-spkrec-ecapa-voxceleb"),
        )
        suppress_optional_k2_lazy_import()
    return _ENCODER


def embedding(path: Path) -> np.ndarray:
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
