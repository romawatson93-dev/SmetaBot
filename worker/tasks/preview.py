from __future__ import annotations

import base64
import os
import uuid
from typing import Any, Dict, Optional

import redis
from celery import shared_task

from common.preview import PreviewError, generate_preview

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PREVIEW_BLOB_TTL = int(os.getenv("PREVIEW_BLOB_TTL", os.getenv("SOURCE_BLOB_TTL", "3600")))
FULLRES_BLOB_PREFIX = os.getenv("FULLRES_BLOB_PREFIX", "renderpng")
FULLRES_BLOB_TTL = int(os.getenv("FULLRES_BLOB_TTL", os.getenv("SOURCE_BLOB_TTL", "3600")))
_storage = redis.Redis.from_url(REDIS_URL)


def _store_preview(payload: bytes) -> str:
    key = f"preview:{uuid.uuid4().hex}"
    _storage.set(key, payload, ex=PREVIEW_BLOB_TTL)
    return key


def _store_fullres(payload: bytes) -> str:
    key = f"{FULLRES_BLOB_PREFIX}:{uuid.uuid4().hex}"
    _storage.set(key, payload, ex=FULLRES_BLOB_TTL)
    return key


def _load_source_blob(key: str) -> bytes:
    if not key:
        raise PreviewError("Storage key is empty.")
    try:
        data = _storage.get(key)
    except Exception as exc:  # pragma: no cover - redis failure path
        raise PreviewError(f"Failed to load source blob from Redis ({key}): {exc}") from exc
    if data is None:
        raise PreviewError(f"Blob {key} is missing or expired.")
    return data


@shared_task
def generate_preview_task(
    *,
    file_b64: str = "",
    file_key: Optional[str] = None,
    filename: str,
    render_format: str,
) -> Dict[str, Any]:
    """Generate preview pages for a document."""
    try:
        if file_key:
            file_bytes = _load_source_blob(file_key)
        elif file_b64:
            file_bytes = base64.b64decode(file_b64)
        else:
            raise PreviewError("No payload provided for preview generation.")
    except Exception as exc:  # pragma: no cover - invalid input
        raise PreviewError(f"Failed to decode source document: {exc}") from exc

    result = generate_preview(file_bytes, filename, render_format)
    pages_meta: list[Dict[str, Any]] = []
    for entry in result.get("pages", []):
        preview_bytes = entry.get("preview_bytes")
        fullres_bytes = entry.get("fullres_bytes")
        if not preview_bytes:
            continue
        preview_key = _store_preview(preview_bytes)
        meta = {
            k: v
            for k, v in entry.items()
            if k not in {"preview_bytes", "fullres_bytes"}
        }
        meta["preview_key"] = preview_key
        if fullres_bytes:
            meta["fullres_key"] = _store_fullres(fullres_bytes)
        pages_meta.append(meta)

    return {"pages": pages_meta, "analysis": result.get("analysis", {})}


__all__ = ["generate_preview_task"]
