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
    QLabel,
    QWidget,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from sftp_auto_sync.domain.enums import AuthType, HostKeyPolicy
from sftp_auto_sync.domain.models import ServerProfile
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.ui.dialogs.test_connection_dialog import TestConnectionDialog


class ServerDialog(QDialog):
    def __init__(self, server_service: ServerService, profile: ServerProfile | None = None, parent=None):
        super().__init__(parent)
        self._server_service = server_service
        self._profile = profile or ServerProfile()
        self.setWindowTitle('服务器')
        self.resize(520, 360)

        self._name_edit = QLineEdit()
        self._host_edit = QLineEdit()
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._username_edit = QLineEdit()
        self._auth_type_combo = QComboBox()
        self._auth_type_combo.addItem('密码', AuthType.PASSWORD)
        self._auth_type_combo.addItem('私钥', AuthType.PRIVATE_KEY)
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_path_edit = QLineEdit()
        self._key_browse_button = QPushButton('浏览...')
        self._key_passphrase_edit = QLineEdit()
        self._key_passphrase_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(3, 600)
        self._host_key_policy_combo = QComboBox()
        self._host_key_policy_combo.addItem('严格', HostKeyPolicy.STRICT)
        self._host_key_policy_combo.addItem('TOFU', HostKeyPolicy.TOFU)
        self._enabled_check = QCheckBox('启用')

        self._password_label = QLabel('密码')
        self._key_path_label = QLabel('私钥路径')
        self._key_passphrase_label = QLabel('密钥密码')

        self._key_path_row = QHBoxLayout()
        self._key_path_row.setContentsMargins(0, 0, 0, 0)
        self._key_path_row.addWidget(self._key_path_edit)
        self._key_path_row.addWidget(self._key_browse_button)
        self._key_path_container = QWidget()
        key_container_layout = QHBoxLayout(self._key_path_container)
        key_container_layout.setContentsMargins(0, 0, 0, 0)
        key_container_layout.addLayout(self._key_path_row)

        form = QFormLayout()
        form.addRow('名称', self._name_edit)
        form.addRow('主机', self._host_edit)
        form.addRow('端口', self._port_spin)
        form.addRow('用户名', self._username_edit)
        form.addRow('认证方式', self._auth_type_combo)
        form.addRow(self._password_label, self._password_edit)
        form.addRow(self._key_path_label, self._key_path_container)
        form.addRow(self._key_passphrase_label, self._key_passphrase_edit)
        form.addRow('连接超时', self._timeout_spin)
        form.addRow('主机密钥策略', self._host_key_policy_combo)
        form.addRow('', self._enabled_check)

        self._test_button = QPushButton('测试连接')
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.accepted.connect(self._on_save_clicked)
        self._buttons.rejected.connect(self.reject)
        button_row = QHBoxLayout()
        button_row.addWidget(self._test_button)
        button_row.addStretch(1)
        button_row.addWidget(self._buttons)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(button_row)

        self._auth_type_combo.currentIndexChanged.connect(self._update_auth_visibility)
        self._key_browse_button.clicked.connect(self._browse_key)
        self._test_button.clicked.connect(self._on_test_connection)

        self._port_spin.setValue(self._profile.port or 22)
        self._timeout_spin.setValue(self._profile.connect_timeout_sec or 10)
        self._enabled_check.setChecked(self._profile.enabled)
        self._populate_from_profile()
        self._update_auth_visibility()

    def _populate_from_profile(self) -> None:
        self._name_edit.setText(self._profile.name)
        self._host_edit.setText(self._profile.host)
        self._username_edit.setText(self._profile.username)
        self._key_path_edit.setText(self._profile.private_key_path or '')
        self._password_edit.setPlaceholderText('留空保持原有密码')
        self._key_passphrase_edit.setPlaceholderText('留空保持原有密码')
        self._select_combo_data(self._auth_type_combo, self._profile.auth_type)
        self._select_combo_data(self._host_key_policy_combo, self._profile.host_key_policy)

    @staticmethod
    def _select_combo_data(combo: QComboBox, value) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _browse_key(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, '选择私钥', str(Path.home()))
        if filename:
            self._key_path_edit.setText(filename)

    def _update_auth_visibility(self) -> None:
        auth_type = self._auth_type_combo.currentData()
        use_password = auth_type == AuthType.PASSWORD
        self._password_label.setVisible(use_password)
        self._password_edit.setVisible(use_password)
        self._key_path_label.setVisible(not use_password)
        self._key_path_container.setVisible(not use_password)
        self._key_passphrase_label.setVisible(not use_password)
        self._key_passphrase_edit.setVisible(not use_password)

    def get_payload(self) -> dict:
        profile = ServerProfile(
            id=self._profile.id,
            name=self._name_edit.text().strip(),
            host=self._host_edit.text().strip(),
            port=self._port_spin.value(),
            username=self._username_edit.text().strip(),
            auth_type=self._auth_type_combo.currentData(),
            password_ref=self._profile.password_ref,
            private_key_path=self._key_path_edit.text().strip() or None,
            private_key_passphrase_ref=self._profile.private_key_passphrase_ref,
            connect_timeout_sec=self._timeout_spin.value(),
            host_key_policy=self._host_key_policy_combo.currentData(),
            enabled=self._enabled_check.isChecked(),
            created_at=self._profile.created_at,
            updated_at=self._profile.updated_at,
        )
        return {
            'profile': profile,
            'password': self._password_edit.text().strip() or None,
            'key_passphrase': self._key_passphrase_edit.text().strip() or None,
        }

    def _on_test_connection(self) -> None:
        payload = self.get_payload()
        dialog = TestConnectionDialog(
            lambda: self._server_service.test_connection(
                payload['profile'],
                password=payload['password'],
                key_passphrase=payload['key_passphrase'],
            ),
            parent=self,
        )
        dialog.exec()

    def _validate(self) -> list[str]:
        errors: list[str] = []
        if not self._name_edit.text().strip():
            errors.append('服务器名称不能为空。')
        if not self._host_edit.text().strip():
            errors.append('主机地址不能为空。')
        if not self._username_edit.text().strip():
            errors.append('用户名不能为空。')
        auth_type = self._auth_type_combo.currentData()
        if auth_type == AuthType.PASSWORD:
            if not self._password_edit.text().strip() and not self._profile.password_ref:
                errors.append('密码认证方式需要输入密码。')
        elif auth_type == AuthType.PRIVATE_KEY:
            if not self._key_path_edit.text().strip():
                errors.append('私钥认证方式需要指定私钥路径。')
        return errors

    def _on_save_clicked(self) -> None:
        errors = self._validate()
        if errors:
            QMessageBox.warning(self, '验证错误', '\n'.join(errors))
            return
        self.accept()
