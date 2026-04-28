from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import threading
from ctypes import WINFUNCTYPE, POINTER, Structure, byref, c_void_p, c_ulong, c_ulonglong, c_int, c_uint, c_bool, wintypes
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from sftp_auto_sync.remote_drive.dokany_runtime import probe_dokany_runtime
from sftp_auto_sync.remote_drive.virtual_drive_facade import VirtualDriveFacade, VirtualFileInfo


class DokanyOperation(str, Enum):
    LIST_DIR = 'list_dir'
    OPEN_FILE = 'open_file'
    READ_HANDLE = 'read_handle'
    WRITE_HANDLE = 'write_handle'
    FLUSH_HANDLE = 'flush_handle'
    CLOSE_HANDLE = 'close_handle'
    READ_FILE = 'read_file'
    WRITE_FILE = 'write_file'
    RENAME_FILE = 'rename_file'
    DELETE_FILE = 'delete_file'
    STAT_FILE = 'stat_file'


DOKAN_VERSION = 0x0203


class DOKAN_OPTIONS(Structure):
    _fields_ = [
        ('Version', ctypes.c_ulong),
        ('ThreadCount', ctypes.c_ulong),
        ('Options', c_ulong),
        ('MountPoint', wintypes.LPCWSTR),
        ('UNCName', wintypes.LPCWSTR),
        ('Timeout', c_ulong),
        ('GlobalContext', c_ulonglong),
        ('AllocationUnitSize', c_ulong),
        ('SectorSize', c_ulong),
        ('VolumeSecurity', c_void_p),
        ('VolumeName', wintypes.LPCWSTR),
        ('MountManager', wintypes.BOOL),
        ('Removable', wintypes.BOOL),
        ('Writable', wintypes.BOOL),
        ('KeepAlive', wintypes.BOOL),
        ('UmFileOptions', c_ulong),
    ]


DOKAN_OPTION_DEBUG = 1
DOKAN_OPTION_STDERR = 2
DOKAN_OPTION_ALT_STREAM = 4
DOKAN_OPTION_KEEP_ALIVE = 8
DOKAN_OPTION_NETWORK = 16
DOKAN_OPTION_MOUNT_MANAGER = 32
DOKAN_OPTION_CHAR_REMAP = 64
DOKAN_OPTION_CASE_SENSITIVE = 128
DOKAN_OPTION_DIRECT_ACCESS = 256
DOKAN_OPTION_NO_PROXY = 512
DOKAN_OPTION_REMOVABLE = 1024
DOKAN_OPTION_NO_SECURITY = 2048


class DOKAN_FILE_INFO(Structure):
    _fields_ = [
        ('Context', c_void_p),
        ('FsContext', c_void_p),
        ('DokanContext', c_void_p),
        ('ProcessId', c_ulong),
        ('RequestInterval', c_ulong),
        ('Options', c_ulong),
        ('Action', c_ulong),
        ('Status', c_ulong),
        ('FileInfoIsValid', wintypes.BOOL),
        ('FileName', wintypes.LPCWSTR),
        ('CurrentByteOffset', c_ulonglong),
        ('InfoBuffer', c_void_p),
    ]


class DOKAN_OPERATIONS(Structure):
    _fields_ = [
        ('ZwCreateFile', c_void_p),
        ('ZwReadFile', c_void_p),
        ('ZwWriteFile', c_void_p),
        ('ZwFlushFileBuffers', c_void_p),
        ('ZwGetFileInformation', c_void_p),
        ('ZwFindFiles', c_void_p),
        ('ZwFindFiles2', c_void_p),
        ('ZwDeleteFile', c_void_p),
        ('ZwDeleteDirectory', c_void_p),
        ('ZwMoveFile', c_void_p),
        ('ZwLockUnlockFile', c_void_p),
        ('ZwGetDiskFreeSpace', c_void_p),
        ('ZwGetVolumeInformation', c_void_p),
        ('ZwMountPoint', c_void_p),
        ('ZwSetEndOfFile', c_void_p),
        ('ZwSetAllocationSize', c_void_p),
        ('ZwSetFileAttributes', c_void_p),
        ('ZwSetFileTime', c_void_p),
        ('ZwSetFileSecurity', c_void_p),
    ]


class FILETIME(Structure):
    _fields_ = [
        ('dwLowDateTime', c_ulong),
        ('dwHighDateTime', c_ulong),
    ]


class WIN32_FIND_DATAW(Structure):
    _fields_ = [
        ('dwFileAttributes', c_ulong),
        ('ftCreationTime', FILETIME),
        ('ftLastAccessTime', FILETIME),
        ('ftLastWriteTime', FILETIME),
        ('nFileSizeHigh', c_ulong),
        ('nFileSizeLow', c_ulong),
        ('dwReserved0', c_ulong),
        ('dwReserved1', c_ulong),
        ('cFileName', ctypes.c_wchar * 260),
        ('cAlternateFileName', ctypes.c_wchar * 14),
    ]


FILE_CASE_SENSITIVE_SEARCH = 1
FILE_CASE_PRESERVED_NAMES = 2
FILE_UNICODE_ON_DISK = 4
FILE_PERSISTENT_ACLS = 8
FILE_SEQUENTIAL_WRITE_ONCE = 0x800


ZWCREATEFILE = WINFUNCTYPE(c_int, wintypes.LPCWSTR, c_int, c_int, c_ulong, c_ulong, c_int, POINTER(DOKAN_FILE_INFO))
ZWREADFILE = WINFUNCTYPE(c_int, c_void_p, c_void_p, c_ulong, POINTER(c_ulong), POINTER(DOKAN_FILE_INFO))
ZWWRITEFILE = WINFUNCTYPE(c_int, c_void_p, c_void_p, c_ulong, POINTER(c_ulong), POINTER(DOKAN_FILE_INFO))
ZWFLUSHFILEBUFFERS = WINFUNCTYPE(c_int, c_void_p, POINTER(DOKAN_FILE_INFO))
ZWGETFILEINFORMATION = WINFUNCTYPE(c_int, wintypes.LPCWSTR, c_void_p, c_ulong, POINTER(DOKAN_FILE_INFO))
ZWFINDFILES = WINFUNCTYPE(c_int, wintypes.LPCWSTR, c_void_p, POINTER(DOKAN_FILE_INFO))
ZWFINDFILES2 = WINFUNCTYPE(c_int, wintypes.LPCWSTR, c_void_p, c_ulong, POINTER(DOKAN_FILE_INFO))
ZWDELETEFILE = WINFUNCTYPE(c_int, wintypes.LPCWSTR, POINTER(DOKAN_FILE_INFO))
ZWDELETEDIRECTORY = WINFUNCTYPE(c_int, wintypes.LPCWSTR, POINTER(DOKAN_FILE_INFO))
ZWMOVEFILE = WINFUNCTYPE(c_int, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL, POINTER(DOKAN_FILE_INFO))
ZWGETDISKFREESPACE = WINFUNCTYPE(c_int, POINTER(DOKAN_FILE_INFO))
ZWGETVOLUMEINFORMATION = WINFUNCTYPE(c_int, wintypes.LPWSTR, c_ulong, POINTER(c_ulong), POINTER(c_ulong), POINTER(c_ulong), c_void_p, c_ulong, POINTER(DOKAN_FILE_INFO))
ZWMOUNTPOINT = WINFUNCTYPE(c_int, POINTER(DOKAN_FILE_INFO))
ZWSETENDOFFILE = WINFUNCTYPE(c_int, c_void_p, c_ulonglong, POINTER(DOKAN_FILE_INFO))
ZWSETALLOCATIONSIZE = WINFUNCTYPE(c_int, c_void_p, c_ulonglong, POINTER(DOKAN_FILE_INFO))
ZWSETFILEATTRIBUTES = WINFUNCTYPE(c_int, wintypes.LPCWSTR, c_ulong, POINTER(DOKAN_FILE_INFO))
ZWSETFILETIME = WINFUNCTYPE(c_int, c_void_p, c_ulonglong, c_ulonglong, c_ulonglong, POINTER(DOKAN_FILE_INFO))
ZWSETFILESECURITY = WINFUNCTYPE(c_int, wintypes.LPCWSTR, c_void_p, c_void_p, POINTER(DOKAN_FILE_INFO))


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
FILE_SHARE_DELETE = 4
OPEN_EXISTING = 3
CREATE_ALWAYS = 2
CREATE_NEW = 1
TRUNCATE_EXISTING = 5
FILE_ATTRIBUTE_NORMAL = 128
FILE_ATTRIBUTE_DIRECTORY = 16
FILE_ATTRIBUTE_READONLY = 1
FILE_ATTRIBUTE_HIDDEN = 2
FILE_ATTRIBUTE_SYSTEM = 4
FILE_ATTRIBUTE_ARCHIVE = 32


def _win32_error(code: int) -> int:
    return -(1 << 32) | code


ERROR_FILE_NOT_FOUND = 2
ERROR_PATH_NOT_FOUND = 3
ERROR_ACCESS_DENIED = 5
ERROR_SHARING_VIOLATION = 32
ERROR_FILE_EXISTS = 80
ERROR_INVALID_PARAMETER = 87
ERROR_NOT_ENOUGH_MEMORY = 8
ERROR_DISK_FULL = 112
ERROR_DIR_NOT_EMPTY = 145


class DokanDll:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, dll_path: str | None = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialize(dll_path)
                    cls._instance = instance
        return cls._instance

    def _initialize(self, dll_path: str | None = None):
        runtime = probe_dokany_runtime()
        if not runtime.available or runtime.dll_path is None:
            raise RuntimeError('Dokan runtime not available')

        dll_to_load = dll_path or runtime.dll_path
        self._dll = ctypes.WinDLL(dll_to_load)

        self._dll.DokanCreateFileSystem.argtypes = [POINTER(DOKAN_OPTIONS), POINTER(DOKAN_OPERATIONS), POINTER(c_ulong)]
        self._dll.DokanCreateFileSystem.restype = c_int

        self._dll.DokanWaitForFileSystemClosed.argtypes = [c_ulong, c_ulong]
        self._dll.DokanWaitForFileSystemClosed.restype = c_int

        self._dll.DokanCloseHandle.argtypes = [c_ulong]
        self._dll.DokanCloseHandle.restype = c_int

        self._dll.DokanRemoveMountPoint.argtypes = [wintypes.LPCWSTR]
        self._dll.DokanRemoveMountPoint.restype = c_int

        self._dll.DokanIsNameInExpression.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL]
        self._dll.DokanIsNameInExpression.restype = wintypes.BOOL

        self._dll.DokanResetTimeout.argtypes = [c_ulong, POINTER(DOKAN_FILE_INFO)]
        self._dll.DokanResetTimeout.restype = c_int

        self._logger = logging.getLogger('dokany')
        self._mounted_handles: dict[int, int] = {}
        self._handle_counter = 0
        self._handle_lock = threading.Lock()

    def create_filesystem(self, options, operations) -> tuple[bool, int]:
        handle = c_ulong(0)
        result = self._dll.DokanCreateFileSystem(byref(options), byref(operations), byref(handle))
        if result == 0:
            return False, 0
        with self._handle_lock:
            self._handle_counter += 1
            self._mounted_handles[self._handle_counter] = handle.value
        return True, handle.value

    def wait_for_closed(self, handle: c_ulong, timeout_ms: c_ulong) -> bool:
        result = self._dll.DokanWaitForFileSystemClosed(handle, timeout_ms)
        return result != 0

    def close_handle(self, handle: c_ulong) -> bool:
        result = self._dll.DokanCloseHandle(handle)
        return result != 0

    def remove_mount_point(self, mount_point: str) -> bool:
        result = self._dll.DokanRemoveMountPoint(mount_point)
        return result != 0

    def reset_timeout(self, timeout_ms: c_ulong, file_info) -> bool:
        result = self._dll.DokanResetTimeout(timeout_ms, file_info)
        return result != 0

    def register_mounted_handle(self, mount_id: int, handle: int) -> None:
        with self._handle_lock:
            self._mounted_handles[mount_id] = handle

    def unregister_mounted_handle(self, mount_id: int) -> None:
        with self._handle_lock:
            self._mounted_handles.pop(mount_id, None)

    def get_mounted_handle(self, mount_id: int) -> int | None:
        with self._handle_lock:
            return self._mounted_handles.get(mount_id)


@dataclass
class DokanyRequest:
    mapping_id: int
    operation: DokanyOperation
    virtual_path: str = '/'
    new_virtual_path: str | None = None
    handle_id: int | None = None
    payload: bytes | None = None
    writable: bool = False
    create: bool = False
    truncate: bool = False
    replace_if_exists: bool = False
    offset: int = 0
    length: int | None = None


@dataclass
class DokanyResponse:
    ok: bool
    result: object | None = None
    error_code: str | None = None
    message: str | None = None


class DokanyAdapter:
    def __init__(self, facade: VirtualDriveFacade, mount_point: str = 'R:', logger: logging.Logger | None = None):
        self._facade = facade
        self._runtime = probe_dokany_runtime()
        self._mount_point = mount_point
        self._logger = logger or logging.getLogger(__name__)
        self._dll: DokanDll | None = None
        self._mount_handles: dict[int, int] = {}
        self._handle_to_path: dict[int, str] = {}
        self._path_to_handle: dict[str, int] = {}
        self._guard = threading.Lock()
        self._callback_refs: list = []

    @property
    def runtime_info(self):
        return self._runtime

    def is_available(self) -> bool:
        return self._runtime.available

    def _ensure_dll(self) -> DokanDll:
        if self._dll is None:
            self._dll = DokanDll()
        return self._dll

    def mount(self, mapping_id: int, drive_letter: str | None = None) -> DokanyResponse:
        if not self.is_available():
            return DokanyResponse(ok=False, error_code='ENOSYS', message=self._runtime.message)

        try:
            dll = self._ensure_dll()
            mount_point = drive_letter or self._mount_point
            if not mount_point.endswith('\\'):
                mount_point += '\\'

            options = DOKAN_OPTIONS()
            options.Version = DOKAN_VERSION
            options.ThreadCount = 0
            options.Options = DOKAN_OPTION_KEEP_ALIVE | DOKAN_OPTION_DEBUG
            options.MountPoint = mount_point
            options.UNCName = None
            options.Timeout = 30000
            options.GlobalContext = 0
            options.AllocationUnitSize = 4096
            options.SectorSize = 512
            options.VolumeSecurity = None
            options.VolumeName = None
            options.MountManager = False
            options.Removable = False
            options.Writable = True
            options.KeepAlive = True
            options.UmFileOptions = 0

            self._callback_refs.clear()

            operations = self._create_operations(mapping_id)

            self._logger.info('Attempting to mount at: %s with version 0x%x', mount_point, DOKAN_VERSION)

            success, handle = dll.create_filesystem(options, operations)
            if not success:
                return DokanyResponse(ok=False, error_code='EIO', message='DokanCreateFileSystem failed')

            with self._guard:
                self._mount_handles[mapping_id] = handle

            return DokanyResponse(ok=True, result={'mapping_id': mapping_id, 'mounted': True, 'drive': mount_point.rstrip('\\')})

        except Exception as exc:
            self._logger.exception('Mount failed for mapping %d', mapping_id)
            return DokanyResponse(ok=False, error_code='EIO', message=str(exc))

    def _create_operations(self, mapping_id: int):
        operations = DOKAN_OPERATIONS()
        operations.ZwCreateFile = ctypes.cast(self._make_create_file_cb(mapping_id), ctypes.c_void_p)
        operations.ZwReadFile = ctypes.cast(self._make_read_file_cb(mapping_id), ctypes.c_void_p)
        operations.ZwWriteFile = ctypes.cast(self._make_write_file_cb(mapping_id), ctypes.c_void_p)
        operations.ZwFlushFileBuffers = ctypes.cast(self._make_flush_file_buffers_cb(mapping_id), ctypes.c_void_p)
        operations.ZwGetFileInformation = ctypes.cast(self._make_get_file_information_cb(mapping_id), ctypes.c_void_p)
        operations.ZwFindFiles = ctypes.cast(self._make_find_files_cb(mapping_id), ctypes.c_void_p)
        operations.ZwFindFiles2 = ctypes.cast(self._make_find_files_cb(mapping_id), ctypes.c_void_p)
        operations.ZwDeleteFile = ctypes.cast(self._make_delete_file_cb(mapping_id), ctypes.c_void_p)
        operations.ZwDeleteDirectory = ctypes.cast(self._make_delete_directory_cb(mapping_id), ctypes.c_void_p)
        operations.ZwMoveFile = ctypes.cast(self._make_move_file_cb(mapping_id), ctypes.c_void_p)
        operations.ZwGetDiskFreeSpace = ctypes.cast(self._make_get_disk_free_space_cb(mapping_id), ctypes.c_void_p)
        operations.ZwGetVolumeInformation = ctypes.cast(self._make_get_volume_information_cb(mapping_id), ctypes.c_void_p)
        operations.ZwSetEndOfFile = ctypes.cast(self._make_set_end_of_file_cb(mapping_id), ctypes.c_void_p)
        operations.ZwSetAllocationSize = ctypes.cast(self._make_set_allocation_size_cb(mapping_id), ctypes.c_void_p)
        operations.ZwLockUnlockFile = None
        operations.ZwSetFileAttributes = None
        operations.ZwSetFileTime = None
        operations.ZwSetFileSecurity = None
        operations.ZwMountPoint = None
        return operations

    def _make_create_file_cb(self, mapping_id: int):
        def callback(file_name: str, security_context, access_mode, share_access, create_params, file_info):
            try:
                self._logger.debug('ZwCreateFile: %s', file_name)
                file_name = self._normalize_path(file_name)

                if file_name.endswith('\\'):
                    file_name = file_name[:-1]

                desired_access = access_mode & 0xFFFFFFFF
                create_disposition = (access_mode >> 32) & 0xFFFFFFFF

                writable = (desired_access & (GENERIC_WRITE | 0x10000000)) != 0
                create_new = create_disposition == CREATE_NEW
                create_always = create_disposition == CREATE_ALWAYS
                open_existing = create_disposition == OPEN_EXISTING
                truncate_existing = create_disposition == TRUNCATE_EXISTING
                create = create_new or create_always or truncate_existing

                if open_existing:
                    try:
                        info = self._facade.stat_file(mapping_id, file_name)
                        is_dir = info.is_dir
                    except FileNotFoundError:
                        return ERROR_FILE_NOT_FOUND
                else:
                    is_dir = False

                if is_dir and (desired_access & ~(FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)) != 0:
                    return ERROR_ACCESS_DENIED

                handle_id = self._facade.open_file(
                    mapping_id,
                    file_name,
                    writable=writable,
                    create=create,
                    truncate=truncate_existing,
                )

                with self._guard:
                    self._handle_to_path[handle_id] = file_name
                    if file_name not in self._path_to_handle:
                        self._path_to_handle[file_name] = handle_id
                    file_info.Context = handle_id

                return 0
            except Exception as exc:
                self._logger.exception('ZwCreateFile error: %s', file_name)
                return ERROR_FILE_NOT_FOUND

        callback_obj = ZWCREATEFILE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_read_file_cb(self, mapping_id: int):
        def callback(file_handle, buffer, length, read_length, file_info):
            try:
                handle_id = file_info.Context
                if handle_id == 0:
                    return ERROR_INVALID_PARAMETER

                offset = file_info.CurrentByteOffset
                data = self._facade.read_handle(mapping_id, handle_id, offset=offset, length=length)

                if not data:
                    read_length[0] = 0
                    return 0

                ctypes.memmove(buffer, ctypes.create_string_buffer(data), len(data))
                read_length[0] = len(data)
                file_info.CurrentByteOffset += len(data)

                return 0
            except Exception as exc:
                self._logger.exception('ZwReadFile error')
                return ERROR_FILE_NOT_FOUND

        callback_obj = ZWREADFILE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_write_file_cb(self, mapping_id: int):
        def callback(file_handle, buffer, length, write_length, file_info):
            try:
                handle_id = file_info.Context
                if handle_id == 0:
                    return ERROR_INVALID_PARAMETER

                data = ctypes.string_at(buffer, length)
                offset = file_info.CurrentByteOffset

                self._facade.write_handle(mapping_id, handle_id, data, offset=offset)
                write_length[0] = length
                file_info.CurrentByteOffset += length

                return 0
            except Exception as exc:
                self._logger.exception('ZwWriteFile error')
                return ERROR_ACCESS_DENIED

        callback_obj = ZWWRITEFILE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_flush_file_buffers_cb(self, mapping_id: int):
        def callback(file_handle, file_info):
            try:
                handle_id = file_info.Context
                if handle_id != 0:
                    self._facade.flush_handle(mapping_id, handle_id)
                return 0
            except Exception as exc:
                self._logger.exception('ZwFlushFileBuffers error')
                return ERROR_ACCESS_DENIED

        callback_obj = ZWFLUSHFILEBUFFERS(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_get_file_information_cb(self, mapping_id: int):
        def callback(file_name, buffer, length, file_info):
            try:
                file_name = self._normalize_path(file_name)
                if file_name.endswith('\\'):
                    file_name = file_name[:-1]

                if file_name == '' or file_name == '\\':
                    file_name = '/'

                info = self._facade.stat_file(mapping_id, file_name)

                buffer.cFileName = (file_name.replace('/', '\\') + '\0').encode('utf-16-le')[:260]
                buffer.nFileSizeHigh = (info.size >> 32) & 0xFFFFFFFF
                buffer.nFileSizeLow = info.size & 0xFFFFFFFF

                if info.mtime_ns:
                    mtime_100ns = info.mtime_ns // 100
                    buffer.ftLastWriteTime.dwLowDateTime = mtime_100ns & 0xFFFFFFFF
                    buffer.ftLastWriteTime.dwHighDateTime = (mtime_100ns >> 32) & 0xFFFFFFFF

                buffer.dwFileAttributes = FILE_ATTRIBUTE_NORMAL
                if info.is_dir:
                    buffer.dwFileAttributes |= FILE_ATTRIBUTE_DIRECTORY

                return 0
            except FileNotFoundError:
                return ERROR_FILE_NOT_FOUND
            except Exception as exc:
                self._logger.exception('ZwGetFileInformation error: %s', file_name)
                return ERROR_FILE_NOT_FOUND

        callback_obj = ZWGETFILEINFORMATION(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_find_files_cb(self, mapping_id: int):
        def callback(file_name, fill_find_data, file_info):
            try:
                path = self._normalize_path(file_name)
                if path.endswith('\\'):
                    path = path[:-1]
                if path == '':
                    path = '/'

                items = self._facade.list_dir(mapping_id, path)

                fill_buffer = ctypes.cast(fill_find_data, ctypes.POINTER(WIN32_FIND_DATAW))
                for i, item in enumerate(items):
                    if i > 0:
                        fill_buffer = ctypes.cast(ctypes.addressof(fill_buffer.contents) + ctypes.sizeof(WIN32_FIND_DATAW), ctypes.POINTER(WIN32_FIND_DATAW))

                    entry = fill_buffer.contents
                    name = item.virtual_path.replace('/', '\\')
                    if item.is_dir:
                        name += '\\'
                    entry.cFileName = (name + '\0').encode('utf-16-le')[:520]
                    entry.nFileSizeHigh = (item.size >> 32) & 0xFFFFFFFF
                    entry.nFileSizeLow = item.size & 0xFFFFFFFF
                    if item.mtime_ns:
                        mtime_100ns = item.mtime_ns // 100
                        entry.ftLastWriteTime.dwLowDateTime = mtime_100ns & 0xFFFFFFFF
                        entry.ftLastWriteTime.dwHighDateTime = (mtime_100ns >> 32) & 0xFFFFFFFF
                    entry.dwFileAttributes = FILE_ATTRIBUTE_NORMAL
                    if item.is_dir:
                        entry.dwFileAttributes |= FILE_ATTRIBUTE_DIRECTORY

                return 0
            except Exception as exc:
                self._logger.exception('ZwFindFiles error: %s', file_name)
                return 0

        callback_obj = ZWFINDFILES(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_delete_file_cb(self, mapping_id: int):
        def callback(file_name, file_info):
            try:
                file_name = self._normalize_path(file_name)
                self._facade.delete_file(mapping_id, file_name)
                return 0
            except Exception as exc:
                self._logger.exception('ZwDeleteFile error: %s', file_name)
                return ERROR_ACCESS_DENIED

        callback_obj = ZWDELETEFILE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_delete_directory_cb(self, mapping_id: int):
        def callback(file_name, file_info):
            try:
                file_name = self._normalize_path(file_name)
                self._facade.delete_file(mapping_id, file_name)
                return 0
            except Exception as exc:
                self._logger.exception('ZwDeleteDirectory error: %s', file_name)
                return ERROR_ACCESS_DENIED

        callback_obj = ZWDELETEDIRECTORY(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_move_file_cb(self, mapping_id: int):
        def callback(file_name, new_file_name, replace_if_exists, file_info):
            try:
                file_name = self._normalize_path(file_name)
                new_file_name = self._normalize_path(new_file_name)
                self._facade.rename_file(mapping_id, file_name, new_file_name)
                return 0
            except Exception as exc:
                self._logger.exception('ZwMoveFile error: %s -> %s', file_name, new_file_name)
                return ERROR_ACCESS_DENIED

        callback_obj = ZWMOVEFILE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_get_disk_free_space_cb(self, mapping_id: int):
        def callback(file_info):
            return 0

        callback_obj = ZWGETDISKFREESPACE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_get_volume_information_cb(self, mapping_id: int):
        def callback(volume_name_buffer, volume_name_size, volume_serial, max_component_length, file_system_flags, file_system_name_buffer, file_system_name_size, file_info):
            import platform
            name = f'SFTPRemote{chr(65 + mapping_id % 26)}'
            ctypes.memset(volume_name_buffer, 0, volume_name_size)
            name_encoded = (name + '\0').encode('utf-16-le')
            ctypes.memmove(volume_name_buffer, name_encoded, min(len(name_encoded), volume_name_size))
            volume_serial[0] = 0x12345678 + mapping_id
            max_component_length[0] = 255
            file_system_flags[0] = FILE_CASE_SENSITIVE_SEARCH | FILE_CASE_PRESERVED_NAMES | FILE_UNICODE_ON_DISK
            fs_name = 'SFTPDrive\0'.encode('utf-16-le')
            ctypes.memmove(file_system_name_buffer, fs_name, min(len(fs_name), file_system_name_size))
            return 0

        callback_obj = ZWGETVOLUMEINFORMATION(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_set_end_of_file_cb(self, mapping_id: int):
        def callback(file_handle, new_size, file_info):
            return 0

        callback_obj = ZWSETENDOFFILE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _make_set_allocation_size_cb(self, mapping_id: int):
        def callback(file_handle, new_size, file_info):
            return 0

        callback_obj = ZWSETALLOCATIONSIZE(callback)
        self._callback_refs.append(callback_obj)
        return callback_obj

    def _cleanup_file(self, mapping_id: int, file_info):
        handle_id = file_info.Context
        if handle_id != 0:
            try:
                self._facade.close_handle(mapping_id, handle_id)
            except Exception:
                pass
            with self._guard:
                path = self._handle_to_path.pop(handle_id, None)
                if path and self._path_to_handle.get(path) == handle_id:
                    self._path_to_handle.pop(path, None)
            file_info.Context = 0

    def unmount(self, mapping_id: int) -> DokanyResponse:
        if not self.is_available():
            return DokanyResponse(ok=False, error_code='ENOSYS', message=self._runtime.message)

        try:
            dll = self._ensure_dll()

            with self._guard:
                handle = self._mount_handles.pop(mapping_id, None)

            if handle:
                dll.wait_for_closed(c_ulong(handle), c_ulong(10000))
                dll.close_handle(c_ulong(handle))
                if self._dll:
                    self._dll.unregister_mounted_handle(mapping_id)

            self._callback_refs.clear()
            with self._guard:
                self._handle_to_path.clear()
                self._path_to_handle.clear()

            return DokanyResponse(ok=True, result={'mapping_id': mapping_id, 'mounted': False})

        except Exception as exc:
            self._logger.exception('Unmount failed for mapping %d', mapping_id)
            return DokanyResponse(ok=False, error_code='EIO', message=str(exc))

    @staticmethod
    def _normalize_path(path: str) -> str:
        if not path:
            return '/'
        path = path.replace('/', '\\')
        if path.startswith('\\'):
            path = path[1:]
        if not path.startswith('\\'):
            path = '\\' + path
        return path

    @staticmethod
    def _to_dokan_path(virtual_path: str) -> str:
        if virtual_path == '/' or not virtual_path:
            return '\\'
        if not virtual_path.startswith('\\'):
            virtual_path = '\\' + virtual_path
        return virtual_path.replace('/', '\\')

    def dispatch(self, request: DokanyRequest) -> DokanyResponse:
        try:
            operation = request.operation
            if operation == DokanyOperation.LIST_DIR:
                items = self._facade.list_dir(request.mapping_id, request.virtual_path)
                return DokanyResponse(ok=True, result=[self._normalize_file_info(item) for item in items])
            if operation == DokanyOperation.OPEN_FILE:
                handle_id = self._facade.open_file(
                    request.mapping_id,
                    request.virtual_path,
                    writable=request.writable,
                    create=request.create,
                    truncate=request.truncate,
                )
                return DokanyResponse(ok=True, result={'handle_id': handle_id})
            if operation == DokanyOperation.READ_HANDLE:
                payload = self._facade.read_handle(
                    request.mapping_id,
                    self._require_handle_id(request),
                    offset=request.offset,
                    length=request.length,
                )
                return DokanyResponse(ok=True, result={'payload': payload, 'length': len(payload), 'offset': request.offset})
            if operation == DokanyOperation.WRITE_HANDLE:
                entry = self._facade.write_handle(
                    request.mapping_id,
                    self._require_handle_id(request),
                    request.payload or b'',
                    offset=request.offset,
                )
                return DokanyResponse(ok=True, result=self._normalize_cache_entry(entry))
            if operation == DokanyOperation.FLUSH_HANDLE:
                self._facade.flush_handle(request.mapping_id, self._require_handle_id(request))
                return DokanyResponse(ok=True)
            if operation == DokanyOperation.CLOSE_HANDLE:
                self._facade.close_handle(request.mapping_id, self._require_handle_id(request))
                return DokanyResponse(ok=True)
            if operation == DokanyOperation.READ_FILE:
                payload = self._facade.read_file(request.mapping_id, request.virtual_path)
                sliced = self._slice_payload(payload, request.offset, request.length)
                return DokanyResponse(ok=True, result={'payload': sliced, 'length': len(sliced), 'offset': request.offset})
            if operation == DokanyOperation.WRITE_FILE:
                entry = self._facade.write_file(request.mapping_id, request.virtual_path, request.payload or b'')
                return DokanyResponse(ok=True, result=self._normalize_cache_entry(entry))
            if operation == DokanyOperation.RENAME_FILE:
                if request.new_virtual_path is None:
                    raise ValueError('new_virtual_path is required for rename_file.')
                entry = self._facade.rename_file(request.mapping_id, request.virtual_path, request.new_virtual_path)
                return DokanyResponse(ok=True, result=self._normalize_cache_entry(entry) if entry is not None else None)
            if operation == DokanyOperation.DELETE_FILE:
                self._facade.delete_file(request.mapping_id, request.virtual_path)
                return DokanyResponse(ok=True)
            if operation == DokanyOperation.STAT_FILE:
                info = self._facade.stat_file(request.mapping_id, request.virtual_path)
                return DokanyResponse(ok=True, result=self._normalize_file_info(info))
            raise NotImplementedError(f'Unsupported Dokany operation: {operation}')
        except FileNotFoundError as exc:
            return DokanyResponse(ok=False, error_code='ENOENT', message=str(exc))
        except PermissionError as exc:
            return DokanyResponse(ok=False, error_code='EACCES', message=str(exc))
        except ValueError as exc:
            return DokanyResponse(ok=False, error_code='EINVAL', message=str(exc))
        except RuntimeError as exc:
            return DokanyResponse(ok=False, error_code='EIO', message=str(exc))
        except Exception as exc:
            return DokanyResponse(ok=False, error_code='EIO', message=str(exc))

    @staticmethod
    def _require_handle_id(request: DokanyRequest) -> int:
        if request.handle_id is None:
            raise ValueError('handle_id is required for this operation.')
        return request.handle_id

    @staticmethod
    def _normalize_file_info(info: VirtualFileInfo) -> dict[str, object]:
        return {
            'virtual_path': info.virtual_path,
            'remote_path': info.remote_path,
            'is_dir': info.is_dir,
            'size': info.size,
            'mtime_ns': info.mtime_ns,
        }

    @staticmethod
    def _normalize_cache_entry(entry) -> dict[str, object]:
        return {
            'remote_path': entry.remote_path,
            'local_cache_path': entry.local_cache_path,
            'local_size': entry.local_size,
            'local_mtime_ns': entry.local_mtime_ns,
            'remote_size': entry.remote_size,
            'remote_mtime_ns': entry.remote_mtime_ns,
            'is_dirty': entry.is_dirty,
            'open_handle_count': entry.open_handle_count,
            'last_error': entry.last_error,
        }

    @staticmethod
    def _slice_payload(payload: bytes, offset: int, length: int | None) -> bytes:
        if offset < 0:
            raise ValueError('offset must be >= 0')
        if length is None:
            return payload[offset:]
        if length < 0:
            raise ValueError('length must be >= 0')
        return payload[offset:offset + length]
