from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from sftp_auto_sync.app.constants import SERVICE_NAME
from sftp_auto_sync.domain.errors import AppError


class SecretStore:
    def __init__(self, service_name: str = SERVICE_NAME):
        self._service_name = service_name

    @staticmethod
    def password_ref_for(server_id: int) -> str:
        return f'server:{server_id}:password'

    @staticmethod
    def key_passphrase_ref_for(server_id: int) -> str:
        return f'server:{server_id}:key_passphrase'

    def set_server_password(self, server_id: int, value: str) -> None:
        try:
            keyring.set_password(self._service_name, self.password_ref_for(server_id), value)
        except KeyringError as exc:
            raise AppError(f'Unable to store password in keyring: {exc}') from exc

    def get_server_password(self, server_id: int) -> str | None:
        try:
            return keyring.get_password(self._service_name, self.password_ref_for(server_id))
        except KeyringError:
            return None

    def delete_server_password(self, server_id: int) -> None:
        try:
            keyring.delete_password(self._service_name, self.password_ref_for(server_id))
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise AppError(f'Unable to delete password from keyring: {exc}') from exc

    def set_key_passphrase(self, server_id: int, value: str) -> None:
        try:
            keyring.set_password(self._service_name, self.key_passphrase_ref_for(server_id), value)
        except KeyringError as exc:
            raise AppError(f'Unable to store key passphrase in keyring: {exc}') from exc

    def get_key_passphrase(self, server_id: int) -> str | None:
        try:
            return keyring.get_password(self._service_name, self.key_passphrase_ref_for(server_id))
        except KeyringError:
            return None

    def delete_key_passphrase(self, server_id: int) -> None:
        try:
            keyring.delete_password(self._service_name, self.key_passphrase_ref_for(server_id))
        except PasswordDeleteError:
            return
        except KeyringError as exc:
            raise AppError(f'Unable to delete key passphrase from keyring: {exc}') from exc
