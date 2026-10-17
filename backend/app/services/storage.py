"""Evidence file storage: local folder in development, Cloud Storage on GCP. Files are write-once."""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from app.config import get_settings

ALLOWED_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "application/pdf": ".pdf", "text/plain": ".txt"}


class StorageError(Exception):
    pass


def sniff_mime(data: bytes, declared: str | None, filename: str) -> str:
    """Trust file signatures over the declared type."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if (declared or "").startswith("text/") or filename.lower().endswith(".txt"):
        try:
            data[:4096].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    raise StorageError("Unsupported file type. Allowed: PNG, JPEG, PDF, plain text.")


class LocalStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, data: bytes, case_id: str, mime: str) -> str:
        name = f"{case_id}/{uuid.uuid4().hex}{ALLOWED_MIME.get(mime, '.bin')}"
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as f:  # exclusive create: never overwrite
            f.write(data)
        return f"local://{name}"

    def _path(self, uri: str) -> Path:
        if not uri.startswith("local://"):
            raise StorageError("not a local uri")
        path = (self.root / uri[len("local://"):]).resolve()
        if self.root.resolve() not in path.parents:
            raise StorageError("invalid path")
        return path

    def get(self, uri: str) -> bytes:
        return self._path(uri).read_bytes()

    def delete(self, uri: str) -> None:
        self._path(uri).unlink(missing_ok=True)


class GCSStorage:
    def __init__(self, bucket: str):
        from google.cloud import storage  # imported lazily

        self.bucket = storage.Client().bucket(bucket)
        self.bucket_name = bucket

    def put(self, data: bytes, case_id: str, mime: str) -> str:
        name = f"evidence/{case_id}/{uuid.uuid4().hex}{ALLOWED_MIME.get(mime, '.bin')}"
        blob = self.bucket.blob(name)
        blob.upload_from_string(data, content_type=mime, if_generation_match=0)  # write-once
        return f"gs://{self.bucket_name}/{name}"

    def get(self, uri: str) -> bytes:
        prefix = f"gs://{self.bucket_name}/"
        if not uri.startswith(prefix):
            raise StorageError("uri not in configured bucket")
        return self.bucket.blob(uri[len(prefix):]).download_as_bytes()

    def delete(self, uri: str) -> None:
        prefix = f"gs://{self.bucket_name}/"
        if not uri.startswith(prefix):
            raise StorageError("uri not in configured bucket")
        blob = self.bucket.blob(uri[len(prefix):])
        if blob.exists():
            blob.delete()


_storage = None


def get_storage():
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = GCSStorage(s.gcs_bucket) if s.storage_backend == "gcs" and s.gcs_bucket else LocalStorage(s.local_upload_dir)
    return _storage


def reset_storage(instance=None) -> None:
    global _storage
    _storage = instance


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
