from __future__ import annotations

import io

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import HTTPError

from apps.api.config import settings


def client() -> Minio:
    return Minio(settings.object_store_endpoint,
                 access_key=settings.object_store_access_key,
                 secret_key=settings.object_store_secret_key,
                 secure=settings.object_store_secure)


def ensure_bucket() -> None:
    store = client()
    if not store.bucket_exists(settings.object_store_bucket):
        store.make_bucket(settings.object_store_bucket)


def storage_ready() -> bool:
    try:
        client().bucket_exists(settings.object_store_bucket)
        return True
    except (S3Error, HTTPError, OSError):
        return False


def put_pdf(object_key: str, data: bytes) -> None:
    ensure_bucket()
    client().put_object(settings.object_store_bucket, object_key, io.BytesIO(data), len(data),
                        content_type="application/pdf")


def get_pdf(object_key: str) -> bytes:
    response = client().get_object(settings.object_store_bucket, object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()
