from __future__ import annotations

import logging
import time
from pathlib import Path

from sftp_auto_sync.domain.models import RemoteDriveMapping
from sftp_auto_sync.remote_drive.cache_index import CacheIndex
from sftp_auto_sync.remote_drive.content_cache import ContentCache
from sftp_auto_sync.remote_drive.file_transfer_service import FileTransferService
from sftp_auto_sync.remote_drive.metadata_cache import MetadataCache
from sftp_auto_sync.remote_drive.models import CachedFileEntry, OpenFileHandle, OpenFileHandleInfo, UploadTask
from sftp_auto_sync.remote_drive.upload_scheduler import UploadScheduler


class RemoteDriveSession:
    DOWNLOAD_RETRY_DELAY_SEC = 1.0

    def __init__(
        self,
        mapping: RemoteDriveMapping,
        cache_root: str | Path,
        transfer_service: FileTransferService,
        *,
        logger: logging.Logger | None = None,
    ):
        self.mapping = mapping
        self.cache_index = CacheIndex()
        self.content_cache = ContentCache(cache_root, mount_key=f'remote_drive_{mapping.id or mapping.name}')
        self.metadata_cache = MetadataCache(ttl_sec=mapping.metadata_ttl_sec)
        self.transfer_service = transfer_service
        self.logger = logger or logging.getLogger(__name__)
        self.upload_scheduler = UploadScheduler(self._upload_task, logger=self.logger)
        self._open_handles: dict[int, OpenFileHandle] = {}
        self._next_handle_id = 1

    def start(self) -> None:
        self.content_cache.reset()
        self.cache_index.clear()
        self.metadata_cache.clear()
        self._open_handles.clear()
        self._next_handle_id = 1
        self.upload_scheduler.start()

    def stop(self) -> None:
        self.upload_scheduler.stop()
        self._open_handles.clear()

    def list_dir(self, remote_dir: str):
        cached = self.metadata_cache.get_dir(remote_dir)
        if cached is not None:
            return cached
        entries = self.transfer_service.list_dir(remote_dir)
        self.metadata_cache.set_dir(remote_dir, entries)
        for entry in entries:
            self.metadata_cache.set_stat(entry.remote_path, entry)
        return entries

    def open_file(self, remote_path: str, *, writable: bool = False, create: bool = False, truncate: bool = False) -> OpenFileHandle:
        with self.cache_index.file_lock(remote_path):
            if create:
                entry = self.cache_index.get(remote_path)
                if entry is None and not self.content_cache.has_cached_file(remote_path):
                    entry = self.write_bytes(remote_path, b'')
                else:
                    entry = self.ensure_cached(remote_path)
            else:
                entry = self.ensure_cached(remote_path)

            if truncate and writable:
                entry = self.write_bytes(remote_path, b'')

            entry.open_handle_count += 1
            self.cache_index.upsert(entry)
            handle = OpenFileHandle(
                handle_id=self._next_handle_id,
                remote_path=remote_path,
                local_cache_path=entry.local_cache_path,
                writable=writable,
                created=create,
            )
            self._open_handles[handle.handle_id] = handle
            self._next_handle_id += 1
            return handle

    def read_handle(self, handle_id: int, *, offset: int = 0, length: int | None = None) -> bytes:
        handle = self._require_handle(handle_id)
        self.cache_index.mark_accessed(handle.remote_path)
        payload = Path(handle.local_cache_path).read_bytes()
        if offset < 0:
            raise ValueError('offset must be >= 0')
        if length is None:
            return payload[offset:]
        if length < 0:
            raise ValueError('length must be >= 0')
        return payload[offset:offset + length]

    def write_handle(self, handle_id: int, payload: bytes, *, offset: int = 0) -> CachedFileEntry:
        handle = self._require_handle(handle_id)
        if not handle.writable:
            raise PermissionError(f'Handle {handle_id} is not writable.')
        if offset < 0:
            raise ValueError('offset must be >= 0')
        existing = Path(handle.local_cache_path).read_bytes() if Path(handle.local_cache_path).exists() else b''
        if offset > len(existing):
            existing = existing + (b'\x00' * (offset - len(existing)))
        new_payload = existing[:offset] + payload
        tail_start = offset + len(payload)
        if tail_start < len(existing):
            new_payload += existing[tail_start:]
        entry = self.write_bytes(handle.remote_path, new_payload)
        handle.local_cache_path = entry.local_cache_path
        self._open_handles[handle_id] = handle
        return entry

    def flush_handle(self, handle_id: int) -> None:
        handle = self._require_handle(handle_id)
        entry = self.cache_index.get(handle.remote_path)
        if entry is not None and entry.is_dirty:
            self._upload_task(UploadTask(remote_path=handle.remote_path, run_at=time.time(), reason='flush'))

    def close_handle(self, handle_id: int) -> None:
        handle = self._require_handle(handle_id)
        entry = self.cache_index.get(handle.remote_path)
        if entry is not None:
            entry.open_handle_count = max(0, entry.open_handle_count - 1)
            self.cache_index.upsert(entry)
            if handle.writable and entry.is_dirty:
                self._upload_task(UploadTask(remote_path=handle.remote_path, run_at=time.time(), reason='close'))
        self._open_handles.pop(handle_id, None)

    def stat_handle(self, handle_id: int) -> OpenFileHandleInfo:
        handle = self._require_handle(handle_id)
        cache_path = Path(handle.local_cache_path)
        if cache_path.exists():
            stat = cache_path.stat()
            size = stat.st_size
            mtime_ns = stat.st_mtime_ns
        else:
            entry = self.cache_index.get(handle.remote_path)
            size = entry.local_size if entry and entry.local_size is not None else 0
            mtime_ns = entry.local_mtime_ns if entry else None
        return OpenFileHandleInfo(
            handle_id=handle.handle_id,
            remote_path=handle.remote_path,
            local_cache_path=handle.local_cache_path,
            size=size,
            mtime_ns=mtime_ns,
        )

    def truncate_handle(self, handle_id: int, size: int) -> CachedFileEntry:
        handle = self._require_handle(handle_id)
        if not handle.writable:
            raise PermissionError(f'Handle {handle_id} is not writable.')
        if size < 0:
            raise ValueError('size must be >= 0')
        payload = Path(handle.local_cache_path).read_bytes() if Path(handle.local_cache_path).exists() else b''
        if size < len(payload):
            payload = payload[:size]
        elif size > len(payload):
            payload = payload + (b'\x00' * (size - len(payload)))
        entry = self.write_bytes(handle.remote_path, payload)
        handle.local_cache_path = entry.local_cache_path
        self._open_handles[handle_id] = handle
        return entry

    def read_bytes(self, remote_path: str) -> bytes:
        entry = self.ensure_cached(remote_path)
        self.cache_index.mark_accessed(remote_path)
        return Path(entry.local_cache_path).read_bytes()

    def write_bytes(self, remote_path: str, payload: bytes) -> CachedFileEntry:
        with self.cache_index.file_lock(remote_path):
            entry = self.cache_index.get(remote_path)
            if entry is None:
                cache_path = self.content_cache.write_bytes_atomic(remote_path, payload)
                entry = self.cache_index.get_or_create(remote_path, str(cache_path))
                entry.downloaded_at = time.time()
            else:
                cache_path = self.content_cache.write_bytes_atomic(remote_path, payload)
                entry.local_cache_path = str(cache_path)
            stat = cache_path.stat()
            entry.local_size = stat.st_size
            entry.local_mtime_ns = stat.st_mtime_ns
            entry.last_access_at = time.time()
            entry.is_dirty = True
            self.cache_index.upsert(entry)
            self.upload_scheduler.schedule(remote_path, reason='dirty')
            return entry

    def ensure_cached(self, remote_path: str) -> CachedFileEntry:
        cache_path = self.content_cache.cache_path_for(remote_path)
        with self.cache_index.file_lock(remote_path):
            entry = self.cache_index.get_or_create(remote_path, str(cache_path))
            if cache_path.exists():
                stat = cache_path.stat()
                entry.local_size = stat.st_size
                entry.local_mtime_ns = stat.st_mtime_ns
                entry.last_access_at = time.time()
                entry.downloaded_at = entry.downloaded_at or entry.last_access_at
                remote_stat = self.transfer_service.stat(remote_path)
                remote_size = getattr(remote_stat, 'st_size', None)
                remote_mtime_ns = self._stat_mtime_ns(remote_stat)
                needs_refresh = (
                    not entry.is_dirty and (
                        entry.remote_size != remote_size
                        or entry.remote_mtime_ns != remote_mtime_ns
                        or (stat.st_size == 0 and (remote_size or 0) > 0)
                    )
                )
                if needs_refresh:
                    temp_path = self.content_cache.temp_path_for(remote_path)
                    self._download_until_success(remote_path, temp_path)
                    cache_path = self.content_cache.commit_download(remote_path, temp_path)
                    stat = cache_path.stat()
                    entry.local_cache_path = str(cache_path)
                    entry.local_size = stat.st_size
                    entry.local_mtime_ns = stat.st_mtime_ns
                    entry.downloaded_at = time.time()
                    entry.last_access_at = entry.downloaded_at
                entry.remote_size = remote_size
                entry.remote_mtime_ns = remote_mtime_ns
                self.cache_index.upsert(entry)
                return entry

            temp_path = self.content_cache.temp_path_for(remote_path)
            entry.is_downloading = True
            self.cache_index.upsert(entry)
            try:
                self._download_until_success(remote_path, temp_path)
                cache_path = self.content_cache.commit_download(remote_path, temp_path)
                stat = cache_path.stat()
                entry.local_cache_path = str(cache_path)
                entry.local_size = stat.st_size
                entry.local_mtime_ns = stat.st_mtime_ns
                entry.downloaded_at = time.time()
                entry.last_access_at = entry.downloaded_at
                remote_stat = self.transfer_service.stat(remote_path)
                entry.remote_size = getattr(remote_stat, 'st_size', None)
                entry.remote_mtime_ns = self._stat_mtime_ns(remote_stat)
                entry.last_error = None
                self.cache_index.upsert(entry)
                return entry
            finally:
                entry.is_downloading = False
                self.cache_index.upsert(entry)

    def mark_dirty(self, remote_path: str) -> CachedFileEntry:
        cache_path = self.content_cache.cache_path_for(remote_path)
        entry = self.cache_index.get_or_create(remote_path, str(cache_path))
        stat = cache_path.stat()
        entry.local_size = stat.st_size
        entry.local_mtime_ns = stat.st_mtime_ns
        entry.last_access_at = time.time()
        entry.is_dirty = True
        self.cache_index.upsert(entry)
        self.upload_scheduler.schedule(remote_path, reason='dirty')
        return entry

    def rename_file(self, old_remote_path: str, new_remote_path: str) -> CachedFileEntry | None:
        with self.cache_index.file_lock(old_remote_path):
            self.transfer_service.rename(old_remote_path, new_remote_path)
            new_cache_path = self.content_cache.rename(old_remote_path, new_remote_path)
            entry = self.cache_index.rename(old_remote_path, new_remote_path, str(new_cache_path) if new_cache_path else None)
            if entry is not None:
                self._retarget_handles(old_remote_path, new_remote_path, entry.local_cache_path)
            self.metadata_cache.invalidate_stat(old_remote_path)
            self.metadata_cache.invalidate_stat(new_remote_path)
            return entry

    def delete_file(self, remote_path: str) -> None:
        with self.cache_index.file_lock(remote_path):
            self.transfer_service.remove_file(remote_path)
            self.content_cache.delete(remote_path)
            self.cache_index.remove(remote_path)
            self.metadata_cache.invalidate_stat(remote_path)
            self._drop_handles(remote_path)

    def delete_cached(self, remote_path: str) -> None:
        with self.cache_index.file_lock(remote_path):
            self.content_cache.delete(remote_path)
            self.cache_index.remove(remote_path)
            self.metadata_cache.invalidate_stat(remote_path)
            self._drop_handles(remote_path)

    def _upload_task(self, task: UploadTask) -> None:
        remote_path = task.remote_path
        with self.cache_index.file_lock(remote_path):
            entry = self.cache_index.get(remote_path)
            if entry is None or not entry.is_dirty:
                return
            entry.is_uploading = True
            self.cache_index.upsert(entry)
            try:
                self.transfer_service.upload(entry.local_cache_path, remote_path)
                local_stat = Path(entry.local_cache_path).stat()
                remote_stat = self.transfer_service.stat(remote_path)
                entry.local_size = local_stat.st_size
                entry.local_mtime_ns = local_stat.st_mtime_ns
                entry.remote_size = getattr(remote_stat, 'st_size', None)
                entry.remote_mtime_ns = self._stat_mtime_ns(remote_stat)
                entry.is_dirty = False
                entry.last_error = None
            except Exception as exc:
                entry.last_error = str(exc)
                entry.is_dirty = True
                self.upload_scheduler.schedule(remote_path, reason='retry', delay_sec=min(30, max(2, 2 ** (task.retry_count + 1))), retry_count=task.retry_count + 1)
                raise
            finally:
                entry.is_uploading = False
                entry.last_access_at = time.time()
                self.cache_index.upsert(entry)

    def _require_handle(self, handle_id: int) -> OpenFileHandle:
        handle = self._open_handles.get(handle_id)
        if handle is None:
            raise FileNotFoundError(f'Handle {handle_id} does not exist.')
        return handle

    def _retarget_handles(self, old_remote_path: str, new_remote_path: str, new_local_cache_path: str) -> None:
        for handle in self._open_handles.values():
            if handle.remote_path == old_remote_path:
                handle.remote_path = new_remote_path
                handle.local_cache_path = new_local_cache_path

    def _drop_handles(self, remote_path: str) -> None:
        to_delete = [handle_id for handle_id, handle in self._open_handles.items() if handle.remote_path == remote_path]
        for handle_id in to_delete:
            self._open_handles.pop(handle_id, None)

    def _download_until_success(self, remote_path: str, temp_path: Path) -> None:
        attempt = 0
        while True:
            attempt += 1
            try:
                self.transfer_service.download(remote_path, temp_path)
                return
            except Exception as exc:
                self.content_cache.delete(remote_path)
                self.logger.warning(
                    'Download failed for %s on attempt %d, retrying: %s',
                    remote_path,
                    attempt,
                    exc,
                )
                entry = self.cache_index.get(remote_path)
                if entry is not None:
                    entry.last_error = str(exc)
                    entry.is_downloading = True
                    self.cache_index.upsert(entry)
                time.sleep(self.DOWNLOAD_RETRY_DELAY_SEC)

    @staticmethod
    def _stat_mtime_ns(stat_obj) -> int | None:
        if getattr(stat_obj, 'st_mtime_ns', None) is not None:
            return int(stat_obj.st_mtime_ns)
        if getattr(stat_obj, 'st_mtime', None) is not None:
            return int(stat_obj.st_mtime * 1_000_000_000)
        return None
