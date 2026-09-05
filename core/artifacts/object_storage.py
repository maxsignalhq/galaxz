"""Pluggable storage for artifact payloads.

Metadata belongs in the operational database; this module owns immutable
payload bytes and returns a stable object reference for that metadata.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ObjectStorageError(RuntimeError):
    """Raised when an object cannot be safely published or read."""


@dataclass(frozen=True)
class ObjectMetadata:
    object_id: str
    content_hash: str
    size_bytes: int
    media_type: str


class ObjectStorage(Protocol):
    def put(self, object_id: str, content: bytes, *, media_type: str | None = None) -> ObjectMetadata: ...
    def get(self, object_id: str) -> bytes: ...
    def delete(self, object_id: str) -> None: ...
    def list_ids(self) -> list[str]: ...


def _metadata(object_id: str, content: bytes, media_type: str | None) -> ObjectMetadata:
    return ObjectMetadata(
        object_id=object_id,
        content_hash=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        media_type=media_type or "application/octet-stream",
    )


class LocalObjectStorage:
    """Filesystem backend using temp-file plus atomic rename publication."""

    def __init__(self, root: str, *, max_size_bytes: int = 50 * 1024 * 1024):
        self.root = Path(root).resolve()
        self.max_size_bytes = max_size_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, object_id: str) -> Path:
        if not object_id or object_id.startswith("/"):
            raise ValueError("object_id must be a non-empty relative key")
        path = (self.root / object_id).resolve()
        if self.root != path and self.root not in path.parents:
            raise ValueError("object_id escapes the object storage root")
        return path

    def put(self, object_id: str, content: bytes, *, media_type: str | None = None) -> ObjectMetadata:
        if len(content) > self.max_size_bytes:
            raise ObjectStorageError("object exceeds configured size limit")
        target = self._path(object_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".upload-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except OSError as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise ObjectStorageError("object publication failed") from exc
        return _metadata(object_id, content, media_type or mimetypes.guess_type(object_id)[0])

    def get(self, object_id: str) -> bytes:
        try:
            return self._path(object_id).read_bytes()
        except OSError as exc:
            raise ObjectStorageError("object read failed") from exc

    def delete(self, object_id: str) -> None:
        try:
            self._path(object_id).unlink()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ObjectStorageError("object deletion failed") from exc

    def list_ids(self) -> list[str]:
        return [str(path.relative_to(self.root)) for path in self.root.rglob("*") if path.is_file() and not path.name.startswith(".upload-")]


class S3ObjectStorage:
    """S3-compatible backend; boto3 is imported only when this backend is used."""

    def __init__(self, bucket: str, *, prefix: str = "", endpoint_url: str | None = None, client=None, max_size_bytes: int = 50 * 1024 * 1024):
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.max_size_bytes = max_size_bytes
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ObjectStorageError("S3 storage requires the optional boto3 dependency") from exc
            client = boto3.client("s3", endpoint_url=endpoint_url)
        self.client = client

    def _key(self, object_id: str) -> str:
        if not object_id or object_id.startswith("/") or ".." in Path(object_id).parts:
            raise ValueError("object_id must be a safe relative key")
        return f"{self.prefix}/{object_id}" if self.prefix else object_id

    def put(self, object_id: str, content: bytes, *, media_type: str | None = None) -> ObjectMetadata:
        if len(content) > self.max_size_bytes:
            raise ObjectStorageError("object exceeds configured size limit")
        metadata = _metadata(object_id, content, media_type or mimetypes.guess_type(object_id)[0])
        try:
            self.client.put_object(Bucket=self.bucket, Key=self._key(object_id), Body=content, ContentType=metadata.media_type, Metadata={"sha256": metadata.content_hash})
        except Exception as exc:
            raise ObjectStorageError("object publication failed") from exc
        return metadata

    def get(self, object_id: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(object_id))["Body"].read()
        except Exception as exc:
            raise ObjectStorageError("object read failed") from exc

    def delete(self, object_id: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(object_id))
        except Exception as exc:
            raise ObjectStorageError("object deletion failed") from exc

    def list_ids(self) -> list[str]:
        try:
            response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=f"{self.prefix}/" if self.prefix else "")
        except Exception as exc:
            raise ObjectStorageError("object listing failed") from exc
        prefix = f"{self.prefix}/" if self.prefix else ""
        return [key["Key"][len(prefix):] for key in response.get("Contents", []) if key["Key"].startswith(prefix)]


class ArtifactAccessPolicy:
    """Explicit ownership check for artifact downloads."""

    def authorize(self, *, artifact_project_id: str | None, artifact_organization_id: str | None, project_id: str | None, organization_id: str | None) -> None:
        if artifact_project_id and artifact_project_id != project_id:
            raise PermissionError("artifact is outside the requested project scope")
        if artifact_organization_id and artifact_organization_id != organization_id:
            raise PermissionError("artifact is outside the requested organization scope")


def object_storage_from_environment() -> ObjectStorage | None:
    """Build the explicitly configured payload backend, or keep inline storage."""
    backend = os.getenv("GALAXZ_ARTIFACT_STORAGE", "inline").lower()
    if backend == "inline":
        return None
    max_size = int(os.getenv("GALAXZ_ARTIFACT_MAX_BYTES", str(50 * 1024 * 1024)))
    if backend == "local":
        return LocalObjectStorage(os.getenv("GALAXZ_ARTIFACT_STORAGE_ROOT", "data/artifacts"), max_size_bytes=max_size)
    if backend == "s3":
        return S3ObjectStorage(
            os.environ["GALAXZ_ARTIFACT_S3_BUCKET"],
            prefix=os.getenv("GALAXZ_ARTIFACT_S3_PREFIX", ""),
            endpoint_url=os.getenv("GALAXZ_ARTIFACT_S3_ENDPOINT"),
            max_size_bytes=max_size,
        )
    raise ValueError("GALAXZ_ARTIFACT_STORAGE must be inline, local or s3")
