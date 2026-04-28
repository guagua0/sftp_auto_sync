from __future__ import annotations

from dataclasses import dataclass, field

from sftp_auto_sync.domain.enums import AuthType, DeletePolicy, HostKeyPolicy, TaskAction


@dataclass
class ServerProfile:
    id: int | None = None
    name: str = ''
    host: str = ''
    port: int = 22
    username: str = ''
    auth_type: AuthType = AuthType.PASSWORD
    password_ref: str | None = None
    private_key_path: str | None = None
    private_key_passphrase_ref: str | None = None
    connect_timeout_sec: int = 10
    host_key_policy: HostKeyPolicy = HostKeyPolicy.TOFU
    enabled: bool = True
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class SyncMapping:
    id: int | None = None
    name: str = ''
    server_id: int = 0
    local_dir: str = ''
    remote_dir: str = ''
    recursive: bool = True
    enabled: bool = True
    delete_policy: DeletePolicy = DeletePolicy.IGNORE
    startup_rescan: bool = True
    ignore_patterns: list[str] = field(default_factory=list)
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class RemoteDriveMapping:
    id: int | None = None
    name: str = ''
    server_id: int = 0
    remote_root: str = ''
    drive_letter: str = ''
    enabled: bool = True
    auto_mount: bool = False
    read_only: bool = False
    cache_root: str | None = None
    file_cache_size_limit_mb: int = 1024
    metadata_ttl_sec: int = 10
    download_timeout_sec: int = 60
    upload_timeout_sec: int = 60
    note: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class SyncTask:
    task_id: str
    mapping_id: int
    server_id: int
    action: TaskAction
    local_path: str | None
    relative_path: str
    remote_path: str
    source: str
    priority: int
    retry_count: int
    enqueue_ts: float


@dataclass
class FileSnapshot:
    size: int
    mtime_ns: int


@dataclass
class SyncStateRecord:
    mapping_id: int
    relative_path: str
    last_local_size: int | None
    last_local_mtime_ns: int | None
    last_uploaded_at: str | None
    last_status: str | None
    last_error: str | None
    remote_path: str


@dataclass
class AppSetting:
    key: str
    value: str
