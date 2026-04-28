from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sftp_auto_sync.domain.errors import ValidationError
from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.sync_engine import SyncEngine
from sftp_auto_sync.ui.dialogs.mapping_dialog import MappingDialog
from sftp_auto_sync.ui.viewmodels.mapping_vm import MappingViewModel

DELETE_POLICY_MAP = {
    'ignore': '忽略',
    'delete_file': '删除文件',
}

BOOL_MAP = {
    True: '是',
    False: '否',
}


class MappingsPage(QWidget):
    def __init__(self, view_model: MappingViewModel, mapping_service: MappingService, server_service: ServerService, sync_engine: SyncEngine, signals=None, parent=None):
        super().__init__(parent)
        self._view_model = view_model
        self._mapping_service = mapping_service
        self._server_service = server_service
        self._sync_engine = sync_engine
        self._signals = signals

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(['名称', '服务器', '本地目录', '远程目录', '递归', '删除策略', '启动扫描', '启用', '更新时间'])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemDoubleClicked.connect(lambda _: self.edit_selected())

        self._add_button = QPushButton('添加')
        self._edit_button = QPushButton('编辑')
        self._delete_button = QPushButton('删除')
        self._toggle_button = QPushButton('启用/禁用')
        self._baseline_button = QPushButton('重建本地基线')
        self._open_button = QPushButton('打开本地目录')
        self._refresh_button = QPushButton('刷新')

        buttons = QHBoxLayout()
        for button in [self._add_button, self._edit_button, self._delete_button, self._toggle_button, self._baseline_button, self._open_button, self._refresh_button]:
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self._table)

        self._add_button.clicked.connect(self.add_mapping)
        self._edit_button.clicked.connect(self.edit_selected)
        self._delete_button.clicked.connect(self.delete_selected)
        self._toggle_button.clicked.connect(self.toggle_selected)
        self._baseline_button.clicked.connect(self.reinitialize_selected_baseline)
        self._open_button.clicked.connect(self.open_local_dir)
        self._refresh_button.clicked.connect(self.refresh)

        self.refresh()

    def _selected_mapping_id(self) -> int | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        item = self._table.item(row, 0)
        return item.data(1000) if item is not None else None

    def refresh(self) -> None:
        rows = self._view_model.rows()
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row['name'],
                row['server_name'],
                row['local_dir'],
                row['remote_dir'],
                BOOL_MAP.get(row['recursive'], str(row['recursive'])),
                DELETE_POLICY_MAP.get(row['delete_policy'], row['delete_policy']),
                BOOL_MAP.get(row['startup_rescan'], str(row['startup_rescan'])),
                BOOL_MAP.get(row['enabled'], str(row['enabled'])),
                row['updated_at'],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if col == 0:
                    item.setData(1000, row['id'])
                self._table.setItem(row_index, col, item)
        self._table.resizeColumnsToContents()

    def add_mapping(self) -> None:
        if not self._server_service.list_all():
            QMessageBox.information(self, '无服务器', '请先创建服务器再创建映射。')
            return
        dialog = MappingDialog(self._server_service, parent=self)
        if dialog.exec() != 1:
            return
        mapping = dialog.get_payload()
        try:
            self._mapping_service.save(mapping)
        except ValidationError as exc:
            QMessageBox.warning(self, '验证错误', '\n'.join(exc.messages))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def edit_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        mapping = self._mapping_service.get(mapping_id)
        if mapping is None:
            return
        dialog = MappingDialog(self._server_service, mapping=mapping, parent=self)
        if dialog.exec() != 1:
            return
        updated = dialog.get_payload()
        try:
            self._mapping_service.save(updated)
        except ValidationError as exc:
            QMessageBox.warning(self, '验证错误', '\n'.join(exc.messages))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def delete_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        if QMessageBox.question(self, '删除映射', '确定删除选中的映射吗?') != QMessageBox.StandardButton.Yes:
            return
        self._mapping_service.delete(mapping_id)
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def toggle_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        mapping = self._mapping_service.get(mapping_id)
        if mapping is None:
            return
        mapping.enabled = not mapping.enabled
        try:
            self._mapping_service.save(mapping)
        except Exception as exc:
            QMessageBox.warning(self, '更新错误', str(exc))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def open_local_dir(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        mapping = self._mapping_service.get(mapping_id)
        if mapping is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(mapping.local_dir))

    def reinitialize_selected_baseline(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        mapping = self._mapping_service.get(mapping_id)
        if mapping is None:
            return
        answer = QMessageBox.question(
            self,
            '重建本地基线',
            '该操作会先停止当前映射上传队列，并按当前本地文件状态重建基线。\n'
            '适用于远程批量改动后重新下载解压，避免把现有文件再次批量上传。\n\n'
            f'确定要重建映射“{mapping.name}”的本地基线吗?',
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._sync_engine.stop_all()
        try:
            self._mapping_service.reinitialize_baseline(mapping_id)
        except Exception as exc:
            QMessageBox.warning(self, '重建失败', str(exc))
        finally:
            self._sync_engine.start_all()

        if self._signals is not None:
            self._signals.config_changed.emit()
            self._signals.dashboard_refresh_requested.emit()
        self.refresh()
