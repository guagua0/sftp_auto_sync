from __future__ import annotations

from sftp_auto_sync.domain.enums import AuthType, DeletePolicy, HostKeyPolicy
from sftp_auto_sync.domain.models import FileSnapshot, ServerProfile, SyncMapping
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory
from sftp_auto_sync.infra.db.mapping_repo import MappingRepository
from sftp_auto_sync.infra.db.migration_runner import run_migrations
from sftp_auto_sync.infra.db.server_repo import ServerRepository
from sftp_auto_sync.infra.db.state_repo import StateRepository
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper
from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.validation_service import ValidationService


def test_mapping_service_save_initializes_baseline_without_uploading_existing_files(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)

    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    state_repo = StateRepository(cf)
    path_mapper = PathMapper()
    validation = ValidationService(server_repo)
    service = MappingService(mapping_repo, validation, state_repo, path_mapper)

    server = ServerProfile(
        name='srv1',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server.id = server_repo.create(server)

    local_dir = tmp_path / 'local'
    local_dir.mkdir()
    keep_file = local_dir / 'keep.txt'
    keep_file.write_text('hello', encoding='utf-8')
    ignored_dir = local_dir / '.git'
    ignored_dir.mkdir()
    (ignored_dir / 'config').write_text('ignored', encoding='utf-8')

    mapping = SyncMapping(
        name='map1',
        server_id=server.id,
        local_dir=str(local_dir),
        remote_dir='/remote',
        recursive=True,
        enabled=True,
        delete_policy=DeletePolicy.IGNORE,
        startup_rescan=True,
    )

    saved = service.save(mapping)
    assert saved.id is not None

    states = state_repo.list_by_mapping(saved.id)
    assert [state.relative_path for state in states] == ['keep.txt']
    assert states[0].remote_path == '/remote/keep.txt'
    assert states[0].last_status == 'baseline'
    assert states[0].last_uploaded_at is None
    assert states[0].last_local_size == keep_file.stat().st_size
    assert states[0].last_local_mtime_ns == keep_file.stat().st_mtime_ns


def test_mapping_service_save_respects_non_recursive_baseline(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)

    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    state_repo = StateRepository(cf)
    path_mapper = PathMapper()
    validation = ValidationService(server_repo)
    service = MappingService(mapping_repo, validation, state_repo, path_mapper)

    server = ServerProfile(
        name='srv1',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server.id = server_repo.create(server)

    local_dir = tmp_path / 'local'
    local_dir.mkdir()
    (local_dir / 'top.txt').write_text('top', encoding='utf-8')
    nested = local_dir / 'nested'
    nested.mkdir()
    (nested / 'child.txt').write_text('child', encoding='utf-8')

    saved = service.save(
        SyncMapping(
            name='map1',
            server_id=server.id,
            local_dir=str(local_dir),
            remote_dir='/remote',
            recursive=False,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )
    assert saved.id is not None

    states = state_repo.list_by_mapping(saved.id)
    assert [state.relative_path for state in states] == ['top.txt']


def test_mapping_service_reinitialize_baseline_replaces_old_state(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)

    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    state_repo = StateRepository(cf)
    path_mapper = PathMapper()
    validation = ValidationService(server_repo)
    service = MappingService(mapping_repo, validation, state_repo, path_mapper)

    server = ServerProfile(
        name='srv1',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server.id = server_repo.create(server)

    local_dir = tmp_path / 'local'
    local_dir.mkdir()
    keep_file = local_dir / 'keep.txt'
    keep_file.write_text('new', encoding='utf-8')

    saved = service.save(
        SyncMapping(
            name='map1',
            server_id=server.id,
            local_dir=str(local_dir),
            remote_dir='/remote',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )
    assert saved.id is not None

    state_repo.upsert_success(
        saved.id,
        'stale.txt',
        FileSnapshot(size=1, mtime_ns=1),
        '/remote/stale.txt',
    )

    keep_file.write_text('updated', encoding='utf-8')
    service.reinitialize_baseline(saved.id)

    states = state_repo.list_by_mapping(saved.id)
    assert [state.relative_path for state in states] == ['keep.txt']
    assert states[0].last_status == 'baseline'
    assert states[0].remote_path == '/remote/keep.txt'
    assert states[0].last_local_size == keep_file.stat().st_size


def test_mapping_service_save_allows_same_local_dir_for_same_server(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)

    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    state_repo = StateRepository(cf)
    path_mapper = PathMapper()
    validation = ValidationService(server_repo)
    service = MappingService(mapping_repo, validation, state_repo, path_mapper)

    server = ServerProfile(
        name='srv1',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server.id = server_repo.create(server)

    local_dir = tmp_path / 'local'
    local_dir.mkdir()
    (local_dir / 'a.txt').write_text('a', encoding='utf-8')

    first = service.save(
        SyncMapping(
            name='map1',
            server_id=server.id,
            local_dir=str(local_dir),
            remote_dir='/remote/one',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )
    second = service.save(
        SyncMapping(
            name='map2',
            server_id=server.id,
            local_dir=str(local_dir),
            remote_dir='/remote/two',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )

    assert first.id is not None
    assert second.id is not None
    assert second.id != first.id


def test_mapping_service_save_allows_same_local_dir_for_different_servers(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)

    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    state_repo = StateRepository(cf)
    path_mapper = PathMapper()
    validation = ValidationService(server_repo)
    service = MappingService(mapping_repo, validation, state_repo, path_mapper)

    server1 = ServerProfile(
        name='srv1',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server2 = ServerProfile(
        name='srv2',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server1.id = server_repo.create(server1)
    server2.id = server_repo.create(server2)

    local_dir = tmp_path / 'local'
    local_dir.mkdir()
    (local_dir / 'a.txt').write_text('a', encoding='utf-8')

    first = service.save(
        SyncMapping(
            name='map1',
            server_id=server1.id,
            local_dir=str(local_dir),
            remote_dir='/remote/one',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )
    second = service.save(
        SyncMapping(
            name='map2',
            server_id=server2.id,
            local_dir=str(local_dir),
            remote_dir='/remote/two',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )

    assert first.id is not None
    assert second.id is not None
    assert second.id != first.id


def test_mapping_service_save_allows_overlapping_local_dirs(tmp_path):
    db_path = tmp_path / 'app.db'
    cf = ConnectionFactory(db_path)
    run_migrations(cf)

    server_repo = ServerRepository(cf)
    mapping_repo = MappingRepository(cf)
    state_repo = StateRepository(cf)
    path_mapper = PathMapper()
    validation = ValidationService(server_repo)
    service = MappingService(mapping_repo, validation, state_repo, path_mapper)

    server = ServerProfile(
        name='srv1',
        host='127.0.0.1',
        port=22,
        username='u',
        auth_type=AuthType.PASSWORD,
        connect_timeout_sec=10,
        host_key_policy=HostKeyPolicy.TOFU,
        enabled=True,
        created_at='x',
        updated_at='x',
    )
    server.id = server_repo.create(server)

    parent_dir = tmp_path / 'local'
    child_dir = parent_dir / 'sub'
    child_dir.mkdir(parents=True)
    (parent_dir / 'a.txt').write_text('a', encoding='utf-8')
    (child_dir / 'b.txt').write_text('b', encoding='utf-8')

    first = service.save(
        SyncMapping(
            name='map1',
            server_id=server.id,
            local_dir=str(parent_dir),
            remote_dir='/remote/parent',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )
    second = service.save(
        SyncMapping(
            name='map2',
            server_id=server.id,
            local_dir=str(child_dir),
            remote_dir='/remote/child',
            recursive=True,
            enabled=True,
            delete_policy=DeletePolicy.IGNORE,
            startup_rescan=True,
        )
    )

    assert first.id is not None
    assert second.id is not None
    assert second.id != first.id
