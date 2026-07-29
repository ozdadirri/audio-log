"""Object storage (MinIO/S3-compatible) for everything that used to live under
DATA_DIR: source audio, transcript/summary outputs, thumbnails, and transcode
cache. Object keys are the same relative-path strings paths.py already produces
(e.g. "input/foo.mp3", "output/foo-abcd1234/transcript.md"), so existing
source_path/output_dir values in the DB need no reformatting.

ffmpeg and Pillow need a real file on disk, so anything that processes audio
goes through download_to_temp() first and uploads the result back afterward.
"""

import logging
import os
import tempfile
from pathlib import Path

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from . import config

log = logging.getLogger("audiolog")

_client = boto3.client(
    "s3",
    endpoint_url=config.MINIO_URL,
    aws_access_key_id=config.MINIO_ACCESS_KEY,
    aws_secret_access_key=config.MINIO_SECRET_KEY,
    config=BotoConfig(signature_version="s3v4"),
)
BUCKET = config.MINIO_BUCKET


def ensure_bucket():
    try:
        _client.head_bucket(Bucket=BUCKET)
    except ClientError:
        _client.create_bucket(Bucket=BUCKET)


def unique_key(prefix: str, filename: str) -> str:
    """A key under `prefix` guaranteed not to already exist, appending -1, -2,
    ... to the stem on collision (never overwrites an existing object)."""
    base = Path(filename).name
    stem, suffix = Path(base).stem, Path(base).suffix
    candidate = f"{prefix}/{base}"
    counter = 1
    while exists(candidate):
        candidate = f"{prefix}/{stem}-{counter}{suffix}"
        counter += 1
    return candidate


def exists(key: str) -> bool:
    try:
        _client.head_object(Bucket=BUCKET, Key=key)
        return True
    except ClientError:
        return False


def upload(key: str, local_path: Path, content_type: str | None = None):
    extra = {"ContentType": content_type} if content_type else {}
    _client.upload_file(str(local_path), BUCKET, key, ExtraArgs=extra)


def upload_bytes(key: str, data: bytes, content_type: str | None = None):
    extra = {"ContentType": content_type} if content_type else {}
    _client.put_object(Bucket=BUCKET, Key=key, Body=data, **extra)


def upload_text(key: str, text: str, content_type: str = "text/markdown; charset=utf-8"):
    upload_bytes(key, text.encode("utf-8"), content_type=content_type)


def download_bytes(key: str) -> bytes | None:
    try:
        return _client.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except ClientError:
        return None


def download_text(key: str) -> str | None:
    data = download_bytes(key)
    return data.decode("utf-8") if data is not None else None


def download_to_temp(key: str, suffix: str = "") -> Path | None:
    """Fetch an object to a local temp file; caller is responsible for deleting
    it. None if the key doesn't exist."""
    if not exists(key):
        return None
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    tmp = Path(tmp_path)
    try:
        _client.download_file(BUCKET, key, str(tmp))
    except ClientError:
        tmp.unlink(missing_ok=True)
        return None
    finally:
        os.close(fd)
    return tmp


def delete(key: str):
    _client.delete_object(Bucket=BUCKET, Key=key)


def delete_prefix(prefix: str):
    """Delete every object under a key prefix (e.g. an output_dir)."""
    paginator = _client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
        if keys:
            _client.delete_objects(Bucket=BUCKET, Delete={"Objects": keys})


def presigned_url(key: str, expires: int | None = None,
                   filename: str | None = None, content_type: str | None = None) -> str:
    params = {"Bucket": BUCKET, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'inline; filename="{filename}"'
    if content_type:
        params["ResponseContentType"] = content_type
    return _client.generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires or config.MINIO_URL_EXPIRY,
    )
