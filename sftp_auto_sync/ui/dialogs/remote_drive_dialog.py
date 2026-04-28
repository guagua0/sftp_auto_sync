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
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sftp_auto_sync.domain.models import RemoteDriveMapping
from sftp_auto_sync.services.server_service import ServerService


class RemoteDriveDialog(QDialog):
    def __init__(self, server_service: ServerService, mapping: RemoteDriveMapping | None = None, parent=None):
        super().__init__(parent)
        self._server_service = server_service
        self._mapping = mapping or RemoteDriveMapping()
        self.setWindowTitle('远程盘映射')
        self.resize(640, 480)

        self._name_edit = QLineEdit()
        self._server_combo = QComboBox()
        self._remote_root_edit = QLineEdit()
        self._drive_letter_edit = QLineEdit()
        self._drive_letter_edit.setMaxLength(2)
        self._cache_root_edit = QLineEdit()
        self._browse_button = QPushButton('浏览...')
        self._enabled_check = QCheckBox('启用')
        self._auto_mount_check = QCheckBox('启动后自动挂载')
        self._read_only_check = QCheckBox('只读模式')
        self._cache_limit_spin = QSpinBox()
        self._cache_limit_spin.setRange(1, 1024 * 1024)
        self._cache_limit_spin.setSuffix(' MB')
        self._metadata_ttl_spin = QSpinBox()
        self._metadata_ttl_spin.setRange(0, 3600)
        self._metadata_ttl_spin.setSuffix(' s')
        self._download_timeout_spin = QSpinBox()
        self._download_timeout_spin.setRange(1, 3600)
        self._download_timeout_spin.setSuffix(' s')
        self._upload_timeout_spin = QSpinBox()
        self._upload_timeout_spin.setRange(1, 3600)
        self._upload_timeout_spin.setSuffix(' s')
        self._note_edit = QTextEdit()

        cache_row = QHBoxLayout()
        cache_row.setContentsMargins(0, 0, 0, 0)
        cache_row.addWidget(self._cache_root_edit)
        cache_row.addWidget(self._browse_button)
        cache_widget = QWidget()
        cache_widget.setLayout(cache_row)

        form = QFormLayout()
        form.addRow('名称', self._name_edit)
        form.addRow('服务器', self._server_combo)
        form.addRow('远程根目录', self._remote_root_edit)
        form.addRow('盘符', self._drive_letter_edit)
        form.addRow('缓存根目录', cache_widget)
        form.addRow('缓存大小上限', self._cache_limit_spin)
        form.addRow('元数据缓存 TTL', self._metadata_ttl_spin)
        form.addRow('下载超时', self._download_timeout_spin)
        form.addRow('上传超时', self._upload_timeout_spin)
        form.addRow('', self._enabled_check)
        form.addRow('', self._auto_mount_check)
        form.addRow('', self._read_only_check)
        form.addRow('备注', self._note_edit)

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._on_save_clicked)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        self._browse_button.clicked.connect(self._browse_cache_root)
        self._populate_servers()
        self._populate_from_mapping()

    def _populate_servers(self) -> None:
        self._server_combo.clear()
        for server in self._server_service.list_all():
            if server.id is not None:
                self._server_combo.addItem(server.name, server.id)

    def _populate_from_mapping(self) -> None:
        self._name_edit.setText(self._mapping.name)
        self._remote_root_edit.setText(self._mapping.remote_root)
        self._drive_letter_edit.setText(self._mapping.drive_letter)
        self._cache_root_edit.setText(self._mapping.cache_root or '')
        self._enabled_check.setChecked(self._mapping.enabled)
        self._auto_mount_check.setChecked(self._mapping.auto_mount)
        self._read_only_check.setChecked(self._mapping.read_only)
        self._cache_limit_spin.setValue(self._mapping.file_cache_size_limit_mb)
        self._metadata_ttl_spin.setValue(self._mapping.metadata_ttl_sec)
        self._download_timeout_spin.setValue(self._mapping.download_timeout_sec)
        self._upload_timeout_spin.setValue(self._mapping.upload_timeout_sec)
        self._note_edit.setPlainText(self._mapping.note or '')
        self._select_server(self._mapping.server_id)

    def _select_server(self, server_id: int) -> None:
        for index in range(self._server_combo.count()):
            if self._server_combo.itemData(index) == server_id:
                self._server_combo.setCurrentIndex(index)
                return

    def _browse_cache_root(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, '选择缓存根目录', str(Path.home()))
        if directory:
            self._cache_root_edit.setText(directory)

    def get_payload(self) -> RemoteDriveMapping:
        return RemoteDriveMapping(
            id=self._mapping.id,
            name=self._name_edit.text().strip(),
            server_id=int(self._server_combo.currentData() or 0),
            remote_root=self._remote_root_edit.text().strip(),
            drive_letter=self._drive_letter_edit.text().strip().upper().rstrip(':'),
            enabled=self._enabled_check.isChecked(),
            auto_mount=self._auto_mount_check.isChecked(),
            read_only=self._read_only_check.isChecked(),
            cache_root=self._cache_root_edit.text().strip() or None,
            file_cache_size_limit_mb=int(self._cache_limit_spin.value()),
            metadata_ttl_sec=int(self._metadata_ttl_spin.value()),
            download_timeout_sec=int(self._download_timeout_spin.value()),
            upload_timeout_sec=int(self._upload_timeout_spin.value()),
            note=self._note_edit.toPlainText().strip() or None,
            created_at=self._mapping.created_at,
            updated_at=self._mapping.updated_at,
        )

    def _validate(self) -> list[str]:
        errors: list[str] = []
        if not self._name_edit.text().strip():
            errors.append('远程盘名称不能为空。')
        if self._server_combo.currentData() is None:
            errors.append('请选择一个服务器。')
        if not self._remote_root_edit.text().strip():
            errors.append('远程根目录不能为空。')
        if self._remote_root_edit.text().strip() and not self._remote_root_edit.text().strip().startswith('/'):
            errors.append('远程根目录必须是以 / 开头的绝对路径。')
        if not self._drive_letter_edit.text().strip():
            errors.append('盘符不能为空。')
        else:
            drive_letter = self._drive_letter_edit.text().strip().upper().rstrip(':')
            if len(drive_letter) != 1 or not drive_letter.isalpha():
                errors.append('盘符必须是单个英文字母，例如 R。')
        return errors

    def _on_save_clicked(self) -> None:
        errors = self._validate()
        if errors:
            QMessageBox.warning(self, '验证错误', '\n'.join(errors))
            return
        self.accept()
