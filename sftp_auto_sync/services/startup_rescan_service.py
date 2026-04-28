from __future__ import annotations

import threading
import uuid
from pathlib import Path
from time import time

from sftp_auto_sync.app.constants import DEFAULT_RESCAN_PRIORITY
from sftp_auto_sync.domain.enums import DeletePolicy, TaskAction
from sftp_auto_sync.domain.models import FileSnapshot, SyncMapping, SyncTask
from sftp_auto_sync.infra.db.state_repo import StateRepository
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper


class StartupRescanService:
    def __init__(self, state_repo: StateRepository, path_mapper: PathMapper):
        self._state_repo = state_repo
        self._path_mapper = path_mapper

    def _iter_files(self, mapping: SyncMapping):
        root = Path(mapping.local_dir)
        iterable = root.rglob('*') if mapping.recursive else root.glob('*')
        for path in iterable:
            if path.is_dir() or path.is_symlink():
                continue
            yield path

    def build_tasks(self, mappings: list[SyncMapping], *, stop_event: threading.Event | None = None) -> list[SyncTask]:
        tasks: list[SyncTask] = []
        for mapping in mappings:
            if stop_event and stop_event.is_set():
                break
            if not mapping.enabled or not mapping.startup_rescan or mapping.id is None:
                continue
            existing_local_paths: set[str] = set()
            for path in self._iter_files(mapping):
                if stop_event and stop_event.is_set():
                    break
                if self._path_mapper.is_ignored(mapping, path):
                    continue
                # Some paths (e.g. special Windows devices like \\.\nul) may
                # be encountered during startup rescan. Skip gracefully instead
                # of crashing the startup process.
                try:
                    relative = self._path_mapper.to_relative_path(mapping, path)
                except ValueError:
                    # skip this path as it's outside mapping root or otherwise invalid
                    continue
                existing_local_paths.add(relative)
                stat = path.stat()
                snapshot = FileSnapshot(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                state = self._state_repo.get(mapping.id, relative)
                if state is None or state.last_local_size != snapshot.size or state.last_local_mtime_ns != snapshot.mtime_ns:
                    tasks.append(
                        SyncTask(
                            task_id=str(uuid.uuid4()),
                            mapping_id=mapping.id,
                            server_id=mapping.server_id,
                            action=TaskAction.UPSERT,
                            local_path=str(path),
                            relative_path=relative,
                            remote_path=self._path_mapper.to_remote_path(mapping, relative),
                            source='startup_rescan',
                            priority=DEFAULT_RESCAN_PRIORITY,
                            retry_count=0,
                            enqueue_ts=time(),
                        )
                    )
            if mapping.delete_policy == DeletePolicy.DELETE_FILE:
                for state in self._state_repo.list_by_mapping(mapping.id):
                    if stop_event and stop_event.is_set():
                        break
                    if state.relative_path in existing_local_paths:
                        continue
                    tasks.append(
                        SyncTask(
                            task_id=str(uuid.uuid4()),
                            mapping_id=mapping.id,
                            server_id=mapping.server_id,
                            action=TaskAction.DELETE,
                            local_path=None,
                            relative_path=state.relative_path,
                            remote_path=state.remote_path or self._path_mapper.to_remote_path(mapping, state.relative_path),
                            source='startup_rescan',
                            priority=DEFAULT_RESCAN_PRIORITY,
                            retry_count=0,
                            enqueue_ts=time(),
                        )
                    )
        return tasks
