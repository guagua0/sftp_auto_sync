from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sftp_auto_sync.domain.enums import DeletePolicy
from sftp_auto_sync.domain.models import SyncMapping
from sftp_auto_sync.services.server_service import ServerService


class MappingDialog(QDialog):
    def __init__(self, server_service: ServerService, mapping: SyncMapping | None = None, parent=None):
        super().__init__(parent)
        self._server_service = server_service
        self._mapping = mapping or SyncMapping()
        self.setWindowTitle('映射')
        self.resize(640, 460)

        self._name_edit = QLineEdit()
        self._server_combo = QComboBox()
        self._local_dir_edit = QLineEdit()
        self._browse_button = QPushButton('浏览...')
        self._remote_dir_edit = QLineEdit()
        self._recursive_check = QCheckBox('递归')
        self._delete_policy_combo = QComboBox()
        self._delete_policy_combo.addItem('忽略', DeletePolicy.IGNORE)
        self._delete_policy_combo.addItem('删除文件', DeletePolicy.DELETE_FILE)
        self._startup_rescan_check = QCheckBox('启动时扫描')
        self._ignore_edit = QTextEdit()
        self._ignore_edit.setPlaceholderText('每行一个忽略规则，例如：\ndb*\n*.dat\ndata/')
        self._ignore_edit.setToolTip('示例：db* 忽略 db 开头文件，*.dat 忽略 dat 文件，data/ 忽略 data 目录及其内容。')
        self._note_edit = QTextEdit()
        self._enabled_check = QCheckBox('启用')

        local_row = QHBoxLayout()
        local_row.setContentsMargins(0, 0, 0, 0)
        local_row.addWidget(self._local_dir_edit)
        local_row.addWidget(self._browse_button)


        form = QFormLayout()
        form.addRow('名称', self._name_edit)
        form.addRow('服务器', self._server_combo)
        local_row_widget = QWidget()
        local_row_widget.setLayout(local_row)
        form.addRow('本地目录', local_row_widget)
        form.addRow('远程目录', self._remote_dir_edit)
        form.addRow('', self._recursive_check)
        form.addRow('删除策略', self._delete_policy_combo)
        form.addRow('', self._startup_rescan_check)
        form.addRow('忽略模式', self._ignore_edit)
        form.addRow('备注', self._note_edit)
        form.addRow('', self._enabled_check)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._on_save_clicked)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        self._browse_button.clicked.connect(self._browse_local_dir)
        self._populate_servers()
        self._populate_from_mapping()

    def _populate_servers(self) -> None:
        self._server_combo.clear()
        for server in self._server_service.list_all():
            if server.id is not None:
                self._server_combo.addItem(server.name, server.id)

    def _populate_from_mapping(self) -> None:
        self._name_edit.setText(self._mapping.name)
        self._local_dir_edit.setText(self._mapping.local_dir)
        self._remote_dir_edit.setText(self._mapping.remote_dir)
        self._recursive_check.setChecked(self._mapping.recursive)
        self._startup_rescan_check.setChecked(self._mapping.startup_rescan)
        self._enabled_check.setChecked(self._mapping.enabled)
        self._ignore_edit.setPlainText('\n'.join(self._mapping.ignore_patterns))
        self._note_edit.setPlainText(self._mapping.note or '')
        self._select_server(self._mapping.server_id)
        self._select_delete_policy(self._mapping.delete_policy)

    def _select_server(self, server_id: int) -> None:
        for index in range(self._server_combo.count()):
            if self._server_combo.itemData(index) == server_id:
                self._server_combo.setCurrentIndex(index)
                return

    def _select_delete_policy(self, policy: DeletePolicy) -> None:
        for index in range(self._delete_policy_combo.count()):
            if self._delete_policy_combo.itemData(index) == policy:
                self._delete_policy_combo.setCurrentIndex(index)
                return

    def _browse_local_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, '选择本地目录', str(Path.home()))
        if directory:
            self._local_dir_edit.setText(directory)

    def get_payload(self) -> SyncMapping:
        ignore_patterns = [line.strip() for line in self._ignore_edit.toPlainText().splitlines() if line.strip()]
        return SyncMapping(
            id=self._mapping.id,
            name=self._name_edit.text().strip(),
            server_id=int(self._server_combo.currentData() or 0),
            local_dir=self._local_dir_edit.text().strip(),
            remote_dir=self._remote_dir_edit.text().strip(),
            recursive=self._recursive_check.isChecked(),
            enabled=self._enabled_check.isChecked(),
            delete_policy=self._delete_policy_combo.currentData(),
            startup_rescan=self._startup_rescan_check.isChecked(),
            ignore_patterns=ignore_patterns,
            note=self._note_edit.toPlainText().strip() or None,
            created_at=self._mapping.created_at,
            updated_at=self._mapping.updated_at,
        )

    def _validate(self) -> list[str]:
        errors: list[str] = []
        if not self._name_edit.text().strip():
            errors.append('映射名称不能为空。')
        if self._server_combo.currentData() is None:
            errors.append('请选择一个服务器。')
        if not self._local_dir_edit.text().strip():
            errors.append('本地目录不能为空。')
        if not self._remote_dir_edit.text().strip():
            errors.append('远程目录不能为空。')
        if self._remote_dir_edit.text().strip() and not self._remote_dir_edit.text().strip().startswith('/'):
            errors.append('远程目录必须是以 / 开头的绝对路径。')
        return errors

    def _on_save_clicked(self) -> None:
        errors = self._validate()
        if errors:
            QMessageBox.warning(self, '验证错误', '\n'.join(errors))
            return
        self.accept()
