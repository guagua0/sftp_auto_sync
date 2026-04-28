PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS server_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 22,
    username TEXT NOT NULL,
    auth_type TEXT NOT NULL CHECK (auth_type IN ('password', 'private_key')),
    password_ref TEXT,
    private_key_path TEXT,
    private_key_passphrase_ref TEXT,
    connect_timeout_sec INTEGER NOT NULL DEFAULT 10,
    host_key_policy TEXT NOT NULL DEFAULT 'tofu'
        CHECK (host_key_policy IN ('strict', 'tofu')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    server_id INTEGER NOT NULL,
    local_dir TEXT NOT NULL,
    remote_dir TEXT NOT NULL,
    recursive INTEGER NOT NULL DEFAULT 1 CHECK (recursive IN (0, 1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    delete_policy TEXT NOT NULL DEFAULT 'ignore'
        CHECK (delete_policy IN ('ignore', 'delete_file')),
    startup_rescan INTEGER NOT NULL DEFAULT 1 CHECK (startup_rescan IN (0, 1)),
    ignore_patterns_json TEXT NOT NULL DEFAULT '[]',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(server_id) REFERENCES server_profiles(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS sync_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_id INTEGER NOT NULL,
    relative_path TEXT NOT NULL,
    last_local_size INTEGER,
    last_local_mtime_ns INTEGER,
    last_uploaded_at TEXT,
    last_status TEXT,
    last_error TEXT,
    remote_path TEXT NOT NULL,
    UNIQUE(mapping_id, relative_path),
    FOREIGN KEY(mapping_id) REFERENCES sync_mappings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mapping_id INTEGER,
    server_id INTEGER,
    action TEXT NOT NULL,
    relative_path TEXT,
    remote_path TEXT,
    status TEXT NOT NULL,
    message TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(mapping_id) REFERENCES sync_mappings(id) ON DELETE SET NULL,
    FOREIGN KEY(server_id) REFERENCES server_profiles(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remote_drive_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    server_id INTEGER NOT NULL,
    remote_root TEXT NOT NULL,
    drive_letter TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    auto_mount INTEGER NOT NULL DEFAULT 0 CHECK (auto_mount IN (0, 1)),
    read_only INTEGER NOT NULL DEFAULT 0 CHECK (read_only IN (0, 1)),
    cache_root TEXT,
    file_cache_size_limit_mb INTEGER NOT NULL DEFAULT 1024,
    metadata_ttl_sec INTEGER NOT NULL DEFAULT 10,
    download_timeout_sec INTEGER NOT NULL DEFAULT 60,
    upload_timeout_sec INTEGER NOT NULL DEFAULT 60,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(server_id) REFERENCES server_profiles(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_mapping_server_id
    ON sync_mappings(server_id);

CREATE INDEX IF NOT EXISTS idx_state_mapping_path
    ON sync_state(mapping_id, relative_path);

CREATE INDEX IF NOT EXISTS idx_history_created_at
    ON sync_history(created_at);

CREATE INDEX IF NOT EXISTS idx_history_mapping_id
    ON sync_history(mapping_id);

CREATE INDEX IF NOT EXISTS idx_remote_drive_server_id
    ON remote_drive_mappings(server_id);
