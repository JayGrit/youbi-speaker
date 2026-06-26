from __future__ import annotations

import shutil
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from .config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_ENDPOINT,
    MINIO_FULL_BASE_URL,
    MINIO_SECRET_KEY,
    MINIO_SECURE,
    STORAGE_BACKEND,
    WORK_DIR,
)


@dataclass(frozen=True)
class ObjectRef:
    bucket: str
    object_name: str


def task_work_dir(task_id: str) -> Path:
    path = task_work_path(task_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_work_path(task_id: str) -> Path:
    return WORK_DIR / task_id


def _endpoint_parts() -> tuple[str, bool]:
    parsed = urlparse(MINIO_ENDPOINT)
    if parsed.scheme:
        return parsed.netloc, parsed.scheme == "https"
    return MINIO_ENDPOINT, MINIO_SECURE


def _minio_client() -> Minio:
    endpoint, secure = _endpoint_parts()
    return Minio(endpoint, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=secure)


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if client.bucket_exists(bucket):
        client.set_bucket_policy(bucket, _public_read_policy(bucket))
        return
    client.make_bucket(bucket)
    client.set_bucket_policy(bucket, _public_read_policy(bucket))


def _public_read_policy(bucket: str) -> str:
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"AWS": ["*"]},
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
    )


def parse_object_ref(ref: str) -> ObjectRef | None:
    value = str(ref or "").strip()
    if not value:
        return None

    parsed = urlparse(value)
    if parsed.scheme == "http" and parsed.hostname == "120.53.92.66" and parsed.port == 9000:
        prefix = f"/{MINIO_BUCKET}/"
        if not parsed.path.startswith(prefix):
            return None
        object_name = parsed.path[len(prefix) :]
        return ObjectRef(MINIO_BUCKET, object_name) if object_name else None

    return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def local_path_object_candidates(ref: str | Path) -> list[str]:
    source = str(ref).strip().removeprefix("local:")
    parsed = urlparse(source)
    if parsed.scheme and parsed.scheme != "file":
        return []

    path_value = parsed.path if parsed.scheme == "file" else source
    if not path_value:
        return []

    path = Path(path_value)
    candidates: list[str] = []
    try:
        candidates.append(str(path.expanduser().resolve().relative_to(WORK_DIR)))
    except (OSError, ValueError):
        pass

    parts = path.parts
    for marker in ("workfolder", "work", "YouBi"):
        if marker in parts:
            index = parts.index(marker)
            candidates.append("/".join(parts[index + 1 :]))

    candidates.append(str(path).lstrip("/"))
    return _unique(candidates)


def object_ref(object_name: str, bucket: str = MINIO_BUCKET) -> str:
    return object_url(object_name, bucket)


def object_url(object_name: str, bucket: str = MINIO_BUCKET) -> str:
    return f"{MINIO_FULL_BASE_URL.rstrip('/')}/{bucket}/{object_name.lstrip('/')}"


def object_prefix(prefix: str, bucket: str = MINIO_BUCKET) -> str:
    normalized = prefix.strip("/")
    return object_url(f"{normalized}/", bucket)


def _download_object(object_info: ObjectRef, destination: Path) -> Path:
    client = _minio_client()
    client.fget_object(object_info.bucket, object_info.object_name, str(destination))
    return destination


def _object_exists(object_info: ObjectRef) -> bool:
    client = _minio_client()
    try:
        client.stat_object(object_info.bucket, object_info.object_name)
        return True
    except S3Error:
        return False


def _object_refs(ref: str | Path, object_candidates: list[str] | tuple[str, ...]) -> list[ObjectRef]:
    source = str(ref)
    refs: list[ObjectRef] = []
    explicit = parse_object_ref(source)
    if explicit:
        refs.append(explicit)
    refs.extend(ObjectRef(MINIO_BUCKET, candidate) for candidate in object_candidates)
    refs.extend(ObjectRef(MINIO_BUCKET, candidate) for candidate in local_path_object_candidates(source))

    seen: set[tuple[str, str]] = set()
    result: list[ObjectRef] = []
    for object_info in refs:
        key = (object_info.bucket, object_info.object_name)
        if key in seen:
            continue
        seen.add(key)
        result.append(object_info)
    return result


def resolve_input_ref(
    ref: str | Path,
    object_candidates: list[str] | tuple[str, ...] = (),
    content_type: str = "application/octet-stream",
) -> str:
    source = str(ref)
    local = Path(source.removeprefix("local:"))

    explicit = parse_object_ref(source)
    if explicit:
        return object_ref(explicit.object_name, explicit.bucket)

    candidates = _object_refs(source, object_candidates)
    if local.exists() and local.stat().st_size > 0:
        if not candidates or STORAGE_BACKEND != "minio":
            return source
        return upload(local, candidates[0].object_name, content_type)

    for object_info in candidates:
        if _object_exists(object_info):
            return object_ref(object_info.object_name, object_info.bucket)

    raise FileNotFoundError(f"input does not exist locally or in minio: {source}")


def download(ref: str | Path, destination: Path, object_candidates: list[str] | tuple[str, ...] = ()) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = str(ref)

    local = Path(source.removeprefix("local:"))
    if local.exists() and local.stat().st_size > 0:
        if local.resolve() != destination.resolve():
            shutil.copy2(local, destination)
        return destination

    errors: list[str] = []
    for object_info in _object_refs(source, object_candidates):
        try:
            return _download_object(object_info, destination)
        except S3Error as exc:
            errors.append(f"{object_url(object_info.object_name, object_info.bucket)}: {exc.code}")

    detail = "; tried minio " + ", ".join(errors) if errors else ""
    raise FileNotFoundError(f"input does not exist locally or in minio: {source}{detail}")


def upload(local_path: Path, object_name: str, content_type: str = "application/octet-stream") -> str:
    if not local_path.exists() or local_path.stat().st_size == 0:
        raise FileNotFoundError(f"output does not exist or is empty: {local_path}")

    if STORAGE_BACKEND != "minio":
        return f"local:{local_path}"

    client = _minio_client()
    _ensure_bucket(client, MINIO_BUCKET)
    normalized = object_name.lstrip("/")
    client.fput_object(MINIO_BUCKET, normalized, str(local_path), content_type=content_type)
    return object_url(normalized)
