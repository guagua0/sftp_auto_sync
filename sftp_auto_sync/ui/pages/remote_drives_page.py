from __future__ import annotations

import threading
from PySide6.QtCore import QTimer
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
from sftp_auto_sync.services.remote_drive_service import RemoteDriveService
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.ui.dialogs.remote_drive_dialog import RemoteDriveDialog
from sftp_auto_sync.ui.viewmodels.remote_drive_vm import RemoteDriveViewModel


class RemoteDrivesPage(QWidget):
    def __init__(
        self,
        view_model: RemoteDriveViewModel,
        remote_drive_service: RemoteDriveService,
        server_service: ServerService,
        signals=None,
        parent=None,
    ):
        super().__init__(parent)
        self._view_model = view_model
        self._remote_drive_service = remote_drive_service
        self._server_service = server_service
        self._signals = signals
        
        self._mount_status = None
        self._mount_error = None
        self._mount_timer = None
        self._unmount_status = None
        self._unmount_timer = None

        self._table = QTableWidget(0, 13)
        self._table.setHorizontalHeaderLabels(['名称', '服务器', '远程根目录', '盘符', '状态', '后端', '盘符已挂载', '状态说明', '待上传', '自动挂载', '只读', '启用', '更新时间'])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.itemDoubleClicked.connect(lambda _: self.edit_selected())

        self._add_button = QPushButton('添加')
        self._edit_button = QPushButton('编辑')
        self._delete_button = QPushButton('删除')
        self._mount_button = QPushButton('挂载')
        self._unmount_button = QPushButton('卸载')
        self._toggle_button = QPushButton('启用/禁用')
        self._refresh_button = QPushButton('刷新')
        self._capability_button = QPushButton('查看能力')

        buttons = QHBoxLayout()
        for button in [self._add_button, self._edit_button, self._delete_button, self._mount_button, self._unmount_button, self._toggle_button, self._refresh_button, self._capability_button]:
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self._table)

        self._add_button.clicked.connect(self.add_mapping)
        self._edit_button.clicked.connect(self.edit_selected)
        self._delete_button.clicked.connect(self.delete_selected)
        self._mount_button.clicked.connect(self.mount_selected)
        self._unmount_button.clicked.connect(self.unmount_selected)
        self._toggle_button.clicked.connect(self.toggle_selected)
        self._refresh_button.clicked.connect(self.refresh)
        self._capability_button.clicked.connect(self.show_capabilities)

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
                row['remote_root'],
                row['drive_letter'],
                row['status'],
                row['backend'],
                row['drive_mounted'],
                row['status_message'],
                row['pending_uploads'],
                row['auto_mount'],
                row['read_only'],
                row['enabled'],
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
            QMessageBox.information(self, '无服务器', '请先创建服务器，再创建远程盘映射。')
            return
        dialog = RemoteDriveDialog(self._server_service, parent=self)
        if dialog.exec() != 1:
            return
        mapping = dialog.get_payload()
        try:
            self._remote_drive_service.save(mapping)
        except ValidationError as exc:
            QMessageBox.warning(self, '验证错误', '\n'.join(exc.messages))
            return
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def edit_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        mapping = self._remote_drive_service.get(mapping_id)
        if mapping is None:
            return
        dialog = RemoteDriveDialog(self._server_service, mapping=mapping, parent=self)
        if dialog.exec() != 1:
            return
        updated = dialog.get_payload()
        try:
            self._remote_drive_service.save(updated)
        except ValidationError as exc:
            QMessageBox.warning(self, '验证错误', '\n'.join(exc.messages))
            return
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def delete_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        if QMessageBox.question(self, '删除远程盘映射', '确定删除选中的远程盘映射吗？') != QMessageBox.StandardButton.Yes:
            return
        self._remote_drive_service.delete(mapping_id)
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def mount_selected(self) -> None:
        import logging
        import traceback
        import os
        
        # 强制输出日志到文件
        log_dir = os.path.expanduser('~/sftp_auto_sync_logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'mount.log')
        
        # 配置根日志记录器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        if not root_logger.handlers:
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            fh.setFormatter(formatter)
            root_logger.addHandler(fh)
        
        logger = logging.getLogger(__name__)
        logger.info('=== mount_selected called ===')
        
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            logger.warning('No mapping selected')
            return
        
        logger.info('Selected mapping_id=%s', mapping_id)
        
        self._table.setEnabled(False)
        self._mount_status = None
        self._mount_error = None
        
        def do_mount():
            try:
                logger.info('Thread: Starting mount for mapping_id=%s', mapping_id)
                status = self._remote_drive_service.mount(mapping_id)
                logger.info('Thread: mount returned status=%s', status.state)
                self._mount_status = status
            except Exception as e:
                logger.exception('Thread: Mount failed with exception')
                self._mount_error = f'{type(e).__name__}: {str(e)}'
        
        thread = threading.Thread(target=do_mount, daemon=True)
        thread.start()
        
        def check_result():
            if thread.is_alive():
                return
            logger.info('Thread completed, calling _on_mount_complete')
            self._on_mount_complete()
        
        self._mount_timer = QTimer()
        self._mount_timer.timeout.connect(check_result)
        self._mount_timer.start(500)
        
        QTimer.singleShot(30000, lambda: self._on_mount_timeout(thread))
    
    def _on_mount_complete(self):
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            self._mount_timer.stop()
        except:
            pass
        
        self._table.setEnabled(True)
        
        logger.info('_on_mount_complete: error=%s, status=%s', self._mount_error, self._mount_status)
        
        if self._mount_error:
            QMessageBox.warning(self, '挂载失败', f'挂载时发生错误: {self._mount_error}')
        elif self._mount_status:
            if self._mount_status.state == 'error':
                QMessageBox.warning(self, '挂载失败', self._mount_status.message)
            elif self._mount_status.state == 'degraded':
                QMessageBox.information(self, '已进入降级模式', self._mount_status.message)
            elif self._mount_status.state == 'running':
                QMessageBox.information(self, '挂载成功', self._mount_status.message)
        self.refresh()
    
    def _on_mount_timeout(self, thread: threading.Thread):
        import logging
        logger = logging.getLogger(__name__)
        
        if thread.is_alive():
            logger.warning('Mount timeout, thread still alive')
            try:
                self._mount_timer.stop()
            except:
                pass
            self._table.setEnabled(True)
            QMessageBox.warning(self, '挂载超时', '挂载操作超时，请检查网络连接或服务器状态。')
            self.refresh()

    def unmount_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        
        self._table.setEnabled(False)
        
        def do_unmount():
            self._unmount_status = self._remote_drive_service.unmount(mapping_id)
        
        thread = threading.Thread(target=do_unmount, daemon=True)
        thread.start()
        
        def check_result():
            if thread.is_alive():
                return
            self._unmount_timer.stop()
            self._table.setEnabled(True)
            self.refresh()
        
        self._unmount_timer = QTimer()
        self._unmount_timer.timeout.connect(check_result)
        self._unmount_timer.start(100)
        
        QTimer.singleShot(10000, lambda: self._on_unmount_timeout(thread))
    
    def _on_unmount_timeout(self, thread: threading.Thread):
        if thread.is_alive():
            self._unmount_timer.stop()
            self._table.setEnabled(True)
            QMessageBox.warning(self, '卸载超时', '卸载操作超时。')
            self.refresh()

    def toggle_selected(self) -> None:
        mapping_id = self._selected_mapping_id()
        if mapping_id is None:
            return
        mapping = self._remote_drive_service.get(mapping_id)
        if mapping is None:
            return
        mapping.enabled = not mapping.enabled
        try:
            self._remote_drive_service.save(mapping)
        except ValidationError as exc:
            QMessageBox.warning(self, '更新错误', '\n'.join(exc.messages))
            return
        if self._signals is not None:
            self._signals.config_changed.emit()
        self.refresh()

    def show_capabilities(self) -> None:
        summary = self._remote_drive_service.capability_summary()
        QMessageBox.information(
            self,
            '远程盘能力',
            f"WinFSPy 可用: {summary.get('winfspy_available', False)}\n"
            f"库版本: {summary.get('lib_version', 'unknown')}\n"
            f"说明: {summary.get('winfspy_message', 'N/A')}",
        )
