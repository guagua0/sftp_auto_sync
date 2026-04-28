from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from sftp_auto_sync.app.app_paths import build_app_paths
from sftp_auto_sync.app.constants import DEFAULT_DEBOUNCE_MS, DEFAULT_HISTORY_KEEP_ROWS, SETTING_DEBOUNCE_MS, SETTING_LOG_RETENTION_ROWS, SETTING_STARTUP_AUTO_START_ENGINE
from sftp_auto_sync.app.signals import AppSignals
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.infra.db.mapping_repo import MappingRepository
from sftp_auto_sync.infra.db.migration_runner import run_migrations
from sftp_auto_sync.infra.db.remote_drive_mapping_repo import RemoteDriveMappingRepository
from sftp_auto_sync.infra.db.server_repo import ServerRepository
from sftp_auto_sync.infra.db.settings_repo import SettingsRepository
from sftp_auto_sync.infra.db.state_repo import StateRepository
from sftp_auto_sync.infra.logging.log_setup import setup_logging
from sftp_auto_sync.infra.secrets.secret_store import SecretStore
from sftp_auto_sync.infra.sftp.host_keys import KnownHostsManager
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper
from sftp_auto_sync.remote_drive.mount_manager import MountManager
from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.remote_drive_service import RemoteDriveService
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.startup_rescan_service import StartupRescanService
from sftp_auto_sync.services.sync_engine import SyncEngine
from sftp_auto_sync.services.validation_service import ValidationService
from sftp_auto_sync.ui.main_window import MainWindow
from sftp_auto_sync.ui.viewmodels.dashboard_vm import DashboardViewModel
from sftp_auto_sync.ui.viewmodels.log_vm import LogViewModel
from sftp_auto_sync.ui.viewmodels.mapping_vm import MappingViewModel
from sftp_auto_sync.ui.viewmodels.remote_drive_vm import RemoteDriveViewModel
from sftp_auto_sync.ui.viewmodels.server_vm import ServerViewModel


def bootstrap() -> int:
    app_paths = build_app_paths()
    signals = AppSignals()
    logger = setup_logging(app_paths, signals)

    connection_factory = ConnectionFactory(app_paths.db_path)
    run_migrations(connection_factory)

    server_repo = ServerRepository(connection_factory)
    mapping_repo = MappingRepository(connection_factory)
    remote_drive_mapping_repo = RemoteDriveMappingRepository(connection_factory)
    state_repo = StateRepository(connection_factory)
    history_repo = HistoryRepository(connection_factory)
    settings_repo = SettingsRepository(connection_factory)
    settings_repo.ensure_defaults(
        {
            SETTING_LOG_RETENTION_ROWS: str(DEFAULT_HISTORY_KEEP_ROWS),
            SETTING_DEBOUNCE_MS: str(DEFAULT_DEBOUNCE_MS),
            SETTING_STARTUP_AUTO_START_ENGINE: '1',
        }
    )

    secret_store = SecretStore()
    known_hosts_manager = KnownHostsManager(app_paths.known_hosts_path)
    path_mapper = PathMapper()
    validation_service = ValidationService(server_repo)
    server_service = ServerService(
        server_repo,
        mapping_repo,
        remote_drive_mapping_repo,
        history_repo,
        secret_store,
        validation_service,
        known_hosts_manager,
        logger=logger,
    )
    mount_manager = MountManager(
        server_service=server_service,
        secret_store=secret_store,
        known_hosts_manager=known_hosts_manager,
        cache_root=app_paths.cache_dir,
        logger=logger,
    )
    mapping_service = MappingService(mapping_repo, validation_service, state_repo, path_mapper, logger=logger)
    remote_drive_service = RemoteDriveService(remote_drive_mapping_repo, validation_service, mount_manager=mount_manager, logger=logger)
    startup_rescan_service = StartupRescanService(state_repo, path_mapper)
    sync_engine = SyncEngine(
        server_repo=server_repo,
        mapping_repo=mapping_repo,
        state_repo=state_repo,
        history_repo=history_repo,
        settings_repo=settings_repo,
        secret_store=secret_store,
        known_hosts_manager=known_hosts_manager,
        path_mapper=path_mapper,
        startup_rescan_service=startup_rescan_service,
        signals=signals,
        logger=logger,
    )

    server_vm = ServerViewModel(server_service)
    mapping_vm = MappingViewModel(mapping_service, server_service)
    remote_drive_vm = RemoteDriveViewModel(remote_drive_service, server_service)
    dashboard_vm = DashboardViewModel(server_service, mapping_service, history_repo, sync_engine)
    log_vm = LogViewModel(history_repo, server_service, mapping_service)

    app = QApplication(sys.argv)
    window = MainWindow(
        app_paths=app_paths,
        settings_repo=settings_repo,
        server_service=server_service,
        mapping_service=mapping_service,
        remote_drive_service=remote_drive_service,
        history_repo=history_repo,
        server_vm=server_vm,
        mapping_vm=mapping_vm,
        remote_drive_vm=remote_drive_vm,
        dashboard_vm=dashboard_vm,
        log_vm=log_vm,
        sync_engine=sync_engine,
        signals=signals,
    )
    if settings_repo.get_bool(SETTING_STARTUP_AUTO_START_ENGINE, True):
        sync_engine.start_all()
    remote_drive_service.auto_mount_enabled()
    window.show()
    return app.exec()
