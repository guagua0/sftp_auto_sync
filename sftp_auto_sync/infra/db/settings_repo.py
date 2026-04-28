from __future__ import annotations

from sftp_auto_sync.domain.models import AppSetting
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


class SettingsRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._cf = connection_factory

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._cf.connect() as conn:
            row = conn.execute('SELECT value FROM app_settings WHERE key = ?', (key,)).fetchone()
            return row['value'] if row else default

    def set(self, key: str, value: str) -> None:
        with self._cf.connect() as conn:
            conn.execute(
                '''
                INSERT INTO app_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                ''',
                (key, value),
            )
            conn.commit()

    def list_all(self) -> list[AppSetting]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT key, value FROM app_settings ORDER BY key').fetchall()
            return [AppSetting(key=row['key'], value=row['value']) for row in rows]

    def ensure_defaults(self, defaults: dict[str, str]) -> None:
        with self._cf.connect() as conn:
            for key, value in defaults.items():
                conn.execute(
                    '''
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO NOTHING
                    ''',
                    (key, value),
                )
            conn.commit()

    def get_int(self, key: str, default: int) -> int:
        value = self.get(key)
        try:
            return int(value) if value is not None else default
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool) -> bool:
        value = self.get(key)
        if value is None:
            return default
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}
