from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFormLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget

from sftp_auto_sync.app.app_paths import AppPaths
from sftp_auto_sync.app.constants import SETTING_DEBOUNCE_MS, SETTING_LOG_RETENTION_ROWS, SETTING_STARTUP_AUTO_START_ENGINE
from sftp_auto_sync.infra.db.settings_repo import SettingsRepository
from sftp_auto_sync.services.sync_engine import SyncEngine


class SettingsPage(QWidget):
    def __init__(self, app_paths: AppPaths, settings_repo: SettingsRepository, sync_engine: SyncEngine, signals=None, parent=None):
        super().__init__(parent)
        self._app_paths = app_paths
        self._settings_repo = settings_repo
        self._sync_engine = sync_engine
        self._signals = signals

        self._app_data_label = QLabel(str(app_paths.root))
        self._app_data_label.setWordWrap(True)
        self._log_retention_spin = QSpinBox()
        self._log_retention_spin.setRange(1000, 1000000)
        self._debounce_spin = QSpinBox()
        self._debounce_spin.setRange(100, 10000)
        self._auto_start_check = QCheckBox('启动时自动启动引擎')
        self._save_button = QPushButton('保存')

        form = QFormLayout()
        form.addRow('应用数据目录', self._app_data_label)
        form.addRow('日志保留行数', self._log_retention_spin)
        form.addRow('防抖毫秒', self._debounce_spin)
        form.addRow('', self._auto_start_check)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._save_button)
        layout.addStretch(1)

        self._save_button.clicked.connect(self.save)
        self.refresh()

    def refresh(self) -> None:
        self._log_retention_spin.setValue(self._settings_repo.get_int(SETTING_LOG_RETENTION_ROWS, 20000))
        self._debounce_spin.setValue(self._settings_repo.get_int(SETTING_DEBOUNCE_MS, 800))
        self._auto_start_check.setChecked(self._settings_repo.get_bool(SETTING_STARTUP_AUTO_START_ENGINE, True))

    def save(self) -> None:
        self._settings_repo.set(SETTING_LOG_RETENTION_ROWS, str(self._log_retention_spin.value()))
        self._settings_repo.set(SETTING_DEBOUNCE_MS, str(self._debounce_spin.value()))
        self._settings_repo.set(SETTING_STARTUP_AUTO_START_ENGINE, '1' if self._auto_start_check.isChecked() else '0')
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        QMessageBox.information(self, '设置', '设置已保存。')
