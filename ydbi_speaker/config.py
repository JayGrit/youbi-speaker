from __future__ import annotations

import os
import tempfile
from pathlib import Path


IN_CONTAINER = Path("/.dockerenv").exists()

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
    WORKFOLDER = Path("/work")
    MODEL_CACHE_DIR = Path("/models/modelscope")
    VOXCPM_MODEL_DIR = "/models/VoxCPM2"
else:
    WORKFOLDER = Path("/Users/hoshuuch/Money/YouBi/workfolder")
    MODEL_CACHE_DIR = Path("/Users/hoshuuch/Money/YouBi/data/modelscope")
    VOXCPM_MODEL_DIR = "/Users/hoshuuch/Money/YouBi/data/modelscope/OpenBMB__VoxCPM2"

WORK_DIR = Path(os.environ.get("YDBI_SPEAKER_WORK_DIR", Path(tempfile.gettempdir()) / "ydbi" / "speaker")).expanduser()
POLL_INTERVAL_SECONDS = 10

VOXCPM_MODEL = "OpenBMB/VoxCPM2"
VOXCPM_LOAD_DENOISER = False
VOXCPM_MIN_REFERENCE_MS = 1200
VOXCPM_CFG_VALUE = 2.0
VOXCPM_INFERENCE_TIMESTEPS = 10
