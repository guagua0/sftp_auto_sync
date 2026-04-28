from __future__ import annotations

from pathlib import PurePosixPath


class RemoteDrivePathResolver:
    def __init__(self, remote_root: str):
        self._remote_root = self._normalize_remote_root(remote_root)

    @property
    def remote_root(self) -> str:
        return self._remote_root

    def to_remote_path(self, virtual_path: str) -> str:
        normalized = self._normalize_virtual_path(virtual_path)
        if normalized == '/':
            return self._remote_root
        relative = normalized.lstrip('/')
        if self._remote_root == '/':
            return f'/{relative}'
        return str(PurePosixPath(self._remote_root) / PurePosixPath(relative))

    def to_virtual_path(self, remote_path: str) -> str:
        normalized = self._normalize_remote_root(remote_path)
        if self._remote_root == '/':
            return normalized
        if normalized == self._remote_root:
            return '/'
        prefix = f'{self._remote_root}/'
        if not normalized.startswith(prefix):
            raise ValueError(f'{remote_path} is outside remote root {self._remote_root}')
        return '/' + normalized[len(prefix):]

    @staticmethod
    def _normalize_remote_root(path: str) -> str:
        normalized = str(PurePosixPath(path))
        if not normalized.startswith('/'):
            normalized = '/' + normalized.lstrip('/')
        return normalized

    @staticmethod
    def _normalize_virtual_path(path: str) -> str:
        normalized = str(PurePosixPath('/' + path.lstrip('/')))
        return normalized if normalized.startswith('/') else f'/{normalized}'
