from __future__ import annotations

from pathlib import Path

from sftp_auto_sync.infra.sftp.remote_ops import RemoteOps
from sftp_auto_sync.remote_drive.models import RemoteDirEntry


class FileTransferService:
    def __init__(self, sftp_factory, remote_ops: RemoteOps | None = None):
        self._sftp_factory = sftp_factory
        self._remote_ops = remote_ops or RemoteOps()

    def list_dir(self, remote_dir: str) -> list[RemoteDirEntry]:
        sftp = self._sftp_factory()
        rows = sftp.listdir_attr(remote_dir)
        result: list[RemoteDirEntry] = []
        for row in rows:
            mode = getattr(row, 'st_mode', 0)
            is_dir = bool(mode & 0o040000)
            result.append(
                RemoteDirEntry(
                    remote_path=f"{remote_dir.rstrip('/')}/{row.filename}" if remote_dir != '/' else f"/{row.filename}",
                    name=row.filename,
                    is_dir=is_dir,
                    size=getattr(row, 'st_size', 0) or 0,
                    mtime_ns=self._mtime_ns(row),
                )
            )
        return result

    def stat(self, remote_path: str):
        sftp = self._sftp_factory()
        return sftp.stat(remote_path)

    def download(self, remote_path: str, local_path: str | Path) -> None:
        sftp = self._sftp_factory()
        sftp.get(remote_path, str(local_path))

    def upload(self, local_path: str | Path, remote_path: str) -> None:
        sftp = self._sftp_factory()
        remote_dir = self._parent_dir(remote_path)
        self._remote_ops.ensure_remote_dir(sftp, remote_dir)
        temp_remote_path = f'{remote_path}.uploading'
        sftp.put(str(local_path), temp_remote_path)
        sftp.rename(temp_remote_path, remote_path)

    def rename(self, old_remote_path: str, new_remote_path: str) -> None:
        sftp = self._sftp_factory()
        remote_dir = self._parent_dir(new_remote_path)
        self._remote_ops.ensure_remote_dir(sftp, remote_dir)
        sftp.rename(old_remote_path, new_remote_path)

    def remove_file(self, remote_path: str) -> None:
        sftp = self._sftp_factory()
        self._remote_ops.remove_file_if_exists(sftp, remote_path)

    @staticmethod
    def _parent_dir(remote_path: str) -> str:
        parts = remote_path.rsplit('/', 1)
        return parts[0] if len(parts) == 2 and parts[0] else '/'

    @staticmethod
    def _mtime_ns(stat_obj) -> int | None:
        if hasattr(stat_obj, 'st_mtime_ns') and stat_obj.st_mtime_ns is not None:
            return int(stat_obj.st_mtime_ns)
        if hasattr(stat_obj, 'st_mtime') and stat_obj.st_mtime is not None:
            return int(stat_obj.st_mtime * 1_000_000_000)
        return None
