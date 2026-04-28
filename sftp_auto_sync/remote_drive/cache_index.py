from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from sftp_auto_sync.remote_drive.models import CachedFileEntry


class CacheIndex:
    def __init__(self):
        self._entries: dict[str, CachedFileEntry] = {}
        self._file_locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    def get(self, remote_path: str) -> CachedFileEntry | None:
        with self._guard:
            return self._entries.get(remote_path)

    def list_entries(self) -> list[CachedFileEntry]:
        with self._guard:
            return list(self._entries.values())

    def upsert(self, entry: CachedFileEntry) -> CachedFileEntry:
        with self._guard:
            self._entries[entry.remote_path] = entry
            self._file_locks.setdefault(entry.remote_path, threading.RLock())
            return entry

    def get_or_create(self, remote_path: str, local_cache_path: str) -> CachedFileEntry:
        with self._guard:
            entry = self._entries.get(remote_path)
            if entry is None:
                entry = CachedFileEntry(
                    remote_path=remote_path,
                    local_cache_path=local_cache_path,
                    downloaded_at=0.0,
                    last_access_at=time.time(),
                )
                self._entries[remote_path] = entry
            self._file_locks.setdefault(remote_path, threading.RLock())
            return entry

    def remove(self, remote_path: str) -> CachedFileEntry | None:
        with self._guard:
            entry = self._entries.pop(remote_path, None)
            self._file_locks.pop(remote_path, None)
            return entry

    def clear(self) -> None:
        with self._guard:
            self._entries.clear()
            self._file_locks.clear()

    def mark_accessed(self, remote_path: str, *, timestamp: float | None = None) -> CachedFileEntry | None:
        with self._guard:
            entry = self._entries.get(remote_path)
            if entry is None:
                return None
            entry.last_access_at = time.time() if timestamp is None else timestamp
            return entry

    def mark_dirty(self, remote_path: str, *, dirty: bool = True, error: str | None = None) -> CachedFileEntry | None:
        with self._guard:
            entry = self._entries.get(remote_path)
            if entry is None:
                return None
            entry.is_dirty = dirty
            entry.last_error = error
            entry.last_access_at = time.time()
            return entry

    def rename(self, old_remote_path: str, new_remote_path: str, new_local_cache_path: str | None = None) -> CachedFileEntry | None:
        with self._guard:
            entry = self._entries.pop(old_remote_path, None)
            lock = self._file_locks.pop(old_remote_path, threading.RLock())
            if entry is None:
                self._file_locks.setdefault(new_remote_path, lock)
                return None
            entry.remote_path = new_remote_path
            if new_local_cache_path is not None:
                entry.local_cache_path = new_local_cache_path
            self._entries[new_remote_path] = entry
            self._file_locks[new_remote_path] = lock
            return entry

    @contextmanager
    def file_lock(self, remote_path: str) -> Iterator[None]:
        with self._guard:
            lock = self._file_locks.setdefault(remote_path, threading.RLock())
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
