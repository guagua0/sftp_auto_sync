from __future__ import annotations

from datetime import datetime, timezone

from sftp_auto_sync.domain.models import FileSnapshot, SyncStateRecord
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StateRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._cf = connection_factory

    def _row_to_model(self, row) -> SyncStateRecord:
        return SyncStateRecord(
            mapping_id=row['mapping_id'],
            relative_path=row['relative_path'],
            last_local_size=row['last_local_size'],
            last_local_mtime_ns=row['last_local_mtime_ns'],
            last_uploaded_at=row['last_uploaded_at'],
            last_status=row['last_status'],
            last_error=row['last_error'],
            remote_path=row['remote_path'],
        )

    def get(self, mapping_id: int, relative_path: str) -> SyncStateRecord | None:
        with self._cf.connect() as conn:
            row = conn.execute(
                'SELECT * FROM sync_state WHERE mapping_id = ? AND relative_path = ?',
                (mapping_id, relative_path),
            ).fetchone()
            return self._row_to_model(row) if row else None

    def upsert_success(self, mapping_id: int, relative_path: str, snapshot: FileSnapshot, remote_path: str) -> None:
        with self._cf.connect() as conn:
            conn.execute(
                '''
                INSERT INTO sync_state (
                    mapping_id, relative_path, last_local_size, last_local_mtime_ns,
                    last_uploaded_at, last_status, last_error, remote_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id, relative_path)
                DO UPDATE SET
                    last_local_size = excluded.last_local_size,
                    last_local_mtime_ns = excluded.last_local_mtime_ns,
                    last_uploaded_at = excluded.last_uploaded_at,
                    last_status = excluded.last_status,
                    last_error = excluded.last_error,
                    remote_path = excluded.remote_path
                ''',
                (
                    mapping_id,
                    relative_path,
                    snapshot.size,
                    snapshot.mtime_ns,
                    utc_now_iso(),
                    'success',
                    None,
                    remote_path,
                ),
            )
            conn.commit()

    def upsert_baseline(self, mapping_id: int, relative_path: str, snapshot: FileSnapshot, remote_path: str) -> None:
        with self._cf.connect() as conn:
            conn.execute(
                '''
                INSERT INTO sync_state (
                    mapping_id, relative_path, last_local_size, last_local_mtime_ns,
                    last_uploaded_at, last_status, last_error, remote_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id, relative_path)
                DO UPDATE SET
                    last_local_size = excluded.last_local_size,
                    last_local_mtime_ns = excluded.last_local_mtime_ns,
                    last_uploaded_at = excluded.last_uploaded_at,
                    last_status = excluded.last_status,
                    last_error = excluded.last_error,
                    remote_path = excluded.remote_path
                ''',
                (
                    mapping_id,
                    relative_path,
                    snapshot.size,
                    snapshot.mtime_ns,
                    None,
                    'baseline',
                    None,
                    remote_path,
                ),
            )
            conn.commit()

    def upsert_failure(self, mapping_id: int, relative_path: str, remote_path: str, error: str) -> None:
        with self._cf.connect() as conn:
            conn.execute(
                '''
                INSERT INTO sync_state (
                    mapping_id, relative_path, last_uploaded_at, last_status,
                    last_error, remote_path
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mapping_id, relative_path)
                DO UPDATE SET
                    last_uploaded_at = excluded.last_uploaded_at,
                    last_status = excluded.last_status,
                    last_error = excluded.last_error,
                    remote_path = excluded.remote_path
                ''',
                (
                    mapping_id,
                    relative_path,
                    utc_now_iso(),
                    'failed',
                    error,
                    remote_path,
                ),
            )
            conn.commit()

    def delete(self, mapping_id: int, relative_path: str) -> None:
        with self._cf.connect() as conn:
            conn.execute('DELETE FROM sync_state WHERE mapping_id = ? AND relative_path = ?', (mapping_id, relative_path))
            conn.commit()

    def delete_by_mapping(self, mapping_id: int) -> None:
        with self._cf.connect() as conn:
            conn.execute('DELETE FROM sync_state WHERE mapping_id = ?', (mapping_id,))
            conn.commit()

    def list_by_mapping(self, mapping_id: int) -> list[SyncStateRecord]:
        with self._cf.connect() as conn:
            rows = conn.execute('SELECT * FROM sync_state WHERE mapping_id = ? ORDER BY relative_path', (mapping_id,)).fetchall()
            return [self._row_to_model(row) for row in rows]
