from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


class ContentCache:
    def __init__(self, cache_root: str | Path, mount_key: str):
        self._base_dir = Path(cache_root) / 'remote_drives' / mount_key
        self._files_dir = self._base_dir / 'files'
        self._tmp_dir = self._base_dir / 'tmp'
        self._files_dir.mkdir(parents=True, exist_ok=True)
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def reset(self) -> None:
        if self._base_dir.exists():
            shutil.rmtree(self._base_dir, ignore_errors=True)
        self._files_dir.mkdir(parents=True, exist_ok=True)
        self._tmp_dir.mkdir(parents=True, exist_ok=True)

    def cache_path_for(self, remote_path: str) -> Path:
        digest = hashlib.sha1(remote_path.encode('utf-8')).hexdigest()
        return self._files_dir / f'{digest}.bin'

    def temp_path_for(self, remote_path: str) -> Path:
        digest = hashlib.sha1(remote_path.encode('utf-8')).hexdigest()
        return self._tmp_dir / f'{digest}.tmp'

    def has_cached_file(self, remote_path: str) -> bool:
        return self.cache_path_for(remote_path).exists()

    def write_bytes_atomic(self, remote_path: str, payload: bytes) -> Path:
        temp_path = self.temp_path_for(remote_path)
        cache_path = self.cache_path_for(remote_path)
        temp_path.write_bytes(payload)
        os.replace(temp_path, cache_path)
        return cache_path

    def commit_download(self, remote_path: str, temp_path: str | Path) -> Path:
        src = Path(temp_path)
        cache_path = self.cache_path_for(remote_path)
        os.replace(src, cache_path)
        return cache_path

    def rename(self, old_remote_path: str, new_remote_path: str) -> Path | None:
        old_path = self.cache_path_for(old_remote_path)
        new_path = self.cache_path_for(new_remote_path)
        if not old_path.exists():
            return None
        os.replace(old_path, new_path)
        return new_path

    def delete(self, remote_path: str) -> None:
        self.cache_path_for(remote_path).unlink(missing_ok=True)
        self.temp_path_for(remote_path).unlink(missing_ok=True)

    def stat(self, remote_path: str) -> os.stat_result:
        return self.cache_path_for(remote_path).stat()
