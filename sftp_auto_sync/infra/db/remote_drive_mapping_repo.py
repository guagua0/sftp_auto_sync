from __future__ import annotations

from datetime import datetime, timezone

from sftp_auto_sync.domain.models import RemoteDriveMapping
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RemoteDriveMappingRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._cf = connection_factory

    def _row_to_model(self, row) -> RemoteDriveMapping:
        def get_field(key: str, default=None):
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        return RemoteDriveMapping(
            id=get_field('id'),
            name=get_field('name'),
            server_id=get_field('server_id'),
            remote_root=get_field('remote_root') or get_field('remote_root_dir') or '/',
            drive_letter=get_field('drive_letter'),
            enabled=bool(get_field('enabled', 1)),
            auto_mount=bool(get_field('auto_mount', 0)),
            read_only=bool(get_field('read_only', 0)),
            cache_root=get_field('cache_root'),
            file_cache_size_limit_mb=get_field('file_cache_size_limit_mb', 1024),
            metadata_ttl_sec=get_field('metadata_ttl_sec', 10),
            download_timeout_sec=get_field('download_timeout_sec', 60),
            upload_timeout_sec=get_field('upload_timeout_sec', 60),
            note=get_field('note'),
            created_at=get_field('created_at'),
            updated_at=get_field('updated_at'),
        )

    def list_all(self) -> list[RemoteDriveMapping]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM remote_drive_mappings ORDER BY name').fetchall()
            return [self._row_to_model(row) for row in rows]

    def list_enabled(self) -> list[RemoteDriveMapping]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM remote_drive_mappings WHERE enabled = 1 ORDER BY name').fetchall()
            return [self._row_to_model(row) for row in rows]

    def list_by_server(self, server_id: int) -> list[RemoteDriveMapping]:
        with self._cf.connect() as conn:
            rows = conn.execute(
                'SELECT * FROM remote_drive_mappings WHERE server_id = ? ORDER BY name',
                (server_id,),
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def get(self, mapping_id: int) -> RemoteDriveMapping | None:
        with self._cf.connect() as conn:
            row = conn.execute('SELECT * FROM remote_drive_mappings WHERE id = ?', (mapping_id,)).fetchone()
            return self._row_to_model(row) if row else None

    def create(self, item: RemoteDriveMapping) -> int:
        now = utc_now_iso()
        with self._cf.connect() as conn:
            cursor = conn.execute(
                '''
                INSERT INTO remote_drive_mappings (
                    name, server_id, remote_root, drive_letter, enabled, auto_mount,
                    read_only, cache_root, file_cache_size_limit_mb, metadata_ttl_sec,
                    download_timeout_sec, upload_timeout_sec, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    item.name,
                    item.server_id,
                    item.remote_root,
                    item.drive_letter,
                    int(item.enabled),
                    int(item.auto_mount),
                    int(item.read_only),
                    item.cache_root,
                    item.file_cache_size_limit_mb,
                    item.metadata_ttl_sec,
                    item.download_timeout_sec,
                    item.upload_timeout_sec,
                    item.note,
                    item.created_at or now,
                    item.updated_at or now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update(self, item: RemoteDriveMapping) -> None:
        if item.id is None:
            raise ValueError('RemoteDriveMapping.id is required for update().')
        with self._cf.connect() as conn:
            conn.execute(
                '''
                UPDATE remote_drive_mappings
                SET name = ?, server_id = ?, remote_root = ?, drive_letter = ?,
                    enabled = ?, auto_mount = ?, read_only = ?, cache_root = ?,
                    file_cache_size_limit_mb = ?, metadata_ttl_sec = ?,
                    download_timeout_sec = ?, upload_timeout_sec = ?, note = ?,
                    updated_at = ?
                WHERE id = ?
                ''',
                (
                    item.name,
                    item.server_id,
                    item.remote_root,
                    item.drive_letter,
                    int(item.enabled),
                    int(item.auto_mount),
                    int(item.read_only),
                    item.cache_root,
                    item.file_cache_size_limit_mb,
                    item.metadata_ttl_sec,
                    item.download_timeout_sec,
                    item.upload_timeout_sec,
                    item.note,
                    utc_now_iso(),
                    item.id,
                ),
            )
            conn.commit()

    def delete(self, mapping_id: int) -> None:
        with self._cf.connect() as conn:
            conn.execute('DELETE FROM remote_drive_mappings WHERE id = ?', (mapping_id,))
            conn.commit()
