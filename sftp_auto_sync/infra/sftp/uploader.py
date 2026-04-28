from __future__ import annotations

import time
from pathlib import Path, PurePosixPath

from sftp_auto_sync.app.constants import DEFAULT_STABILITY_CHECK_INTERVAL_MS, DEFAULT_STABILITY_MAX_CHECKS
from sftp_auto_sync.domain.errors import RetryableError, SkippedTaskError, UploadError
from sftp_auto_sync.domain.models import FileSnapshot
from sftp_auto_sync.infra.sftp.remote_ops import RemoteOps


class Uploader:
    def __init__(
        self,
        remote_ops: RemoteOps,
        *,
        stability_check_interval_ms: int = DEFAULT_STABILITY_CHECK_INTERVAL_MS,
        stability_max_checks: int = DEFAULT_STABILITY_MAX_CHECKS,
    ):
        self._remote_ops = remote_ops
        self._interval = stability_check_interval_ms / 1000.0
        self._max_checks = max(2, stability_max_checks)

    def wait_until_stable(self, local_path: Path) -> FileSnapshot:
        previous: FileSnapshot | None = None
        for _ in range(self._max_checks):
            if not local_path.exists():
                raise SkippedTaskError(f'Local file missing: {local_path}')
            if local_path.is_dir():
                raise SkippedTaskError(f'Path is a directory: {local_path}')
            if local_path.is_symlink():
                raise SkippedTaskError(f'Symlink is not supported: {local_path}')
            stat = local_path.stat()
            current = FileSnapshot(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            if previous and previous == current:
                return current
            previous = current
            time.sleep(self._interval)
        raise RetryableError(f'File is still changing: {local_path}')

    def upload_file(self, sftp, local_path: Path, remote_path: str) -> FileSnapshot:
        if not local_path.exists():
            raise SkippedTaskError(f'Local file missing: {local_path}')
        parent = str(PurePosixPath(remote_path).parent)
        self._remote_ops.ensure_remote_dir(sftp, parent)
        tmp_path = f'{remote_path}.__uploading__'
        try:
            self._remote_ops.remove_file_if_exists(sftp, tmp_path)
        except Exception:
            pass
        try:
            sftp.put(str(local_path), tmp_path, confirm=True)
            remote_stat = sftp.stat(tmp_path)
            local_stat = local_path.stat()
            if getattr(remote_stat, 'st_size', None) != local_stat.st_size:
                raise UploadError('Remote file size mismatch after upload.')
            try:
                sftp.posix_rename(tmp_path, remote_path)
            except Exception:
                try:
                    self._remote_ops.remove_file_if_exists(sftp, remote_path)
                except Exception:
                    pass
                sftp.rename(tmp_path, remote_path)
            return FileSnapshot(size=local_stat.st_size, mtime_ns=local_stat.st_mtime_ns)
        except Exception as exc:
            try:
                self._remote_ops.remove_file_if_exists(sftp, tmp_path)
            except Exception:
                pass
            if isinstance(exc, (UploadError, SkippedTaskError, RetryableError)):
                raise
            raise UploadError(str(exc)) from exc

    def delete_file(self, sftp, remote_path: str) -> None:
        self._remote_ops.remove_file_if_exists(sftp, remote_path)
