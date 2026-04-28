from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CachedFileEntry:
    remote_path: str
    local_cache_path: str
    remote_size: int | None = None
    remote_mtime_ns: int | None = None
    local_size: int | None = None
    local_mtime_ns: int | None = None
    downloaded_at: float = 0.0
    last_access_at: float = 0.0
    is_dirty: bool = False
    is_downloading: bool = False
    is_uploading: bool = False
    open_handle_count: int = 0
    last_error: str | None = None


@dataclass
class OpenFileHandle:
    handle_id: int
    remote_path: str
    local_cache_path: str
    writable: bool = False
    created: bool = False


@dataclass
class OpenFileHandleInfo:
    handle_id: int
    remote_path: str
    local_cache_path: str
    size: int = 0
    mtime_ns: int | None = None


@dataclass
class RemoteDirEntry:
    remote_path: str
    name: str
    is_dir: bool
    size: int = 0
    mtime_ns: int | None = None


@dataclass
class MetadataCacheEntry:
    value: object
    expires_at: float


@dataclass
class UploadTask:
    remote_path: str
    run_at: float
    reason: str
    retry_count: int = 0
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class MountStatus:
    mapping_id: int
    state: str
    message: str = ''
    pending_uploads: int = 0
    backend: str = 'session_only'
    drive_mounted: bool = False
    drive_letter: str | None = None
