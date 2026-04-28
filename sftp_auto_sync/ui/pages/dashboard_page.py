from __future__ import annotations

from datetime import datetime, timezone, timedelta

from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sftp_auto_sync.ui.viewmodels.dashboard_vm import DashboardViewModel

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

ENGINE_STATE_MAP = {
    'stopped': '已停止',
    'running': '运行中',
    'error': '错误',
}


class DashboardPage(QWidget):
    def __init__(self, view_model: DashboardViewModel, parent=None):
        super().__init__(parent)
        self._view_model = view_model
        self._worker_payloads: dict[int, dict] = {}

        self._total_servers_value = QLabel('0')
        self._enabled_servers_value = QLabel('0')
        self._total_mappings_value = QLabel('0')
        self._running_mappings_value = QLabel('0')
        self._engine_state_value = QLabel('已停止')
        self._queue_length_value = QLabel('0')
        self._active_workers_value = QLabel('0')
        self._last_error_value = QLabel('')
        self._last_error_value.setWordWrap(True)

        stats_group = QGroupBox('概览')
        stats_layout = QGridLayout(stats_group)
        stats_layout.addWidget(QLabel('服务器总数'), 0, 0)
        stats_layout.addWidget(self._total_servers_value, 0, 1)
        stats_layout.addWidget(QLabel('已启用服务器'), 0, 2)
        stats_layout.addWidget(self._enabled_servers_value, 0, 3)
        stats_layout.addWidget(QLabel('映射总数'), 1, 0)
        stats_layout.addWidget(self._total_mappings_value, 1, 1)
        stats_layout.addWidget(QLabel('运行中映射'), 1, 2)
        stats_layout.addWidget(self._running_mappings_value, 1, 3)
        stats_layout.addWidget(QLabel('引擎状态'), 2, 0)
        stats_layout.addWidget(self._engine_state_value, 2, 1)
        stats_layout.addWidget(QLabel('队列长度'), 2, 2)
        stats_layout.addWidget(self._queue_length_value, 2, 3)
        stats_layout.addWidget(QLabel('活动工作线程'), 3, 0)
        stats_layout.addWidget(self._active_workers_value, 3, 1)
        stats_layout.addWidget(QLabel('最后错误'), 4, 0)
        stats_layout.addWidget(self._last_error_value, 4, 1, 1, 3)

        self._worker_table = QTableWidget(0, 4)
        self._worker_table.setHorizontalHeaderLabels(['服务器', '状态', '路径', '消息'])
        self._worker_table.horizontalHeader().setStretchLastSection(True)

        self._history_table = QTableWidget(0, 6)
        self._history_table.setHorizontalHeaderLabels(['时间', '服务器', '映射', '操作', '状态', '路径'])
        self._history_table.horizontalHeader().setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.addWidget(stats_group)
        layout.addWidget(QLabel('工作线程状态'))
        layout.addWidget(self._worker_table)
        layout.addWidget(QLabel('最近历史'))
        layout.addWidget(self._history_table)

        self.refresh()

    def refresh(self) -> None:
        snapshot = self._view_model.snapshot()
        self._total_servers_value.setText(str(snapshot.total_servers))
        self._enabled_servers_value.setText(str(snapshot.enabled_servers))
        self._total_mappings_value.setText(str(snapshot.total_mappings))
        self._running_mappings_value.setText(str(snapshot.running_mappings))
        self._engine_state_value.setText(snapshot.engine_state)
        self._queue_length_value.setText(str(snapshot.queue_length))
        self._active_workers_value.setText(str(snapshot.active_workers))
        self._last_error_value.setText(snapshot.last_error)
        self._populate_history(self._view_model.recent_history(20))

    def _populate_history(self, rows: list[dict]) -> None:
        self._history_table.setRowCount(len(rows))
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
            ]
            for col, value in enumerate(values):
                self._history_table.setItem(row_index, col, QTableWidgetItem(str(value or '')))
        self._history_table.resizeColumnsToContents()

    def handle_worker_status(self, payload: dict) -> None:
        self._worker_payloads[payload['server_id']] = payload
        if payload.get('status') == 'failed':
            self._last_error_value.setText(payload.get('message', ''))
        self._render_workers()

    def _render_workers(self) -> None:
        rows = list(self._worker_payloads.values())
        self._worker_table.setRowCount(len(rows))
        for row_index, payload in enumerate(rows):
            status = STATUS_MAP.get(payload.get('status', ''), payload.get('status', ''))
            values = [
                payload.get('server_name', ''),
                status,
                payload.get('relative_path', ''),
                payload.get('message', ''),
            ]
            for col, value in enumerate(values):
                self._worker_table.setItem(row_index, col, QTableWidgetItem(str(value or '')))
        self._worker_table.resizeColumnsToContents()

    def handle_queue_stats(self, payload: dict) -> None:
        self._queue_length_value.setText(str(payload.get('total_queue_length', 0)))

    def handle_engine_state(self, state: str) -> None:
        self._engine_state_value.setText(ENGINE_STATE_MAP.get(state, state))
