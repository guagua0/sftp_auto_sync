from __future__ import annotations

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
from sftp_auto_sync.remote_drive.dokany_adapter import DokanyAdapter, DokanyOperation, DokanyRequest
from sftp_auto_sync.remote_drive.mount_manager import MountManager
from sftp_auto_sync.remote_drive.path_resolver import RemoteDrivePathResolver
from sftp_auto_sync.remote_drive.virtual_drive_facade import VirtualDriveFacade
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.validation_service import ValidationService
import sftp_auto_sync.remote_drive.mount_manager as mount_manager_module


class FakeConnectionManager:
    def __init__(self, *args, **kwargs):
        self.files = {'/root/a.txt': b'hello'}
        self.directories = {'/', '/root'}
        self.fake = SimpleNamespace(
            listdir_attr=self.listdir_attr,
            stat=self.stat,
            get=self.get,
            put=self.put,
            rename=self.rename,
            mkdir=self.mkdir,
            remove=self.remove,
            close=lambda: None,
        )

    def listdir_attr(self, remote_dir):
        if remote_dir != '/root':
            return []
        return [SimpleNamespace(filename='a.txt', st_mode=0o100644, st_size=5, st_mtime=1)]

    def stat(self, remote_path):
        if remote_path in self.directories:
            return SimpleNamespace(st_size=0, st_mtime=1, st_mtime_ns=1_000_000_000)
        data = self.files[remote_path]
        return SimpleNamespace(st_size=len(data), st_mtime=1, st_mtime_ns=1_000_000_000)

    def get(self, remote_path, local_path):
        Path(local_path).write_bytes(self.files[remote_path])

    def put(self, local_path, remote_path):
        self.files[remote_path] = Path(local_path).read_bytes()

    def rename(self, old, new):
        if old in self.files:
            self.files[new] = self.files.pop(old)
        elif old in self.directories:
            self.directories.add(new)
            self.directories.discard(old)

    def mkdir(self, remote_dir):
        self.directories.add(remote_dir)

    def remove(self, remote_path):
        self.files.pop(remote_path, None)

    def connect(self, server):
        return object(), self.fake

    def close(self):
        return None


def build_manager(tmp_path):
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
    return MountManager(server_service=server_service, secret_store=secret_store, known_hosts_manager=known_hosts, cache_root=tmp_path / 'cache'), server


def test_remote_drive_path_resolver_roundtrip():
    resolver = RemoteDrivePathResolver('/root')
    assert resolver.to_remote_path('/') == '/root'
    assert resolver.to_remote_path('/a.txt') == '/root/a.txt'
    assert resolver.to_virtual_path('/root/a.txt') == '/a.txt'


def test_virtual_drive_facade_basic_ops(tmp_path):
    manager, server = build_manager(tmp_path)
    mapping = RemoteDriveMapping(id=1, name='rd1', server_id=server.id, remote_root='/root', drive_letter='R')
    original = mount_manager_module.ConnectionManager
    mount_manager_module.ConnectionManager = FakeConnectionManager
    try:
        manager.mount(mapping)
        facade = VirtualDriveFacade(manager)
        rows = facade.list_dir(1, '/')
        assert len(rows) == 1
        assert rows[0].virtual_path == '/a.txt'
        assert facade.read_file(1, '/a.txt') == b'hello'
        facade.write_file(1, '/b.txt', b'world')
        session = manager.session_for(1)
        assert session is not None
        session._upload_task(SimpleNamespace(remote_path='/root/b.txt', retry_count=0))
        facade.rename_file(1, '/b.txt', '/c.txt')
        info = facade.stat_file(1, '/c.txt')
        assert info.virtual_path == '/c.txt'
        facade.delete_file(1, '/c.txt')
    finally:
        manager.unmount_all()
        mount_manager_module.ConnectionManager = original


def test_virtual_drive_facade_handle_ops(tmp_path):
    manager, server = build_manager(tmp_path)
    mapping = RemoteDriveMapping(id=1, name='rd1', server_id=server.id, remote_root='/root', drive_letter='R')
    original = mount_manager_module.ConnectionManager
    mount_manager_module.ConnectionManager = FakeConnectionManager
    try:
        manager.mount(mapping)
        facade = VirtualDriveFacade(manager)
        handle_id = facade.open_file(1, '/new.txt', writable=True, create=True)
        assert facade.read_handle(1, handle_id) == b''
        facade.write_handle(1, handle_id, b'abc')
        facade.flush_handle(1, handle_id)
        session = manager.session_for(1)
        assert session is not None
        assert session.read_bytes('/root/new.txt') == b'abc'
        facade.close_handle(1, handle_id)
        assert session.cache_index.get('/root/new.txt').open_handle_count == 0
    finally:
        manager.unmount_all()
        mount_manager_module.ConnectionManager = original


def test_dokany_adapter_dispatch_basic_ops(tmp_path):
    manager, server = build_manager(tmp_path)
    mapping = RemoteDriveMapping(id=1, name='rd1', server_id=server.id, remote_root='/root', drive_letter='R')
    original = mount_manager_module.ConnectionManager
    mount_manager_module.ConnectionManager = FakeConnectionManager
    try:
        manager.mount(mapping)
        adapter = DokanyAdapter(VirtualDriveFacade(manager))
        open_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.OPEN_FILE, virtual_path='/d.txt', writable=True, create=True, truncate=True))
        assert open_resp.ok is True
        handle_id = open_resp.result['handle_id']
        write_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.WRITE_HANDLE, handle_id=handle_id, payload=b'data', offset=0))
        assert write_resp.ok is True
        assert write_resp.result['is_dirty'] is True
        append_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.WRITE_HANDLE, handle_id=handle_id, payload=b'X', offset=2))
        assert append_resp.ok is True
        flush_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.FLUSH_HANDLE, handle_id=handle_id))
        assert flush_resp.ok is True
        read_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.READ_FILE, virtual_path='/d.txt', offset=1, length=2))
        assert read_resp.ok is True
        assert read_resp.result['payload'] == b'aX'
        list_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.LIST_DIR, virtual_path='/'))
        assert list_resp.ok is True
        assert isinstance(list_resp.result, list)
        close_resp = adapter.dispatch(DokanyRequest(mapping_id=1, operation=DokanyOperation.CLOSE_HANDLE, handle_id=handle_id))
        assert close_resp.ok is True
    finally:
        manager.unmount_all()
        mount_manager_module.ConnectionManager = original
