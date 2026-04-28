from __future__ import annotations

import logging
import socket
from pathlib import Path

import paramiko

from sftp_auto_sync.domain.enums import AuthType, HostKeyPolicy
from sftp_auto_sync.domain.errors import AuthError, ConnectionError, HostKeyError, NonRetryableError
from sftp_auto_sync.domain.models import ServerProfile
from sftp_auto_sync.infra.secrets.secret_store import SecretStore
from sftp_auto_sync.infra.sftp.host_keys import KnownHostsManager


class ConnectionManager:
    def __init__(self, known_hosts_manager: KnownHostsManager, secret_store: SecretStore, logger: logging.Logger | None = None):
        self._known_hosts_manager = known_hosts_manager
        self._secret_store = secret_store
        self._logger = logger or logging.getLogger(__name__)
        self._ssh: paramiko.SSHClient | None = None
        self._sftp = None
        self._server_id: int | None = None

    def connect(
        self,
        server: ServerProfile,
        *,
        password_override: str | None = None,
        key_passphrase_override: str | None = None,
    ) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        if self.is_alive() and self._server_id == server.id:
            return self._ssh, self._sftp
        self.close()

        ssh = paramiko.SSHClient()
        ssh.load_system_host_keys()
        self._known_hosts_manager.ensure_exists()
        try:
            ssh.load_host_keys(str(self._known_hosts_manager.path))
        except IOError:
            pass
        ssh.set_missing_host_key_policy(paramiko.RejectPolicy() if server.host_key_policy == HostKeyPolicy.STRICT else paramiko.AutoAddPolicy())

        kwargs: dict[str, object] = {
            'hostname': server.host,
            'port': server.port,
            'username': server.username,
            'timeout': server.connect_timeout_sec,
            'allow_agent': False,
            'look_for_keys': False,
        }
        if server.auth_type == AuthType.PASSWORD:
            password = password_override
            if password is None and server.id is not None:
                password = self._secret_store.get_server_password(server.id)
            if not password:
                raise AuthError('Password is required.')
            kwargs['password'] = password
        else:
            if not server.private_key_path:
                raise AuthError('Private key path is required.')
            key_path = Path(server.private_key_path)
            if not key_path.exists() or not key_path.is_file():
                raise NonRetryableError(f'Private key not found: {key_path}')
            passphrase = key_passphrase_override
            if passphrase is None and server.id is not None:
                passphrase = self._secret_store.get_key_passphrase(server.id)
            loaded = False
            if hasattr(paramiko.PKey, 'from_path'):
                try:
                    kwargs['pkey'] = paramiko.PKey.from_path(key_path, passphrase=passphrase)
                    loaded = True
                except Exception as exc:
                    self._logger.debug('PKey.from_path failed, fallback to key_filename: %s', exc)
            if not loaded:
                kwargs['key_filename'] = str(key_path)
                if passphrase:
                    kwargs['password'] = passphrase

        try:
            ssh.connect(**kwargs)
            if server.host_key_policy == HostKeyPolicy.TOFU:
                ssh.save_host_keys(str(self._known_hosts_manager.path))
            sftp = ssh.open_sftp()
        except paramiko.BadHostKeyException as exc:
            ssh.close()
            raise HostKeyError(str(exc)) from exc
        except paramiko.AuthenticationException as exc:
            ssh.close()
            raise AuthError('Authentication failed.') from exc
        except (paramiko.SSHException, OSError, EOFError, socket.error) as exc:
            ssh.close()
            raise ConnectionError(str(exc)) from exc
        self._ssh = ssh
        self._sftp = sftp
        self._server_id = server.id
        return ssh, sftp

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:
                pass
        if self._ssh is not None:
            try:
                self._ssh.close()
            except Exception:
                pass
        self._sftp = None
        self._ssh = None
        self._server_id = None

    def is_alive(self) -> bool:
        if self._ssh is None or self._sftp is None:
            return False
        try:
            transport = self._ssh.get_transport()
            return bool(transport and transport.is_active())
        except Exception:
            return False
