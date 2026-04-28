from __future__ import annotations

from datetime import datetime, timezone

from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HistoryRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._cf = connection_factory

    def add(
        self,
        *,
        mapping_id: int | None,
        server_id: int | None,
        action: str,
        relative_path: str | None,
        remote_path: str | None,
        status: str,
        message: str,
        source: str | None,
    ) -> None:
        with self._cf.connect() as conn:
            conn.execute(
                '''
                INSERT INTO sync_history (
                    mapping_id, server_id, action, relative_path,
                    remote_path, status, message, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    mapping_id,
                    server_id,
                    action,
                    relative_path,
                    remote_path,
                    status,
                    message,
                    source,
                    utc_now_iso(),
                ),
            )
            conn.commit()

    def list_recent(
        self,
        limit: int = 500,
        *,
        mapping_id: int | None = None,
        server_id: int | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[object] = []
        if mapping_id is not None:
            clauses.append('h.mapping_id = ?')
            params.append(mapping_id)
        if server_id is not None:
            clauses.append('h.server_id = ?')
            params.append(server_id)
        if status:
            clauses.append('h.status = ?')
            params.append(status)
        if keyword:
            clauses.append('(h.relative_path LIKE ? OR h.remote_path LIKE ? OR h.message LIKE ?)')
            like = f'%{keyword}%'
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        query = f'''
            SELECT
                h.id,
                h.mapping_id,
                h.server_id,
                h.action,
                h.relative_path,
                h.remote_path,
                h.status,
                h.message,
                h.source,
                h.created_at,
                m.name AS mapping_name,
                s.name AS server_name
            FROM sync_history h
            LEFT JOIN sync_mappings m ON m.id = h.mapping_id
            LEFT JOIN server_profiles s ON s.id = h.server_id
            {where}
            ORDER BY h.id DESC
            LIMIT ?
        '''
        params.append(limit)
        with self._cf.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def prune(self, keep_rows: int = 20000) -> None:
        with self._cf.connect() as conn:
            conn.execute(
                '''
                DELETE FROM sync_history
                WHERE id NOT IN (
                    SELECT id FROM sync_history ORDER BY id DESC LIMIT ?
                )
                ''',
                (keep_rows,),
            )
            conn.commit()

    def clear_all(self) -> None:
        with self._cf.connect() as conn:
            conn.execute('DELETE FROM sync_history')
            conn.commit()
