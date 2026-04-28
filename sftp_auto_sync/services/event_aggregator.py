from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from sftp_auto_sync.app.constants import DEFAULT_AGGREGATOR_TICK_MS, DEFAULT_DEBOUNCE_MS, DEFAULT_LIVE_PRIORITY
from sftp_auto_sync.domain.enums import DeletePolicy, TaskAction
from sftp_auto_sync.domain.models import SyncMapping, SyncTask
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper
from sftp_auto_sync.services.dispatcher import Dispatcher


@dataclass
class PendingEntry:
    mapping_id: int
    server_id: int
    action: TaskAction
    local_path: str | None
    relative_path: str
    remote_path: str
    deadline_ts: float


class EventAggregator(threading.Thread):
    def __init__(self, mappings: dict[int, SyncMapping], path_mapper: PathMapper, dispatcher: Dispatcher, *, debounce_ms: int = DEFAULT_DEBOUNCE_MS, tick_ms: int = DEFAULT_AGGREGATOR_TICK_MS, logger: logging.Logger | None = None):
        super().__init__(daemon=True, name='event-aggregator')
        self._mappings = dict(mappings)
        self._path_mapper = path_mapper
        self._dispatcher = dispatcher
        self._debounce_sec = debounce_ms / 1000.0
        self._tick_sec = tick_ms / 1000.0
        self._logger = logger or logging.getLogger(__name__)
        self._raw_queue: queue.Queue[dict] = queue.Queue()
        self._stop_event = threading.Event()
        self._pending: dict[tuple[int, str], PendingEntry] = {}

    def submit_raw_event(self, event: dict) -> None:
        self._raw_queue.put(event)

    def stop(self) -> None:
        self._stop_event.set()

    def _make_pending(self, mapping: SyncMapping, action: TaskAction, path: str, server_id: int) -> PendingEntry | None:
        abs_path = Path(path)
        if self._path_mapper.is_ignored(mapping, abs_path):
            return None
        try:
            relative_path = self._path_mapper.to_relative_path(mapping, abs_path)
        except ValueError:
            return None
        remote_path = self._path_mapper.to_remote_path(mapping, relative_path)
        local_path = str(abs_path) if action == TaskAction.UPSERT else None
        return PendingEntry(mapping.id or 0, server_id, action, local_path, relative_path, remote_path, time.time() + self._debounce_sec)

    def _merge_entry(self, entry: PendingEntry | None) -> None:
        if entry is None:
            return
        key = (entry.mapping_id, entry.relative_path)
        self._pending[key] = entry

    def _drain_raw_events(self) -> None:
        while True:
            try:
                raw = self._raw_queue.get_nowait()
            except queue.Empty:
                break
            try:
                mapping = self._mappings.get(raw['mapping_id'])
                if mapping is None or not mapping.enabled or mapping.id is None:
                    continue
                event_type = raw['event_type']
                server_id = raw['server_id']
                if event_type in {'created', 'modified'} and raw.get('src_path'):
                    self._merge_entry(self._make_pending(mapping, TaskAction.UPSERT, raw['src_path'], server_id))
                elif event_type == 'deleted' and mapping.delete_policy == DeletePolicy.DELETE_FILE and raw.get('src_path'):
                    self._merge_entry(self._make_pending(mapping, TaskAction.DELETE, raw['src_path'], server_id))
                elif event_type == 'moved':
                    if mapping.delete_policy == DeletePolicy.DELETE_FILE and raw.get('src_path'):
                        self._merge_entry(self._make_pending(mapping, TaskAction.DELETE, raw['src_path'], server_id))
                    if raw.get('dest_path'):
                        self._merge_entry(self._make_pending(mapping, TaskAction.UPSERT, raw['dest_path'], server_id))
            finally:
                self._raw_queue.task_done()

    def _flush_due(self) -> None:
        now = time.time()
        for key, entry in list(self._pending.items()):
            if entry.deadline_ts > now:
                continue
            self._dispatcher.dispatch(
                SyncTask(
                    task_id=str(uuid.uuid4()),
                    mapping_id=entry.mapping_id,
                    server_id=entry.server_id,
                    action=entry.action,
                    local_path=entry.local_path,
                    relative_path=entry.relative_path,
                    remote_path=entry.remote_path,
                    source='live_event',
                    priority=DEFAULT_LIVE_PRIORITY,
                    retry_count=0,
                    enqueue_ts=now,
                )
            )
            del self._pending[key]

    def run(self) -> None:
        while not self._stop_event.is_set():
            self._drain_raw_events()
            self._flush_due()
            time.sleep(self._tick_sec)
