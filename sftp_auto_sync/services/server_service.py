from __future__ import annotations

import logging

from sftp_auto_sync.domain.enums import AuthType
from sftp_auto_sync.domain.errors import AppError, ValidationError
from sftp_auto_sync.domain.models import ServerProfile
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.infra.db.mapping_repo import MappingRepository
from sftp_auto_sync.infra.db.remote_drive_mapping_repo import RemoteDriveMappingRepository
from sftp_auto_sync.infra.db.server_repo import ServerRepository
from sftp_auto_sync.infra.secrets.secret_store import SecretStore
from sftp_auto_sync.infra.sftp.connection_manager import ConnectionManager
from sftp_auto_sync.infra.sftp.host_keys import KnownHostsManager
from sftp_auto_sync.services.validation_service import ValidationService


class ServerService:
    def __init__(
        self,
        server_repo: ServerRepository,
        mapping_repo: MappingRepository,
        remote_drive_mapping_repo: RemoteDriveMappingRepository,
        history_repo: HistoryRepository,
        secret_store: SecretStore,
        validation_service: ValidationService,
        known_hosts_manager: KnownHostsManager,
        logger: logging.Logger | None = None,
    ):
        self._server_repo = server_repo
        self._mapping_repo = mapping_repo
        self._remote_drive_mapping_repo = remote_drive_mapping_repo
        self._history_repo = history_repo
        self._secret_store = secret_store
        self._validation_service = validation_service
        self._known_hosts_manager = known_hosts_manager
        self._logger = logger or logging.getLogger(__name__)

    def list_all(self) -> list[ServerProfile]:
        return self._server_repo.list_all()

    def list_enabled(self) -> list[ServerProfile]:
        return self._server_repo.list_enabled()

    def get(self, server_id: int) -> ServerProfile | None:
        return self._server_repo.get(server_id)

    def save(self, profile: ServerProfile, *, password: str | None = None, key_passphrase: str | None = None) -> ServerProfile:
        existing = self._server_repo.get(profile.id) if profile.id else None
        if profile.auth_type == AuthType.PASSWORD:
            password_present = bool(password) or (
                existing is not None and existing.id is not None and bool(self._secret_store.get_server_password(existing.id))
            )
        else:
            password_present = True
        errors = self._validation_service.validate_server(profile, password_present=password_present)
        if errors:
            raise ValidationError(errors)

        is_create = profile.id is None
        if is_create:
            profile.id = self._server_repo.create(profile)
        profile.password_ref = self._secret_store.password_ref_for(profile.id) if profile.id and profile.auth_type == AuthType.PASSWORD else None
        profile.private_key_passphrase_ref = self._secret_store.key_passphrase_ref_for(profile.id) if profile.id and profile.auth_type == AuthType.PRIVATE_KEY else None
        self._server_repo.update(profile)

        if profile.id is not None:
            if profile.auth_type == AuthType.PASSWORD:
                if password:
                    self._secret_store.set_server_password(profile.id, password)
                self._secret_store.delete_key_passphrase(profile.id)
            else:
                self._secret_store.delete_server_password(profile.id)
                if key_passphrase:
                    self._secret_store.set_key_passphrase(profile.id, key_passphrase)
        return self._server_repo.get(profile.id) or profile

    def delete(self, server_id: int) -> None:
        if self._mapping_repo.list_by_server(server_id):
            raise AppError('删除此服务器前请先删除关联的同步映射。')
        if self._remote_drive_mapping_repo.list_by_server(server_id):
            raise AppError('删除此服务器前请先删除关联的远程盘映射。')
        self._server_repo.delete(server_id)
        self._secret_store.delete_server_password(server_id)
        self._secret_store.delete_key_passphrase(server_id)

    def test_connection(self, profile: ServerProfile, *, password: str | None = None, key_passphrase: str | None = None) -> tuple[bool, str]:
        if profile.auth_type == AuthType.PASSWORD:
            password_present = bool(password) or (profile.id is not None and bool(self._secret_store.get_server_password(profile.id)))
        else:
            password_present = True
        errors = self._validation_service.validate_server(profile, password_present=password_present)
        if errors:
            message = '\n'.join(errors)
            self._history_repo.add(mapping_id=None, server_id=profile.id, action='test_connection', relative_path=None, remote_path=None, status='failed', message=message, source='ui')
            return False, message
        manager = ConnectionManager(self._known_hosts_manager, self._secret_store, logger=self._logger)
        try:
            manager.connect(profile, password_override=password, key_passphrase_override=key_passphrase)
            message = '连接成功。'
            self._history_repo.add(mapping_id=None, server_id=profile.id, action='test_connection', relative_path=None, remote_path=None, status='success', message=message, source='ui')
            return True, message
        except Exception as exc:
            message = str(exc)
            self._history_repo.add(mapping_id=None, server_id=profile.id, action='test_connection', relative_path=None, remote_path=None, status='failed', message=message, source='ui')
            return False, message
        finally:
            manager.close()
