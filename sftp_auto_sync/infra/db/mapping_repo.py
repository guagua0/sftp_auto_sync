from __future__ import annotations

import json
from datetime import datetime, timezone

from sftp_auto_sync.domain.enums import DeletePolicy
from sftp_auto_sync.domain.models import SyncMapping
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MappingRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._cf = connection_factory

    def _row_to_model(self, row) -> SyncMapping:
        return SyncMapping(
            id=row['id'],
            name=row['name'],
            server_id=row['server_id'],
            local_dir=row['local_dir'],
            remote_dir=row['remote_dir'],
            recursive=bool(row['recursive']),
            enabled=bool(row['enabled']),
            delete_policy=DeletePolicy(row['delete_policy']),
            startup_rescan=bool(row['startup_rescan']),
            ignore_patterns=json.loads(row['ignore_patterns_json'] or '[]'),
            note=row['note'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )

    def list_all(self) -> list[SyncMapping]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM sync_mappings ORDER BY name').fetchall()
            return [self._row_to_model(row) for row in rows]

    def list_enabled(self) -> list[SyncMapping]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM sync_mappings WHERE enabled = 1 ORDER BY name').fetchall()
            return [self._row_to_model(row) for row in rows]

    def list_by_server(self, server_id: int) -> list[SyncMapping]:
        with self._cf.connect() as conn:
            rows = conn.execute(
                'SELECT * FROM sync_mappings WHERE server_id = ? ORDER BY name',
                (server_id,),
            ).fetchall()
            return [self._row_to_model(row) for row in rows]

    def get(self, mapping_id: int) -> SyncMapping | None:
        with self._cf.connect() as conn:
            row = conn.execute('SELECT * FROM sync_mappings WHERE id = ?', (mapping_id,)).fetchone()
            return self._row_to_model(row) if row else None

    def create(self, item: SyncMapping) -> int:
        now = utc_now_iso()
        with self._cf.connect() as conn:
            cursor = conn.execute(
                '''
                INSERT INTO sync_mappings (
                    name, server_id, local_dir, remote_dir, recursive, enabled,
                    delete_policy, startup_rescan, ignore_patterns_json, note,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    item.name,
                    item.server_id,
                    item.local_dir,
                    item.remote_dir,
                    int(item.recursive),
                    int(item.enabled),
                    item.delete_policy.value if isinstance(item.delete_policy, DeletePolicy) else item.delete_policy,
                    int(item.startup_rescan),
                    json.dumps(item.ignore_patterns, ensure_ascii=False),
                    item.note,
                    item.created_at or now,
                    item.updated_at or now,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def update(self, item: SyncMapping) -> None:
        if item.id is None:
            raise ValueError('SyncMapping.id is required for update().')
        with self._cf.connect() as conn:
            conn.execute(
                '''
                UPDATE sync_mappings
                SET name = ?, server_id = ?, local_dir = ?, remote_dir = ?,
                    recursive = ?, enabled = ?, delete_policy = ?,
                    startup_rescan = ?, ignore_patterns_json = ?, note = ?,
                    updated_at = ?
                WHERE id = ?
                ''',
                (
                    item.name,
                    item.server_id,
                    item.local_dir,
                    item.remote_dir,
                    int(item.recursive),
                    int(item.enabled),
                    item.delete_policy.value if isinstance(item.delete_policy, DeletePolicy) else item.delete_policy,
                    int(item.startup_rescan),
                    json.dumps(item.ignore_patterns, ensure_ascii=False),
                    item.note,
                    utc_now_iso(),
                    item.id,
                ),
            )
            conn.commit()

    def delete(self, mapping_id: int) -> None:
        with self._cf.connect() as conn:
            conn.execute('DELETE FROM sync_mappings WHERE id = ?', (mapping_id,))
            conn.commit()
