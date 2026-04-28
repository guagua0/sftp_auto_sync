from __future__ import annotations

from datetime import datetime, timezone, timedelta

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sftp_auto_sync.ui.viewmodels.log_vm import LogViewModel

BEIJING_TZ = timezone(timedelta(hours=8))

ACTION_MAP = {
    'upsert': '上传/更新',
    'delete': '删除',
    'test_connection': '测试连接',
}

STATUS_MAP = {
    'success': '成功',
    'failed': '失败',
    'skipped': '跳过',
    'pending': '等待',
    'running': '运行中',
}


class LogsPage(QWidget):
    def __init__(self, view_model: LogViewModel, parent=None):
        super().__init__(parent)
        self._view_model = view_model

        self._server_combo = QComboBox()
        self._mapping_combo = QComboBox()
        self._status_combo = QComboBox()
        self._status_combo.addItem('全部', None)
        self._status_combo.addItem('成功', 'success')
        self._status_combo.addItem('失败', 'failed')
        self._status_combo.addItem('跳过', 'skipped')
        self._keyword_edit = QLineEdit()
        self._keyword_edit.setPlaceholderText('关键字')
        self._refresh_button = QPushButton('刷新')
        self._copy_button = QPushButton('复制消息')
        self._clear_button = QPushButton('清空日志')

        filters = QHBoxLayout()
        filters.addWidget(QLabel('服务器'))
        filters.addWidget(self._server_combo)
        filters.addWidget(QLabel('映射'))
        filters.addWidget(self._mapping_combo)
        filters.addWidget(QLabel('状态'))
        filters.addWidget(self._status_combo)
        filters.addWidget(self._keyword_edit)
        filters.addWidget(self._refresh_button)
        filters.addWidget(self._copy_button)
        filters.addWidget(self._clear_button)

        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(['时间', '服务器', '映射', '操作', '状态', '路径', '消息'])
        self._table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self._table)

        self._refresh_button.clicked.connect(self.refresh)
        self._copy_button.clicked.connect(self.copy_selected_message)
        self._clear_button.clicked.connect(self.clear_logs)

        self._load_filter_options()
        self.refresh()

    def _load_filter_options(self) -> None:
        self._server_combo.clear()
        self._server_combo.addItem('全部', None)
        for server_id, name in self._view_model.server_options():
            self._server_combo.addItem(name, server_id)
        self._mapping_combo.clear()
        self._mapping_combo.addItem('全部', None)
        for mapping_id, name in self._view_model.mapping_options():
            self._mapping_combo.addItem(name, mapping_id)

    def refresh(self) -> None:
        rows = self._view_model.rows(
            limit=500,
            mapping_id=self._mapping_combo.currentData(),
            server_id=self._server_combo.currentData(),
            status=self._status_combo.currentData(),
            keyword=self._keyword_edit.text().strip() or None,
        )
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            created_at = row.get('created_at', '')
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt = dt.astimezone(BEIJING_TZ)
                    created_at = dt.strftime('%Y/%m/%d %H:%M:%S')
                except (ValueError, TypeError):
                    pass
            action = ACTION_MAP.get(row.get('action', ''), row.get('action', ''))
            status = STATUS_MAP.get(row.get('status', ''), row.get('status', ''))
            values = [
                created_at,
                row.get('server_name', ''),
                row.get('mapping_name', ''),
                action,
                status,
                row.get('relative_path', ''),
                row.get('message', ''),
            ]
            for col, value in enumerate(values):
                self._table.setItem(row_index, col, QTableWidgetItem(str(value or '')))
        self._table.resizeColumnsToContents()

    def copy_selected_message(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 6)
        if item is None:
            return
        QApplication.clipboard().setText(item.text())

    def clear_logs(self) -> None:
        reply = QMessageBox.question(
            self,
            '确认清空',
            '确定要清空所有日志吗？此操作不可恢复。',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._view_model.clear_all()
            self.refresh()
