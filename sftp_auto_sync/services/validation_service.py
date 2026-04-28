from __future__ import annotations

from pathlib import Path

from sftp_auto_sync.domain.enums import AuthType, DeletePolicy, HostKeyPolicy
from sftp_auto_sync.domain.models import RemoteDriveMapping, ServerProfile, SyncMapping
from sftp_auto_sync.infra.db.server_repo import ServerRepository


class ValidationService:
    def __init__(self, server_repo: ServerRepository):
        self._server_repo = server_repo

    def validate_server(self, data: ServerProfile, *, password_present: bool) -> list[str]:
        errors: list[str] = []
        if not data.name.strip():
            errors.append('服务器名称不能为空。')
        for server in self._server_repo.list_all():
            if server.name == data.name and server.id != data.id:
                errors.append('服务器名称必须唯一。')
                break
        if not data.host.strip():
            errors.append('主机地址不能为空。')
        if not (1 <= int(data.port) <= 65535):
            errors.append('端口必须在 1 到 65535 之间。')
        if not data.username.strip():
            errors.append('用户名不能为空。')
        if data.auth_type == AuthType.PASSWORD and not password_present:
            errors.append('密码认证方式需要输入密码。')
        if data.auth_type == AuthType.PRIVATE_KEY:
            if not data.private_key_path:
                errors.append('私钥认证方式需要指定私钥路径。')
            else:
                key_path = Path(data.private_key_path)
                if not key_path.exists() or not key_path.is_file():
                    errors.append('私钥路径必须存在且可读。')
        if data.connect_timeout_sec < 3:
            errors.append('连接超时至少为 3 秒。')
        if data.host_key_policy not in {HostKeyPolicy.STRICT, HostKeyPolicy.TOFU}:
            errors.append('主机密钥策略必须是 strict 或 tofu。')
        return errors

    def validate_mapping(self, data: SyncMapping, existing_mappings: list[SyncMapping]) -> list[str]:
        errors: list[str] = []
        if not data.name.strip():
            errors.append('映射名称不能为空。')
        for mapping in existing_mappings:
            if mapping.name == data.name and mapping.id != data.id:
                errors.append('映射名称必须唯一。')
                break
        if self._server_repo.get(data.server_id) is None:
            errors.append('选择的服务器不存在。')
        local_dir = Path(data.local_dir)
        if not local_dir.is_absolute():
            errors.append('本地目录必须是绝对路径。')
        if not local_dir.exists() or not local_dir.is_dir():
            errors.append('本地目录必须存在且是一个目录。')
        if not data.remote_dir.startswith('/'):
            errors.append('远程目录必须是以 / 开头的绝对 POSIX 路径。')
        if not isinstance(data.ignore_patterns, list) or any(not isinstance(i, str) for i in data.ignore_patterns):
            errors.append('忽略模式必须是字符串数组。')
        if data.delete_policy not in {DeletePolicy.IGNORE, DeletePolicy.DELETE_FILE}:
            errors.append('删除策略必须是 ignore 或 delete_file。')
        return errors

    def validate_remote_drive_mapping(self, data: RemoteDriveMapping, existing_mappings: list[RemoteDriveMapping]) -> list[str]:
        errors: list[str] = []
        if not data.name.strip():
            errors.append('远程盘名称不能为空。')
        for mapping in existing_mappings:
            if mapping.name == data.name and mapping.id != data.id:
                errors.append('远程盘名称必须唯一。')
                break
        if self._server_repo.get(data.server_id) is None:
            errors.append('选择的服务器不存在。')
        if not data.remote_root.startswith('/'):
            errors.append('远程根目录必须是以 / 开头的绝对 POSIX 路径。')
        drive_letter = data.drive_letter.strip().upper().rstrip(':')
        if len(drive_letter) != 1 or not drive_letter.isalpha():
            errors.append('盘符必须是单个英文字母，例如 R。')
        for mapping in existing_mappings:
            other_letter = mapping.drive_letter.strip().upper().rstrip(':')
            if other_letter == drive_letter and mapping.id != data.id:
                errors.append('盘符必须唯一。')
                break
        if data.cache_root:
            cache_root = Path(data.cache_root)
            if not cache_root.is_absolute():
                errors.append('缓存根目录必须是绝对路径。')
        if data.file_cache_size_limit_mb <= 0:
            errors.append('缓存大小上限必须大于 0。')
        if data.metadata_ttl_sec < 0:
            errors.append('元数据缓存 TTL 不能小于 0。')
        if data.download_timeout_sec < 1:
            errors.append('下载超时至少为 1 秒。')
        if data.upload_timeout_sec < 1:
            errors.append('上传超时至少为 1 秒。')
        return errors
