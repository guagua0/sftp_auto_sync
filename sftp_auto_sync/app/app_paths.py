from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sftp_auto_sync.app.constants import APP_SLUG


@dataclass(frozen=True)
class AppPaths:
    root: Path
    db_path: Path
    known_hosts_path: Path
    logs_dir: Path
    cache_dir: Path


def default_app_root() -> Path:
    appdata = os.environ.get('APPDATA')
    if appdata:
        return Path(appdata) / APP_SLUG
    xdg_data = os.environ.get('XDG_DATA_HOME')
    if xdg_data:
        return Path(xdg_data) / APP_SLUG
    return Path.home() / '.local' / 'share' / APP_SLUG


def fallback_app_root() -> Path:
    return Path(tempfile.gettempdir()) / APP_SLUG


def ensure_writable_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / '.write_test'
    probe.write_text('ok', encoding='utf-8')
    probe.unlink(missing_ok=True)


def build_app_paths(root: str | Path | None = None) -> AppPaths:
    preferred_base = Path(root) if root is not None else default_app_root()
    fallback_base = fallback_app_root()
    last_error: Exception | None = None

    for base in [preferred_base, fallback_base]:
        try:
            ensure_writable_dir(base)
            logs_dir = base / 'logs'
            cache_dir = base / 'cache'
            ensure_writable_dir(logs_dir)
            ensure_writable_dir(cache_dir)
            known_hosts_path = base / 'known_hosts'
            if not known_hosts_path.exists():
                known_hosts_path.touch()
            else:
                known_hosts_path.touch(exist_ok=True)
            return AppPaths(
                root=base,
                db_path=base / 'app.db',
                known_hosts_path=known_hosts_path,
                logs_dir=logs_dir,
                cache_dir=cache_dir,
            )
        except OSError as exc:
            last_error = exc
            continue
    raise OSError(f'Unable to initialize writable app data directory: {last_error}')
