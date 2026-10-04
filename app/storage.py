"""Audio storage. LocalStorage (default, ./data/audio) or MinioStorage (STORAGE_BACKEND=minio)."""
import os
import tempfile
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Iterator

from app.config import ROOT, get_settings


class Storage:
    def save(self, key: str, data: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...

    @contextmanager
    def local_path(self, key: str) -> Iterator[str]:
        """A filesystem path for the object (temp copy for remote backends)."""
        suffix = Path(key).suffix
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.read(key))
            yield tmp
        finally:
            os.unlink(tmp)


class LocalStorage(Storage):
    def __init__(self, base: str):
        p = Path(base)
        self.base = p if p.is_absolute() else ROOT / p
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.base / key).resolve()
        if self.base.resolve() not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def save(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    @contextmanager
    def local_path(self, key: str) -> Iterator[str]:
        yield str(self._path(key))


class MinioStorage(Storage):
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        from minio import Minio  # optional dependency

        secure = endpoint.startswith("https://")
        endpoint = endpoint.removeprefix("https://").removeprefix("http://")
        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self.bucket = bucket
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)

    def save(self, key: str, data: bytes) -> str:
        import io

        self.client.put_object(self.bucket, key, io.BytesIO(data), len(data))
        return key

    def read(self, key: str) -> bytes:
        resp = self.client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def exists(self, key: str) -> bool:
        try:
            self.client.stat_object(self.bucket, key)
            return True
        except Exception:
            return False


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "minio":
        return MinioStorage(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, s.minio_bucket)
    return LocalStorage(s.audio_dir)
