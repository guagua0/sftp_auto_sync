from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Any

from winfspy import (
    BaseFileSystemOperations,
    FileSystem,
    NTStatusDirectoryNotEmpty,
    NTStatusMediaWriteProtected,
    NTStatusNotADirectory,
    NTStatusObjectNameCollision,
    NTStatusObjectNameNotFound,
)
from winfspy.plumbing import NTSTATUS, NTStatusError, ffi
from winfspy.plumbing.file_attribute import CREATE_FILE_CREATE_OPTIONS, FILE_ATTRIBUTE
from winfspy.plumbing.security_descriptor import SecurityDescriptor
from winfspy.plumbing.win32_filetime import filetime_now

from sftp_auto_sync.remote_drive.virtual_drive_facade import VirtualDriveFacade, VirtualFileInfo


@dataclass
class WinFSPyResponse:
    ok: bool
    result: object | None = None
    error_code: str | None = None
    message: str | None = None


class EntryObj:
    allocation_unit = 4096

    def __init__(
        self,
        path: PureWindowsPath,
        *,
        is_dir: bool,
        security_descriptor: SecurityDescriptor,
        file_attributes: int,
        size: int = 0,
        creation_time: int | None = None,
        last_access_time: int | None = None,
        last_write_time: int | None = None,
        change_time: int | None = None,
    ):
        self.path = path
        self.is_dir = is_dir
        self.security_descriptor = security_descriptor
        default_attrs = FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        self.attributes = file_attributes or default_attrs
        if is_dir:
            self.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
        else:
            self.attributes &= ~FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
            self.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        now = filetime_now()
        self.creation_time = creation_time or now
        self.last_access_time = last_access_time or now
        self.last_write_time = last_write_time or now
        self.change_time = change_time or now
        self.index_number = 0
        self.file_size = 0 if is_dir else size
        self.allocation_size = 0 if is_dir else self._aligned_size(self.file_size)

    @property
    def name(self) -> str:
        return self.path.name

    def _aligned_size(self, size: int) -> int:
        if size <= 0:
            return 0
        units = (size + self.allocation_unit - 1) // self.allocation_unit
        return units * self.allocation_unit

    def update_size(self, size: int) -> None:
        if self.is_dir:
            self.file_size = 0
            self.allocation_size = 0
            return
        self.file_size = max(0, int(size))
        self.allocation_size = self._aligned_size(self.file_size)

    def touch_write(self, now: int | None = None) -> None:
        stamp = now or filetime_now()
        self.last_access_time = stamp
        self.last_write_time = stamp
        self.change_time = stamp

    def touch_access(self, now: int | None = None) -> None:
        self.last_access_time = now or filetime_now()

    def get_file_info(self) -> dict[str, int]:
        return {
            'file_attributes': self.attributes,
            'allocation_size': self.allocation_size,
            'file_size': self.file_size,
            'creation_time': self.creation_time,
            'last_access_time': self.last_access_time,
            'last_write_time': self.last_write_time,
            'change_time': self.change_time,
            'index_number': self.index_number,
        }


class OpenContext:
    def __init__(self, entry: EntryObj, *, mapping_id: int, facade: VirtualDriveFacade, writable: bool, handle_id: int | None = None):
        self.entry = entry
        self.mapping_id = mapping_id
        self.facade = facade
        self.writable = writable
        self.handle_id = handle_id


class WinFSPyAdapter:
    DEFAULT_SD = SecurityDescriptor.from_string(
        'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;WD)'
    )

    def __init__(
        self,
        facade: VirtualDriveFacade,
        mount_point: str = 'R:',
        logger: logging.Logger | None = None,
    ):
        self._facade = facade
        self._mount_point = mount_point
        self._logger = logger or logging.getLogger(__name__)
        self._filesystem: FileSystem | None = None
        self._operations: SFTPFileSystemOperations | None = None

    def is_available(self) -> bool:
        try:
            import winfspy  # noqa: F401
            return True
        except ImportError:
            return False

    def mount(self, mapping_id: int, drive_letter: str | None = None) -> WinFSPyResponse:
        if not self.is_available():
            return WinFSPyResponse(ok=False, error_code='ENOSYS', message='WinFSPy not available')

        try:
            mount_point = drive_letter or self._mount_point
            try:
                FileSystem.unmount(mount_point)
                self._logger.info('Unmounted existing: %s', mount_point)
                time.sleep(0.5)
            except Exception:
                pass

            self._operations = SFTPFileSystemOperations(self._facade, mapping_id, self._logger)
            self._filesystem = FileSystem(
                mount_point,
                self._operations,
                sector_size=512,
                sectors_per_allocation_unit=1,
                max_component_length=255,
                volume_creation_time=filetime_now(),
                volume_serial_number=0x12340000 + mapping_id,
                file_info_timeout=1000,
                case_sensitive_search=1,
                case_preserved_names=1,
                unicode_on_disk=1,
                persistent_acls=1,
                prefix='\\sftp\\remote',
                file_system_name='SFTPDrive',
            )

            self._logger.info('Mounting at: %s', mount_point)
            self._filesystem.start()
            self._logger.info('Mounted successfully: %s', mount_point)
            return WinFSPyResponse(ok=True, result={'mapping_id': mapping_id, 'mounted': True, 'drive': mount_point})
        except Exception as exc:
            self._logger.exception('Mount failed')
            return WinFSPyResponse(ok=False, error_code='EIO', message=str(exc))

    def mount_with_label(
        self,
        mapping_id: int,
        volume_label: str,
        drive_letter: str | None = None,
    ) -> WinFSPyResponse:
        if not self.is_available():
            return WinFSPyResponse(ok=False, error_code='ENOSYS', message='WinFSPy not available')

        try:
            mount_point = drive_letter or self._mount_point
            try:
                FileSystem.unmount(mount_point)
                self._logger.info('Unmounted existing: %s', mount_point)
                time.sleep(0.5)
            except Exception:
                pass

            normalized_label = self._normalize_volume_label(volume_label)
            prefix = self._network_prefix_for_label(normalized_label)
            self._operations = SFTPFileSystemOperations(
                self._facade,
                mapping_id,
                self._logger,
                volume_label=normalized_label,
            )
            self._filesystem = FileSystem(
                mount_point,
                self._operations,
                sector_size=512,
                sectors_per_allocation_unit=1,
                max_component_length=255,
                volume_creation_time=filetime_now(),
                volume_serial_number=0x12340000 + mapping_id,
                file_info_timeout=1000,
                case_sensitive_search=1,
                case_preserved_names=1,
                unicode_on_disk=1,
                persistent_acls=1,
                prefix=prefix,
                file_system_name='SFTPDrive',
            )

            self._logger.info('Mounting at: %s with label %s', mount_point, normalized_label)
            self._filesystem.start()
            self._logger.info('Mounted successfully: %s', mount_point)
            return WinFSPyResponse(ok=True, result={'mapping_id': mapping_id, 'mounted': True, 'drive': mount_point})
        except Exception as exc:
            self._logger.exception('Mount failed')
            return WinFSPyResponse(ok=False, error_code='EIO', message=str(exc))

    def unmount(self, mapping_id: int) -> WinFSPyResponse:
        try:
            if self._filesystem is not None:
                self._logger.info('Unmounting')
                self._filesystem.stop()
                self._filesystem = None
            if self._operations is not None:
                self._operations.release_handles()
                self._operations = None
            return WinFSPyResponse(ok=True, result={'mapping_id': mapping_id, 'mounted': False})
        except Exception as exc:
            self._logger.exception('Unmount failed')
            return WinFSPyResponse(ok=False, error_code='EIO', message=str(exc))

    @staticmethod
    def _normalize_volume_label(volume_label: str) -> str:
        label = (volume_label or '').strip() or 'SFTP Remote'
        return label[:31]

    @staticmethod
    def _network_prefix_for_label(volume_label: str) -> str:
        slug = re.sub(r'[^0-9A-Za-z._-]+', '_', volume_label).strip('_') or 'remote'
        return f'\\sftp\\{slug[:48]}'


class SFTPFileSystemOperations(BaseFileSystemOperations):
    FSP_CLEANUP_DELETE = 0x01
    FSP_CLEANUP_SET_ALLOCATION_SIZE = 0x02
    FSP_CLEANUP_SET_ARCHIVE_BIT = 0x10
    FSP_CLEANUP_SET_LAST_ACCESS_TIME = 0x20
    FSP_CLEANUP_SET_LAST_WRITE_TIME = 0x40
    FSP_CLEANUP_SET_CHANGE_TIME = 0x80

    def __init__(self, facade: VirtualDriveFacade, mapping_id: int, logger: logging.Logger, *, volume_label: str = 'SFTP Remote'):
        super().__init__()
        self._facade = facade
        self._mapping_id = mapping_id
        self._logger = logger
        self._volume_label = volume_label
        self._thread_lock = threading.RLock()
        self._root_path = PureWindowsPath('/')
        self._root_obj = EntryObj(
            self._root_path,
            is_dir=True,
            security_descriptor=WinFSPyAdapter.DEFAULT_SD,
            file_attributes=FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY,
        )
        self._entries: dict[PureWindowsPath, EntryObj] = {self._root_path: self._root_obj}
        self._dir_children: dict[PureWindowsPath, set[PureWindowsPath]] = {self._root_path: set()}
        self._closed_contexts: list[object] = []

    def release_handles(self) -> None:
        self._opened_objs.clear()
        self._closed_contexts.clear()

    def ll_close(self, file_context) -> NTSTATUS:
        cooked_file_context = ffi.from_handle(file_context)
        try:
            self.close(cooked_file_context)
        except NTStatusError as exc:
            return exc.value
        self._closed_contexts.append(file_context)
        return NTSTATUS.STATUS_SUCCESS

    def get_volume_info(self):
        return {
            'total_size': 10 * 1024 * 1024 * 1024,
            'free_size': 5 * 1024 * 1024 * 1024,
            'volume_label': self._volume_label,
        }

    def set_volume_label(self, volume_label):
        self._volume_label = WinFSPyAdapter._normalize_volume_label(str(volume_label))
        return None

    def get_security_by_name(self, file_name):
        path = self._to_windows_path(file_name)
        entry = self._get_entry(path, refresh=True)
        return (entry.attributes, entry.security_descriptor.handle, entry.security_descriptor.size)

    def get_security(self, file_context):
        return (file_context.entry.security_descriptor.handle, file_context.entry.security_descriptor.size)

    def set_security(self, file_context, security_information, modification_descriptor):
        file_context.entry.security_descriptor = file_context.entry.security_descriptor.evolve(
            security_information,
            modification_descriptor,
        )

    def create(
        self,
        file_name,
        create_options,
        granted_access,
        file_attributes,
        security_descriptor,
        allocation_size,
    ):
        path = self._to_windows_path(file_name)
        if path in self._entries:
            raise NTStatusObjectNameCollision()
        parent_path = path.parent or self._root_path
        parent_entry = self._get_entry(parent_path, refresh=True)
        if not parent_entry.is_dir:
            raise NTStatusNotADirectory()

        is_dir = bool(create_options & CREATE_FILE_CREATE_OPTIONS.FILE_DIRECTORY_FILE)
        entry = EntryObj(
            path,
            is_dir=is_dir,
            security_descriptor=security_descriptor,
            file_attributes=file_attributes,
            size=0,
        )
        handle_id = None if is_dir else self._facade.open_file(
            self._mapping_id,
            self._to_virtual_path(path),
            writable=True,
            create=True,
            truncate=False,
        )
        if handle_id is not None:
            handle_info = self._facade.get_handle_info(self._mapping_id, handle_id)
            entry.update_size(handle_info.size)
            self._apply_cached_times(entry, handle_info.mtime_ns)
        self._store_entry(entry)
        self._invalidate_parent(path)
        return OpenContext(entry, mapping_id=self._mapping_id, facade=self._facade, writable=not is_dir, handle_id=handle_id)

    def open(self, file_name, create_options, granted_access):
        path = self._to_windows_path(file_name)
        entry = self._get_entry(path, refresh=True)
        writable = self._is_write_access(granted_access) and not entry.is_dir
        handle_id = None
        if not entry.is_dir:
            handle_id = self._facade.open_file(
                self._mapping_id,
                self._to_virtual_path(path),
                writable=writable,
                create=False,
                truncate=False,
            )
            handle_info = self._facade.get_handle_info(self._mapping_id, handle_id)
            entry.update_size(handle_info.size)
            self._apply_cached_times(entry, handle_info.mtime_ns)
        return OpenContext(entry, mapping_id=self._mapping_id, facade=self._facade, writable=writable, handle_id=handle_id)

    def overwrite(self, file_context, file_attributes, replace_file_attributes: bool, allocation_size: int):
        entry = file_context.entry
        if entry.is_dir:
            raise NTStatusMediaWriteProtected()
        attrs = file_attributes | FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        if replace_file_attributes:
            entry.attributes = attrs & ~FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
        else:
            entry.attributes |= attrs
            entry.attributes &= ~FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
        self.set_file_size(file_context, allocation_size, True)
        entry.touch_write()

    def close(self, file_context):
        if file_context.handle_id is not None:
            self._facade.close_handle(self._mapping_id, file_context.handle_id)
            file_context.handle_id = None

    def cleanup(self, file_context, file_name, flags):
        entry = file_context.entry
        if flags & self.FSP_CLEANUP_DELETE:
            self.delete(file_context, file_name)
            return
        if flags & self.FSP_CLEANUP_SET_ALLOCATION_SIZE:
            entry.update_size(entry.file_size)
        if flags & self.FSP_CLEANUP_SET_ARCHIVE_BIT and not entry.is_dir:
            entry.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        now = filetime_now()
        if flags & self.FSP_CLEANUP_SET_LAST_ACCESS_TIME:
            entry.last_access_time = now
        if flags & self.FSP_CLEANUP_SET_LAST_WRITE_TIME:
            entry.last_write_time = now
        if flags & self.FSP_CLEANUP_SET_CHANGE_TIME:
            entry.change_time = now

    def read_directory(self, file_context, marker):
        entry = file_context.entry
        if not entry.is_dir:
            raise NTStatusNotADirectory()
        children = self._list_children(entry.path)
        rows = []
        if entry.path != self._root_path:
            parent_entry = self._get_entry(entry.path.parent or self._root_path, refresh=False)
            rows.append({'file_name': '.', **entry.get_file_info()})
            rows.append({'file_name': '..', **parent_entry.get_file_info()})
        for child in children:
            rows.append({'file_name': child.name, **child.get_file_info()})
        rows.sort(key=lambda item: item['file_name'])
        if marker is None:
            return rows
        for index, row in enumerate(rows):
            if row['file_name'] == marker:
                return rows[index + 1:]
        return []

    def get_dir_info_by_name(self, file_context, file_name):
        parent = file_context.entry.path
        path = (parent / str(file_name)).resolve() if hasattr((parent / str(file_name)), 'resolve') else parent / str(file_name)
        entry = self._get_entry(self._normalize_windows_path(path), refresh=True)
        return {'file_name': entry.name, **entry.get_file_info()}

    def get_file_info(self, file_context):
        entry = file_context.entry
        if not entry.is_dir:
            self._refresh_file_entry(entry, handle_id=file_context.handle_id)
        return entry.get_file_info()

    def read(self, file_context, offset, length):
        entry = file_context.entry
        if entry.is_dir:
            raise NTStatusNotADirectory()
        if file_context.handle_id is None:
            return b''
        payload = self._facade.read_handle(self._mapping_id, file_context.handle_id, offset=offset, length=length)
        entry.touch_access()
        self._refresh_file_entry(entry, handle_id=file_context.handle_id)
        return payload

    def write(self, file_context, buffer, offset, write_to_end_of_file, constrained_io):
        entry = file_context.entry
        if entry.is_dir:
            raise NTStatusMediaWriteProtected()
        if file_context.handle_id is None:
            raise NTStatusMediaWriteProtected()
        handle_info = self._facade.get_handle_info(self._mapping_id, file_context.handle_id)
        payload = bytes(buffer)
        actual_offset = handle_info.size if write_to_end_of_file else offset
        if constrained_io and actual_offset >= handle_info.size:
            return 0
        if constrained_io and actual_offset + len(payload) > handle_info.size:
            payload = payload[: max(0, handle_info.size - actual_offset)]
        if not payload and len(bytes(buffer)) > 0:
            return 0
        updated = self._facade.write_handle(self._mapping_id, file_context.handle_id, payload, offset=actual_offset)
        entry.update_size(updated.local_size or 0)
        self._apply_cached_times(entry, updated.local_mtime_ns)
        entry.touch_write()
        return len(payload)

    def flush(self, file_context):
        entry = file_context.entry
        if file_context.handle_id is not None:
            self._facade.flush_handle(self._mapping_id, file_context.handle_id)
            self._refresh_file_entry(entry, handle_id=file_context.handle_id)

    def can_delete(self, file_context, file_name):
        entry = self._get_entry(self._to_windows_path(file_name), refresh=True)
        if entry.is_dir and self._list_children(entry.path):
            raise NTStatusDirectoryNotEmpty()

    def delete(self, file_context, file_name):
        path = self._to_windows_path(file_name)
        entry = self._get_entry(path, refresh=False)
        if entry.is_dir:
            if self._list_children(path):
                raise NTStatusDirectoryNotEmpty()
            raise NTStatusMediaWriteProtected()
        self._facade.delete_file(self._mapping_id, self._to_virtual_path(path))
        self._remove_entry(path)
        self._invalidate_parent(path)

    def rename(self, file_context, file_name, new_file_name, replace_if_exists):
        old_path = self._to_windows_path(file_name)
        new_path = self._to_windows_path(new_file_name)
        entry = self._get_entry(old_path, refresh=False)
        if entry.is_dir:
            raise NTStatusMediaWriteProtected()
        if not replace_if_exists and new_path in self._entries:
            raise NTStatusObjectNameCollision()
        self._facade.rename_file(self._mapping_id, self._to_virtual_path(old_path), self._to_virtual_path(new_path))
        self._remove_entry(old_path)
        entry.path = new_path
        self._store_entry(entry)
        file_context.entry = entry
        self._invalidate_parent(old_path)
        self._invalidate_parent(new_path)

    def set_basic_info(
        self,
        file_context,
        file_attributes,
        creation_time,
        last_access_time,
        last_write_time,
        change_time,
        file_info,
    ):
        entry = file_context.entry
        if file_attributes != FILE_ATTRIBUTE.INVALID_FILE_ATTRIBUTES:
            if entry.is_dir:
                entry.attributes = file_attributes | FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
            else:
                entry.attributes = (file_attributes & ~FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY) | FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        if creation_time:
            entry.creation_time = creation_time
        if last_access_time:
            entry.last_access_time = last_access_time
        if last_write_time:
            entry.last_write_time = last_write_time
        if change_time:
            entry.change_time = change_time
        return entry.get_file_info()

    def set_file_size(self, file_context, new_size, set_allocation_size):
        entry = file_context.entry
        if entry.is_dir:
            return
        if file_context.handle_id is None:
            raise NTStatusMediaWriteProtected()
        handle_info = self._facade.get_handle_info(self._mapping_id, file_context.handle_id)
        current_size = handle_info.size
        target_size = new_size if not set_allocation_size else max(current_size, new_size)
        if target_size == current_size:
            entry.update_size(current_size)
            return
        if target_size < current_size:
            self._facade.truncate_handle(self._mapping_id, file_context.handle_id, target_size)
        else:
            self._facade.write_handle(self._mapping_id, file_context.handle_id, b'\x00' * (target_size - current_size), offset=current_size)
        self._refresh_file_entry(entry, handle_id=file_context.handle_id)
        entry.change_time = filetime_now()

    def _list_children(self, parent_path: PureWindowsPath) -> list[EntryObj]:
        virtual_parent = self._to_virtual_path(parent_path)
        items = self._facade.list_dir(self._mapping_id, virtual_parent)
        children: list[EntryObj] = []
        child_paths: set[PureWindowsPath] = set()
        for item in items:
            child_path = self._to_windows_path(item.virtual_path)
            child_paths.add(child_path)
            child_entry = self._entry_from_virtual_info(child_path, item)
            self._store_entry(child_entry)
            children.append(child_entry)
        self._dir_children[parent_path] = child_paths
        stale_paths = [path for path in list(self._entries) if path.parent == parent_path and path not in child_paths]
        for stale_path in stale_paths:
            if stale_path != self._root_path:
                self._entries.pop(stale_path, None)
        return children

    def _get_entry(self, path: PureWindowsPath, *, refresh: bool) -> EntryObj:
        normalized = self._normalize_windows_path(path)
        if normalized == self._root_path:
            return self._root_obj
        cached = self._entries.get(normalized)
        if cached is not None and not refresh:
            return cached
        try:
            info = self._facade.stat_file(self._mapping_id, self._to_virtual_path(normalized))
        except FileNotFoundError:
            raise NTStatusObjectNameNotFound()
        entry = self._entry_from_virtual_info(normalized, info)
        self._store_entry(entry)
        return entry

    def _entry_from_virtual_info(self, path: PureWindowsPath, info: VirtualFileInfo) -> EntryObj:
        entry = self._entries.get(path)
        if entry is None:
            entry = EntryObj(
                path,
                is_dir=info.is_dir,
                security_descriptor=WinFSPyAdapter.DEFAULT_SD,
                file_attributes=FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY if info.is_dir else FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE,
                size=info.size,
            )
        entry.is_dir = info.is_dir
        entry.update_size(info.size)
        self._apply_cached_times(entry, info.mtime_ns)
        if info.is_dir:
            entry.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
            entry.allocation_size = 0
            entry.file_size = 0
        else:
            entry.attributes &= ~FILE_ATTRIBUTE.FILE_ATTRIBUTE_DIRECTORY
            entry.attributes |= FILE_ATTRIBUTE.FILE_ATTRIBUTE_ARCHIVE
        return entry

    def _refresh_file_entry(self, entry: EntryObj, *, handle_id: int | None) -> None:
        if entry.is_dir:
            return
        if handle_id is not None:
            handle_info = self._facade.get_handle_info(self._mapping_id, handle_id)
            entry.update_size(handle_info.size)
            self._apply_cached_times(entry, handle_info.mtime_ns)
            return
        info = self._facade.stat_file(self._mapping_id, self._to_virtual_path(entry.path))
        entry.update_size(info.size)
        self._apply_cached_times(entry, info.mtime_ns)

    def _apply_cached_times(self, entry: EntryObj, mtime_ns: int | None) -> None:
        if not mtime_ns:
            return
        filetime_value = self._ns_to_filetime(mtime_ns)
        entry.last_write_time = filetime_value
        entry.change_time = filetime_value
        if entry.creation_time == 0:
            entry.creation_time = filetime_value

    @staticmethod
    def _ns_to_filetime(value: int) -> int:
        return int(value // 100) + 116444736000000000

    def _store_entry(self, entry: EntryObj) -> None:
        self._entries[entry.path] = entry
        parent = entry.path.parent or self._root_path
        self._dir_children.setdefault(parent, set()).add(entry.path)
        self._dir_children.setdefault(entry.path, set())

    def _remove_entry(self, path: PureWindowsPath) -> None:
        normalized = self._normalize_windows_path(path)
        self._entries.pop(normalized, None)
        children = self._dir_children.pop(normalized, set())
        for child in list(children):
            self._entries.pop(child, None)
        parent = normalized.parent or self._root_path
        self._dir_children.setdefault(parent, set()).discard(normalized)

    def _invalidate_parent(self, path: PureWindowsPath) -> None:
        parent = path.parent or self._root_path
        self._dir_children.pop(parent, None)

    def _to_virtual_path(self, path: PureWindowsPath) -> str:
        if path == self._root_path:
            return '/'
        parts = [part for part in path.parts if part not in ('\\', '/')]
        return '/' + '/'.join(parts)

    def _to_windows_path(self, path: str | bytes | PureWindowsPath) -> PureWindowsPath:
        if isinstance(path, bytes):
            path = path.decode('utf-8')
        if isinstance(path, PureWindowsPath):
            return self._normalize_windows_path(path)
        value = str(path or '/').replace('\\', '/')
        if not value.startswith('/'):
            value = '/' + value
        return self._normalize_windows_path(PureWindowsPath(value))

    def _normalize_windows_path(self, path: PureWindowsPath) -> PureWindowsPath:
        parts = [part for part in path.parts if part not in ('\\', '/')]
        return self._root_path.joinpath(*parts) if parts else self._root_path

    @staticmethod
    def _is_write_access(granted_access: int) -> bool:
        write_mask = 0x0002 | 0x0004 | 0x0010 | 0x0100 | 0x40000000
        return bool(granted_access & write_mask)
