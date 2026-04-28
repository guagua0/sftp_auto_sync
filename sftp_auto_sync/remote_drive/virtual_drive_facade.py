from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from sftp_auto_sync.remote_drive.path_resolver import RemoteDrivePathResolver
from sftp_auto_sync.remote_drive.models import OpenFileHandleInfo, RemoteDirEntry

if TYPE_CHECKING:
    from sftp_auto_sync.remote_drive.mount_manager import MountManager
    from sftp_auto_sync.remote_drive.session import RemoteDriveSession


@dataclass
class VirtualFileInfo:
    virtual_path: str
    remote_path: str
    is_dir: bool
    size: int = 0
    mtime_ns: int | None = None


class VirtualDriveFacade:
    def __init__(self, mount_manager: 'MountManager'):
        self._mount_manager = mount_manager

    def list_dir(self, mapping_id: int, virtual_dir: str) -> list[VirtualFileInfo]:
        session, resolver = self._resolve(mapping_id)
        session = cast('RemoteDriveSession', session)
        remote_dir = resolver.to_remote_path(virtual_dir)
        entries = cast(list[RemoteDirEntry], session.list_dir(remote_dir))
        return [
            VirtualFileInfo(
                virtual_path=resolver.to_virtual_path(entry.remote_path),
                remote_path=entry.remote_path,
                is_dir=entry.is_dir,
                size=entry.size,
                mtime_ns=entry.mtime_ns,
            )
            for entry in entries
        ]

    def open_file(self, mapping_id: int, virtual_path: str, *, writable: bool = False, create: bool = False, truncate: bool = False) -> int:
        session, resolver = self._resolve(mapping_id)
        handle = session.open_file(resolver.to_remote_path(virtual_path), writable=writable, create=create, truncate=truncate)
        return handle.handle_id

    def read_handle(self, mapping_id: int, handle_id: int, *, offset: int = 0, length: int | None = None) -> bytes:
        session, _ = self._resolve(mapping_id)
        return session.read_handle(handle_id, offset=offset, length=length)

    def write_handle(self, mapping_id: int, handle_id: int, payload: bytes, *, offset: int = 0):
        session, _ = self._resolve(mapping_id)
        return session.write_handle(handle_id, payload, offset=offset)

    def flush_handle(self, mapping_id: int, handle_id: int) -> None:
        session, _ = self._resolve(mapping_id)
        session.flush_handle(handle_id)

    def close_handle(self, mapping_id: int, handle_id: int) -> None:
        session, _ = self._resolve(mapping_id)
        session.close_handle(handle_id)

    def get_handle_info(self, mapping_id: int, handle_id: int) -> OpenFileHandleInfo:
        session, _ = self._resolve(mapping_id)
        return session.stat_handle(handle_id)

    def truncate_handle(self, mapping_id: int, handle_id: int, size: int):
        session, _ = self._resolve(mapping_id)
        return session.truncate_handle(handle_id, size)

    def read_file(self, mapping_id: int, virtual_path: str) -> bytes:
        session, resolver = self._resolve(mapping_id)
        return session.read_bytes(resolver.to_remote_path(virtual_path))

    def write_file(self, mapping_id: int, virtual_path: str, payload: bytes):
        session, resolver = self._resolve(mapping_id)
        return session.write_bytes(resolver.to_remote_path(virtual_path), payload)

    def rename_file(self, mapping_id: int, old_virtual_path: str, new_virtual_path: str):
        session, resolver = self._resolve(mapping_id)
        return session.rename_file(
            resolver.to_remote_path(old_virtual_path),
            resolver.to_remote_path(new_virtual_path),
        )

    def delete_file(self, mapping_id: int, virtual_path: str) -> None:
        session, resolver = self._resolve(mapping_id)
        session.delete_file(resolver.to_remote_path(virtual_path))

    def stat_file(self, mapping_id: int, virtual_path: str) -> VirtualFileInfo:
        session, resolver = self._resolve(mapping_id)
        session = cast('RemoteDriveSession', session)
        remote_path = resolver.to_remote_path(virtual_path)
        stat_entry = session.metadata_cache.get_stat(remote_path)
        if stat_entry is None:
            parent_virtual = '/' if virtual_path in {'', '/'} else '/' + '/'.join([part for part in virtual_path.strip('/').split('/')[:-1] if part])
            if parent_virtual == '//':
                parent_virtual = '/'
            self.list_dir(mapping_id, parent_virtual)
            stat_entry = session.metadata_cache.get_stat(remote_path)
        if stat_entry is None:
            cached = session.cache_index.get(remote_path)
            if cached is not None:
                return VirtualFileInfo(
                    virtual_path=virtual_path,
                    remote_path=remote_path,
                    is_dir=False,
                    size=cached.local_size or 0,
                    mtime_ns=cached.local_mtime_ns,
                )
            raise FileNotFoundError(remote_path)
        stat_entry = cast(RemoteDirEntry, stat_entry)
        return VirtualFileInfo(
            virtual_path=resolver.to_virtual_path(stat_entry.remote_path),
            remote_path=stat_entry.remote_path,
            is_dir=stat_entry.is_dir,
            size=stat_entry.size,
            mtime_ns=stat_entry.mtime_ns,
        )

    def _resolve(self, mapping_id: int):
        session = self._mount_manager.session_for(mapping_id)
        if session is None:
            raise RuntimeError(f'Remote drive mapping {mapping_id} is not mounted.')
        resolver = RemoteDrivePathResolver(session.mapping.remote_root)
        return session, resolver
