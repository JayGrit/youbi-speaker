from __future__ import annotations

import os
import tempfile
from pathlib import Path


IN_CONTAINER = Path("/.dockerenv").exists()
SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_YDBI_ROOT = SERVICE_ROOT.parents[1] if SERVICE_ROOT.parent.name == "services" else SERVICE_ROOT
YDBI_ROOT = Path(os.environ.get("YDBI_ROOT", DEFAULT_YDBI_ROOT)).expanduser()
PROJECT_MODEL_CACHE_DIR = SERVICE_ROOT / "data" / "modelscope"


def _path_from_env(name: str, default: Path | str) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


def _value_from_env(name: str, default: Path | str) -> str:
    return str(Path(os.environ.get(name, str(default))).expanduser())


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


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

if IN_CONTAINER:
    WORK_ROOT = _path_from_env("YDBI_WORK_DIR", "/work")
    WORKFOLDER = _path_from_env("WORKFOLDER", WORK_ROOT)
    MODEL_CACHE_DIR = _path_from_env("MODEL_CACHE_DIR", "/models/modelscope")
    VOXCPM_MODEL_DIR = _value_from_env("VOXCPM_MODEL_DIR", "/models/VoxCPM2")
else:
    WORK_ROOT = _path_from_env("YDBI_WORK_DIR", DEFAULT_YDBI_ROOT / "workfolder")
    WORKFOLDER = _path_from_env("WORKFOLDER", WORK_ROOT)
    MODEL_CACHE_DIR = _path_from_env("MODEL_CACHE_DIR", PROJECT_MODEL_CACHE_DIR)
    VOXCPM_MODEL_DIR = _value_from_env("VOXCPM_MODEL_DIR", MODEL_CACHE_DIR / "OpenBMB__VoxCPM2")

WORK_DIR = Path(os.environ.get("YDBI_SPEAKER_WORK_DIR", WORK_ROOT / "speaker")).expanduser()
POLL_INTERVAL_SECONDS = 10
SEGMENT_RUNNING_TIMEOUT_SECONDS = _int_from_env("YDBI_SPEAKER_SEGMENT_TIMEOUT_SECONDS", 180)

VOXCPM_MODEL = "OpenBMB/VoxCPM2"
VOXCPM_LOAD_DENOISER = False
VOXCPM_OPTIMIZE = _bool_from_env("VOXCPM_OPTIMIZE", False)
VOXCPM_MIN_REFERENCE_MS = 1200
VOXCPM_CFG_VALUE = 2.0
VOXCPM_INFERENCE_TIMESTEPS = 10
