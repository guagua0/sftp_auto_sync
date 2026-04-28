from __future__ import annotations

import errno
from pathlib import PurePosixPath


class RemoteOps:
    def __init__(self):
        self._known_dirs: set[str] = {'/'}

    def reset_cache(self) -> None:
        self._known_dirs = {'/'}

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        if isinstance(exc, FileNotFoundError):
            return True
        code = getattr(exc, 'errno', None)
        if code in {errno.ENOENT, 2}:
            return True
        text = str(exc).lower()
        return 'no such file' in text or 'not found' in text

    def stat_or_none(self, sftp, remote_path: str):
        try:
            return sftp.stat(remote_path)
        except OSError as exc:
            if self._is_not_found_error(exc):
                return None
            raise
        except IOError as exc:
            if self._is_not_found_error(exc):
                return None
            raise

    def ensure_remote_dir(self, sftp, remote_dir: str) -> None:
        normalized = str(PurePosixPath(remote_dir))
        if normalized in {'', '.', '/'}:
            return
        current = ''
        for part in PurePosixPath(normalized).parts:
            if part == '/':
                current = '/'
                self._known_dirs.add(current)
                continue
            current = str(PurePosixPath(current) / part)
            if current in self._known_dirs:
                continue
            stat = self.stat_or_none(sftp, current)
            if stat is None:
                try:
                    sftp.mkdir(current)
                except Exception:
                    if self.stat_or_none(sftp, current) is None:
                        raise
            self._known_dirs.add(current)

    def remove_file_if_exists(self, sftp, remote_path: str) -> None:
        try:
            sftp.remove(remote_path)
        except OSError as exc:
            if self._is_not_found_error(exc):
                return
            raise
        except IOError as exc:
            if self._is_not_found_error(exc):
                return
            raise
