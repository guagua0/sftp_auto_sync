from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QToolBar,
)

from sftp_auto_sync.app.app_paths import AppPaths
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.infra.db.settings_repo import SettingsRepository
from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.remote_drive_service import RemoteDriveService
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.sync_engine import SyncEngine
from sftp_auto_sync.ui.pages.dashboard_page import DashboardPage
from sftp_auto_sync.ui.pages.logs_page import LogsPage
from sftp_auto_sync.ui.pages.mappings_page import MappingsPage
from sftp_auto_sync.ui.pages.remote_drives_page import RemoteDrivesPage
from sftp_auto_sync.ui.pages.servers_page import ServersPage
from sftp_auto_sync.ui.pages.settings_page import SettingsPage
from sftp_auto_sync.ui.viewmodels.dashboard_vm import DashboardViewModel
from sftp_auto_sync.ui.viewmodels.log_vm import LogViewModel
from sftp_auto_sync.ui.viewmodels.mapping_vm import MappingViewModel
from sftp_auto_sync.ui.viewmodels.remote_drive_vm import RemoteDriveViewModel
from sftp_auto_sync.ui.viewmodels.server_vm import ServerViewModel


class MainWindow(QMainWindow):
    def __init__(
        self,
        *,
        app_paths: AppPaths,
        settings_repo: SettingsRepository,
        server_service: ServerService,
        mapping_service: MappingService,
        remote_drive_service: RemoteDriveService,
        history_repo: HistoryRepository,
        server_vm: ServerViewModel,
        mapping_vm: MappingViewModel,
        remote_drive_vm: RemoteDriveViewModel,
        dashboard_vm: DashboardViewModel,
        log_vm: LogViewModel,
        sync_engine: SyncEngine,
        signals=None,
    ):
        super().__init__()
        self._signals = signals
        self._sync_engine = sync_engine
        self._remote_drive_service = remote_drive_service
        self.setWindowTitle('SFTP 自动同步')
        self.resize(1360, 820)

        self._dashboard_page = DashboardPage(dashboard_vm)
        self._servers_page = ServersPage(server_vm, server_service, sync_engine, signals=signals)
        self._mappings_page = MappingsPage(mapping_vm, mapping_service, server_service, sync_engine, signals=signals)
        self._remote_drives_page = RemoteDrivesPage(remote_drive_vm, remote_drive_service, server_service, signals=signals)
        self._logs_page = LogsPage(log_vm)
        self._settings_page = SettingsPage(app_paths, settings_repo, sync_engine, signals=signals)

        self._navigation = QListWidget()
        self._navigation.setFixedWidth(180)
        for label in ['仪表板', '服务器', '映射', '远程盘', '日志', '设置']:
            QListWidgetItem(label, self._navigation)
        self._navigation.currentRowChanged.connect(self._switch_page)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._dashboard_page)
        self._stack.addWidget(self._servers_page)
        self._stack.addWidget(self._mappings_page)
        self._stack.addWidget(self._remote_drives_page)
        self._stack.addWidget(self._logs_page)
        self._stack.addWidget(self._settings_page)

        splitter = QSplitter()
        splitter.addWidget(self._navigation)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        toolbar = QToolBar('引擎')
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)
        self._start_action = toolbar.addAction('启动引擎')
        self._stop_action = toolbar.addAction('停止引擎')
        self._reload_action = toolbar.addAction('重载配置')
        self._refresh_action = toolbar.addAction('刷新页面')
        self._start_action.triggered.connect(self._sync_engine.start_all)
        self._stop_action.triggered.connect(self._sync_engine.stop_all)
        self._reload_action.triggered.connect(self._sync_engine.reload_config)
        self._refresh_action.triggered.connect(self.refresh_current_page)

        status = QStatusBar()
        self.setStatusBar(status)
        self.statusBar().showMessage('就绪')

        self._navigation.setCurrentRow(0)

        if self._signals is not None:
            self._signals.engine_state_changed.connect(self._on_engine_state_changed)
            self._signals.queue_stats_changed.connect(self._on_queue_stats_changed)
            self._signals.worker_status.connect(self._dashboard_page.handle_worker_status)
            self._signals.worker_status.connect(self._on_worker_status)
            self._signals.history_changed.connect(self._on_history_changed)
            self._signals.dashboard_refresh_requested.connect(self._dashboard_page.refresh)
            self._signals.config_changed.connect(self.refresh_all_pages)
            self._signals.error_occurred.connect(self._on_error)

    def _switch_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.refresh_current_page()

    def refresh_current_page(self) -> None:
        widget = self._stack.currentWidget()
        if hasattr(widget, 'refresh'):
            widget.refresh()

    def refresh_all_pages(self) -> None:
        self._dashboard_page.refresh()
        self._servers_page.refresh()
        self._mappings_page.refresh()
        self._remote_drives_page.refresh()
        self._logs_page.refresh()
        self._settings_page.refresh()

    def _on_engine_state_changed(self, state: str) -> None:
        self.statusBar().showMessage(f'引擎: {state}')
        self._dashboard_page.handle_engine_state(state)

    def _on_queue_stats_changed(self, payload: dict) -> None:
        self._dashboard_page.handle_queue_stats(payload)

    def _on_worker_status(self, payload: dict) -> None:
        if payload.get('status') == 'failed':
            self.statusBar().showMessage(f"失败: {payload.get('message', '')}")

    def _on_history_changed(self) -> None:
        self._dashboard_page.refresh()
        self._logs_page.refresh()

    def _on_error(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def closeEvent(self, event) -> None:
        try:
            self._remote_drive_service.unmount_all()
            self._sync_engine.stop_all()
        except Exception as exc:
            QMessageBox.warning(self, '关闭错误', str(exc))
        super().closeEvent(event)
