from __future__ import annotations

from datetime import datetime, timezone

from sftp_auto_sync.domain.enums import AuthType, HostKeyPolicy
from sftp_auto_sync.domain.models import ServerProfile
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ServerRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._cf = connection_factory

    def _row_to_model(self, row) -> ServerProfile:
        return ServerProfile(
            id=row['id'],
            name=row['name'],
            host=row['host'],
            port=row['port'],
            username=row['username'],
            auth_type=AuthType(row['auth_type']),
            password_ref=row['password_ref'],
            private_key_path=row['private_key_path'],
            private_key_passphrase_ref=row['private_key_passphrase_ref'],
            connect_timeout_sec=row['connect_timeout_sec'],
            host_key_policy=HostKeyPolicy(row['host_key_policy']),
            enabled=bool(row['enabled']),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    def list_all(self) -> list[ServerProfile]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM server_profiles ORDER BY name').fetchall()
            return [self._row_to_model(row) for row in rows]

    def list_enabled(self) -> list[ServerProfile]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM server_profiles WHERE enabled = 1 ORDER BY name').fetchall()
            return [self._row_to_model(row) for row in rows]

    def get(self, server_id: int) -> ServerProfile | None:
        with self._cf.connect() as conn:
            row = conn.execute('SELECT * FROM server_profiles WHERE id = ?', (server_id,)).fetchone()
            return self._row_to_model(row) if row else None

    def create(self, item: ServerProfile) -> int:
        now = utc_now_iso()
        with self._cf.connect() as conn:
            cursor = conn.execute(
                '''
                INSERT INTO server_profiles (
                    name, host, port, username, auth_type, password_ref,
                    private_key_path, private_key_passphrase_ref,
                    connect_timeout_sec, host_key_policy, enabled,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    item.name,
                    item.host,
                    item.port,
                    item.username,
                    item.auth_type.value if isinstance(item.auth_type, AuthType) else item.auth_type,
                    item.password_ref,
                    item.private_key_path,
                    item.private_key_passphrase_ref,
                    item.connect_timeout_sec,
                    item.host_key_policy.value if isinstance(item.host_key_policy, HostKeyPolicy) else item.host_key_policy,
                    int(item.enabled),
                    item.created_at or now,
                    item.updated_at or now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update(self, item: ServerProfile) -> None:
        if item.id is None:
            raise ValueError('ServerProfile.id is required for update().')
        with self._cf.connect() as conn:
            conn.execute(
                '''
                UPDATE server_profiles
                SET name = ?, host = ?, port = ?, username = ?, auth_type = ?,
                    password_ref = ?, private_key_path = ?,
                    private_key_passphrase_ref = ?, connect_timeout_sec = ?,
                    host_key_policy = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                ''',
                (
                    item.name,
                    item.host,
                    item.port,
                    item.username,
                    item.auth_type.value if isinstance(item.auth_type, AuthType) else item.auth_type,
                    item.password_ref,
                    item.private_key_path,
                    item.private_key_passphrase_ref,
                    item.connect_timeout_sec,
                    item.host_key_policy.value if isinstance(item.host_key_policy, HostKeyPolicy) else item.host_key_policy,
                    int(item.enabled),
                    utc_now_iso(),
                    item.id,
                ),
            )
            conn.commit()

    def delete(self, server_id: int) -> None:
        with self._cf.connect() as conn:
            conn.execute('DELETE FROM server_profiles WHERE id = ?', (server_id,))
            conn.commit()
