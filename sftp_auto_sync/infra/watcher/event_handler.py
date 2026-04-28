from __future__ import annotations

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler

from sftp_auto_sync.domain.models import SyncMapping
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper


class MappingEventHandler(FileSystemEventHandler):
    def __init__(self, mapping: SyncMapping, path_mapper: PathMapper, aggregator, logger: logging.Logger | None = None):
        super().__init__()
        self._mapping = mapping
        self._path_mapper = path_mapper
        self._aggregator = aggregator
        self._logger = logger or logging.getLogger(__name__)

    def on_any_event(self, event) -> None:
        if event.is_directory:
            return
        event_type = getattr(event, 'event_type', '')
        if event_type not in {'created', 'modified', 'deleted', 'moved'}:
            return
        src_path = getattr(event, 'src_path', None)
        dest_path = getattr(event, 'dest_path', None)
        if event_type != 'moved' and src_path:
            try:
                if self._path_mapper.is_ignored(self._mapping, Path(src_path)):
                    return
            except Exception:
                pass
        if event_type == 'moved' and src_path and dest_path:
            try:
                src_ignored = self._path_mapper.is_ignored(self._mapping, Path(src_path))
                dest_ignored = self._path_mapper.is_ignored(self._mapping, Path(dest_path))
                if src_ignored and dest_ignored:
                    return
            except Exception:
                pass
        raw = {
            'mapping_id': self._mapping.id,
            'server_id': self._mapping.server_id,
            'event_type': event_type,
            'src_path': src_path,
            'dest_path': dest_path,
            'is_directory': event.is_directory,
            'ts': time.time(),
        }
        self._aggregator.submit_raw_event(raw)
