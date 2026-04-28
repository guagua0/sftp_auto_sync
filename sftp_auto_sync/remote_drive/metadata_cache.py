from __future__ import annotations

import threading
import time

from sftp_auto_sync.remote_drive.models import MetadataCacheEntry


class MetadataCache:
    def __init__(self, ttl_sec: int = 10):
        self._ttl_sec = ttl_sec
        self._dir_index: dict[str, MetadataCacheEntry] = {}
        self._stat_index: dict[str, MetadataCacheEntry] = {}
        self._guard = threading.RLock()

    def get_dir(self, remote_dir: str):
        with self._guard:
            return self._get(self._dir_index, remote_dir)

    def set_dir(self, remote_dir: str, entries, *, ttl_sec: int | None = None) -> None:
        with self._guard:
            self._dir_index[remote_dir] = MetadataCacheEntry(entries, self._expires_at(ttl_sec))

    def invalidate_dir(self, remote_dir: str) -> None:
        with self._guard:
            self._dir_index.pop(remote_dir, None)

    def get_stat(self, remote_path: str):
        with self._guard:
            return self._get(self._stat_index, remote_path)

    def set_stat(self, remote_path: str, entry, *, ttl_sec: int | None = None) -> None:
        with self._guard:
            self._stat_index[remote_path] = MetadataCacheEntry(entry, self._expires_at(ttl_sec))

    def invalidate_stat(self, remote_path: str) -> None:
        with self._guard:
            self._stat_index.pop(remote_path, None)

    def clear(self) -> None:
        with self._guard:
            self._dir_index.clear()
            self._stat_index.clear()

    def _expires_at(self, ttl_sec: int | None) -> float:
        ttl = self._ttl_sec if ttl_sec is None else ttl_sec
        return time.time() + ttl

    @staticmethod
    def _get(index: dict[str, MetadataCacheEntry], key: str):
        entry = index.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            index.pop(key, None)
            return None
        return entry.value
