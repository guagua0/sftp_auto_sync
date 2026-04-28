from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from sftp_auto_sync.domain.enums import AuthType, HostKeyPolicy
from sftp_auto_sync.domain.models import RemoteDriveMapping, ServerProfile
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.infra.db.mapping_repo import MappingRepository
from sftp_auto_sync.infra.db.migration_runner import run_migrations
from sftp_auto_sync.infra.db.remote_drive_mapping_repo import RemoteDriveMappingRepository
from sftp_auto_sync.infra.db.server_repo import ServerRepository
from sftp_auto_sync.infra.secrets.secret_store import SecretStore
from sftp_auto_sync.infra.sftp.host_keys import KnownHostsManager
from sftp_auto_sync.remote_drive.mount_manager import MountManager
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.validation_service import ValidationService
import sftp_auto_sync.remote_drive.mount_manager as mount_manager_module


class FakeConnectionManager:
    def __init__(self, *args, **kwargs):
        self.fake = SimpleNamespace(
            listdir_attr=lambda remote_dir: [],
            stat=lambda remote_path: SimpleNamespace(st_size=0, st_mtime=1, st_mtime_ns=1_000_000_000),
            get=lambda remote_path, local_path: Path(local_path).write_bytes(b''),
            put=lambda local_path, remote_path: None,
            rename=lambda old, new: None,
            mkdir=lambda remote_dir: None,
            remove=lambda remote_path: None,
            close=lambda: None,
        )

    def connect(self, server):
        return object(), self.fake

    def close(self):
        return None


def test_mount_manager_mount_and_unmount(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)
    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    remote_repo = RemoteDriveMappingRepository(cf)
    history_repo = HistoryRepository(cf)
    secret_store = SecretStore()
    validation = ValidationService(server_repo)
    known_hosts = KnownHostsManager(tmp_path / 'known_hosts')
    server_service = ServerService(server_repo, mapping_repo, remote_repo, history_repo, secret_store, validation, known_hosts)

    server = ServerProfile(name='srv1', host='127.0.0.1', port=22, username='u', auth_type=AuthType.PASSWORD, connect_timeout_sec=10, host_key_policy=HostKeyPolicy.TOFU, enabled=True, created_at='x', updated_at='x')
    server.id = server_repo.create(server)
    mapping = RemoteDriveMapping(id=1, name='rd1', server_id=server.id, remote_root='/data', drive_letter='R')

    original = mount_manager_module.ConnectionManager
    mount_manager_module.ConnectionManager = FakeConnectionManager
    try:
        manager = MountManager(server_service=server_service, secret_store=secret_store, known_hosts_manager=known_hosts, cache_root=tmp_path / 'cache')
        mounted = manager.mount(mapping)
        assert mounted.state == 'running'
        assert manager.is_mounted(1) is True
        stopped = manager.unmount(1)
        assert stopped.state == 'stopped'
        assert manager.is_mounted(1) is False
    finally:
        mount_manager_module.ConnectionManager = original
