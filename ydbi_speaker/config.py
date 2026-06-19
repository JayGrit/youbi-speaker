from __future__ import annotations

import os
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YDBI_ROOT = SERVICE_ROOT.parents[1] if SERVICE_ROOT.parent.name == "services" else SERVICE_ROOT
YDBI_ROOT = DEFAULT_YDBI_ROOT


MYSQL_CONFIG = {
    "host": "120.53.92.66",
    "port": 3306,
    "user": "hoshuuch",
    "password": "490229",
    "database": "youbi",
}

STORAGE_BACKEND = "minio"
MINIO_ENDPOINT = "http://120.53.92.66:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
MINIO_BUCKET = "ydbi"
MINIO_PUBLIC_BASE = "/minio"
MINIO_FULL_BASE_URL = "https://120.53.92.66/minio"
MINIO_SECURE = False

def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if value:
        return Path(value).expanduser()
    return default.expanduser()


def _local_work_root() -> Path:
    explicit = os.getenv("WORKFOLDER") or os.getenv("YDBI_WORK_ROOT")
    if explicit:
        return Path(explicit).expanduser()

    docker_work = Path("/work")
    if docker_work.exists() and os.access(docker_work, os.W_OK):
        return docker_work

    return YDBI_ROOT / "workfolder"


WORK_ROOT = _local_work_root()
WORKFOLDER = WORK_ROOT

MODEL_CACHE_DIR = _path_from_env("MODELSCOPE_CACHE", SERVICE_ROOT / "model")
VOXCPM_MODEL_DIR = str(_path_from_env("VOXCPM_MODEL_DIR", MODEL_CACHE_DIR / "VoxCPM2"))

WORK_DIR = WORK_ROOT / "speaker"
POLL_INTERVAL_SECONDS = 10
SEGMENT_RUNNING_TIMEOUT_SECONDS = 3 * 60
NARRATION_SEGMENT_RUNNING_TIMEOUT_SECONDS = 10 * 60
NARRATION_REFERENCE_AUDIO_URL = os.getenv(
    "NARRATION_REFERENCE_AUDIO_URL",
    "http://120.53.92.66:9000/ydbi/assets/voice/history-story-deep-male.wav",
)

VOXCPM_MODEL = "OpenBMB/VoxCPM2"
VOXCPM_LOAD_DENOISER = False
VOXCPM_OPTIMIZE = False
VOXCPM_MIN_REFERENCE_MS = 1200
VOXCPM_CFG_VALUE = 2.0
VOXCPM_INFERENCE_TIMESTEPS = 10
