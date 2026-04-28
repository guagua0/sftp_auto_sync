from __future__ import annotations

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
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.sync_engine import SyncEngine
from sftp_auto_sync.ui.dialogs.server_dialog import ServerDialog
from sftp_auto_sync.ui.dialogs.test_connection_dialog import TestConnectionDialog
from sftp_auto_sync.ui.viewmodels.server_vm import ServerViewModel

AUTH_TYPE_MAP = {
    'password': '密码',
    'private_key': '私钥',
}

HOST_KEY_POLICY_MAP = {
    'strict': '严格',
    'tofu': 'TOFU',
}

BOOL_MAP = {
    True: '是',
    False: '否',
}


class ServersPage(QWidget):
    def __init__(self, view_model: ServerViewModel, server_service: ServerService, sync_engine: SyncEngine, signals=None, parent=None):
        super().__init__(parent)
        self._view_model = view_model
        self._server_service = server_service
        self._sync_engine = sync_engine
        self._signals = signals
        self._last_test_results: dict[int, str] = {}

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(['名称', '主机', '端口', '用户名', '认证方式', '主机密钥', '启用', '上次测试', '更新时间'])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemDoubleClicked.connect(lambda _: self.edit_selected())

        self._add_button = QPushButton('添加')
        self._edit_button = QPushButton('编辑')
        self._delete_button = QPushButton('删除')
        self._test_button = QPushButton('测试连接')
        self._toggle_button = QPushButton('启用/禁用')
        self._refresh_button = QPushButton('刷新')

        buttons = QHBoxLayout()
        for button in [self._add_button, self._edit_button, self._delete_button, self._test_button, self._toggle_button, self._refresh_button]:
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self._table)

        self._add_button.clicked.connect(self.add_server)
        self._edit_button.clicked.connect(self.edit_selected)
        self._delete_button.clicked.connect(self.delete_selected)
        self._test_button.clicked.connect(self.test_selected)
        self._toggle_button.clicked.connect(self.toggle_selected)
        self._refresh_button.clicked.connect(self.refresh)

        self.refresh()

    def _selected_server_id(self) -> int | None:
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
                row['host'],
                row['port'],
                row['username'],
                AUTH_TYPE_MAP.get(row['auth_type'], row['auth_type']),
                HOST_KEY_POLICY_MAP.get(row['host_key_policy'], row['host_key_policy']),
                BOOL_MAP.get(row['enabled'], str(row['enabled'])),
                self._last_test_results.get(row['id'], ''),
                row['updated_at'],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value or ''))
                if col == 0:
                    item.setData(1000, row['id'])
                self._table.setItem(row_index, col, item)
        self._table.resizeColumnsToContents()

    def add_server(self) -> None:
        dialog = ServerDialog(self._server_service, parent=self)
        if dialog.exec() != 1:
            return
        payload = dialog.get_payload()
        try:
            self._server_service.save(payload['profile'], password=payload['password'], key_passphrase=payload['key_passphrase'])
        except ValidationError as exc:
            QMessageBox.warning(self, '验证错误', '\n'.join(exc.messages))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def edit_selected(self) -> None:
        server_id = self._selected_server_id()
        if server_id is None:
            return
        profile = self._server_service.get(server_id)
        if profile is None:
            return
        dialog = ServerDialog(self._server_service, profile=profile, parent=self)
        if dialog.exec() != 1:
            return
        payload = dialog.get_payload()
        try:
            self._server_service.save(payload['profile'], password=payload['password'], key_passphrase=payload['key_passphrase'])
        except ValidationError as exc:
            QMessageBox.warning(self, '验证错误', '\n'.join(exc.messages))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def delete_selected(self) -> None:
        server_id = self._selected_server_id()
        if server_id is None:
            return
        if QMessageBox.question(self, '删除服务器', '确定删除选中的服务器吗?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self._server_service.delete(server_id)
        except Exception as exc:
            QMessageBox.warning(self, '删除错误', str(exc))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def test_selected(self) -> None:
        server_id = self._selected_server_id()
        if server_id is None:
            return
        profile = self._server_service.get(server_id)
        if profile is None:
            return
        dialog = TestConnectionDialog(lambda: self._server_service.test_connection(profile), parent=self)
        dialog.exec()
        self._last_test_results[server_id] = dialog.result_text
        self.refresh()

    def toggle_selected(self) -> None:
        server_id = self._selected_server_id()
        if server_id is None:
            return
        profile = self._server_service.get(server_id)
        if profile is None:
            return
        profile.enabled = not profile.enabled
        try:
            self._server_service.save(profile)
        except Exception as exc:
            QMessageBox.warning(self, '更新错误', str(exc))
            return
        self._sync_engine.reload_config()
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()
