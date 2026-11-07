"""Storage for voice samples, consent records and outputs: local disk (development) or a private S3 bucket."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from voiceover_studio.providers.base import StorageProvider, StoredObject
from voiceover_studio.providers.registry import register


def _safe_key(key: str) -> str:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not key.strip():
        raise ValueError(f"Invalid storage key: {key!r}")
    return path.as_posix()


@register("storage", "local")
class LocalStorage(StorageProvider):
    def __init__(self, root: str = "data"):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def put(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if metadata:
            path.with_name(path.name + ".meta.json").write_text(json.dumps(metadata), encoding="utf-8")
        return StoredObject(_safe_key(key), len(data), metadata or {})

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        path.with_name(path.name + ".meta.json").unlink(missing_ok=True)

    def list(self, prefix: str) -> list[StoredObject]:
        base = self.root / _safe_key(prefix) if prefix else self.root
        if not base.exists():
            return []
        return [
            StoredObject(p.relative_to(self.root).as_posix(), p.stat().st_size)
            for p in sorted(base.rglob("*"))
            if p.is_file() and not p.name.endswith(".meta.json")
        ]


@register("storage", "s3")
class S3Storage(StorageProvider):
    """Private bucket created by Terraform (encrypted, public access blocked). The instance role can only
    reach this bucket."""

    def __init__(self, bucket: str, region: str = "us-east-1", client=None):
        if not bucket:
            raise ValueError("S3 storage needs a bucket name (set by the deployment).")
        self.bucket = bucket
        if client is None:
            import boto3

            client = boto3.client("s3", region_name=region)
        self._s3 = client

    def put(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> StoredObject:
        key = _safe_key(key)
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data, Metadata=metadata or {})
        return StoredObject(key, len(data), metadata or {})

    def get(self, key: str) -> bytes:
        return self._s3.get_object(Bucket=self.bucket, Key=_safe_key(key))["Body"].read()

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket, Key=_safe_key(key))

    def list(self, prefix: str) -> list[StoredObject]:
        found: list[StoredObject] = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            found += [StoredObject(o["Key"], o["Size"]) for o in page.get("Contents", [])]
        return found
