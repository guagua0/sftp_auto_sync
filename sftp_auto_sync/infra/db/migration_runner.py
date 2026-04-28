from __future__ import annotations

from pathlib import Path

from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory


def run_migrations(connection_factory: ConnectionFactory, schema_path: str | Path | None = None) -> None:
    schema_file = Path(schema_path) if schema_path else Path(__file__).with_name('schema.sql')
    sql = schema_file.read_text(encoding='utf-8')
    with connection_factory.connect() as conn:
        conn.executescript(sql)
        conn.commit()
    _migrate_sync_mappings(connection_factory)
    _migrate_remote_drive_mappings(connection_factory)


def _migrate_sync_mappings(connection_factory: ConnectionFactory) -> None:
    with connection_factory.connect() as conn:
        cursor = conn.execute("PRAGMA table_info(sync_mappings)")
        existing_columns = {row['name'] for row in cursor.fetchall()}

        if 'ignore_patterns_json' not in existing_columns:
            conn.execute(
                "ALTER TABLE sync_mappings ADD COLUMN ignore_patterns_json TEXT NOT NULL DEFAULT '[]'"
            )
            conn.commit()

        if 'startup_rescan' not in existing_columns:
            conn.execute(
                "ALTER TABLE sync_mappings ADD COLUMN startup_rescan INTEGER NOT NULL DEFAULT 1 CHECK (startup_rescan IN (0, 1))"
            )
            conn.commit()


def _migrate_remote_drive_mappings(connection_factory: ConnectionFactory) -> None:
    with connection_factory.connect() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'remote_drive_mappings'"
        )
        if cursor.fetchone() is None:
            return

        cursor = conn.execute("PRAGMA table_info(remote_drive_mappings)")
        existing_columns = {row['name'] for row in cursor.fetchall()}

        column_defs = [
            ("enabled", "INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))"),
            ("auto_mount", "INTEGER NOT NULL DEFAULT 0 CHECK (auto_mount IN (0, 1))"),
            ("read_only", "INTEGER NOT NULL DEFAULT 0 CHECK (read_only IN (0, 1))"),
            ("cache_root", "TEXT"),
            ("file_cache_size_limit_mb", "INTEGER NOT NULL DEFAULT 1024"),
            ("metadata_ttl_sec", "INTEGER NOT NULL DEFAULT 10"),
            ("download_timeout_sec", "INTEGER NOT NULL DEFAULT 60"),
            ("upload_timeout_sec", "INTEGER NOT NULL DEFAULT 60"),
            ("note", "TEXT"),
            ("created_at", "TEXT NOT NULL"),
            ("updated_at", "TEXT NOT NULL"),
        ]
        for column_name, column_def in column_defs:
            if column_name not in existing_columns:
                try:
                    conn.execute(f"ALTER TABLE remote_drive_mappings ADD COLUMN {column_name} {column_def}")
                    conn.commit()
                except Exception:
                    pass
