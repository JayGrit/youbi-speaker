from __future__ import annotations

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

WORK_ROOT = Path("/work").expanduser()
WORKFOLDER = WORK_ROOT
MODEL_CACHE_DIR = Path("/models/modelscope").expanduser()
VOXCPM_MODEL_DIR = str(Path("/models/VoxCPM2").expanduser())

WORK_DIR = WORK_ROOT / "speaker"
POLL_INTERVAL_SECONDS = 10
SEGMENT_RUNNING_TIMEOUT_SECONDS = 3 * 60

VOXCPM_MODEL = "OpenBMB/VoxCPM2"
VOXCPM_LOAD_DENOISER = False
VOXCPM_OPTIMIZE = False
VOXCPM_MIN_REFERENCE_MS = 1200
VOXCPM_CFG_VALUE = 2.0
VOXCPM_INFERENCE_TIMESTEPS = 10
