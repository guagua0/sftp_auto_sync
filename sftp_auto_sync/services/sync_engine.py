from __future__ import annotations

import logging
import threading
from queue import PriorityQueue

from sftp_auto_sync.app.constants import DEFAULT_DEBOUNCE_MS, DEFAULT_MAX_RETRIES, DEFAULT_RETRY_DELAYS, DEFAULT_STABILITY_CHECK_INTERVAL_MS, DEFAULT_STABILITY_MAX_CHECKS, SETTING_DEBOUNCE_MS
from sftp_auto_sync.domain.enums import MappingRunState
from sftp_auto_sync.domain.models import ServerProfile, SyncMapping
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.infra.db.mapping_repo import MappingRepository
from sftp_auto_sync.infra.db.server_repo import ServerRepository
from sftp_auto_sync.infra.db.settings_repo import SettingsRepository
from sftp_auto_sync.infra.db.state_repo import StateRepository
from sftp_auto_sync.infra.secrets.secret_store import SecretStore
from sftp_auto_sync.infra.sftp.connection_manager import ConnectionManager
from sftp_auto_sync.infra.sftp.host_keys import KnownHostsManager
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper
from sftp_auto_sync.infra.sftp.remote_ops import RemoteOps
from sftp_auto_sync.infra.sftp.uploader import Uploader
from sftp_auto_sync.infra.watcher.event_handler import MappingEventHandler
from sftp_auto_sync.infra.watcher.observer_manager import ObserverManager
from sftp_auto_sync.services.dispatcher import Dispatcher
from sftp_auto_sync.services.event_aggregator import EventAggregator
from sftp_auto_sync.services.startup_rescan_service import StartupRescanService
from sftp_auto_sync.workers.server_worker import ServerWorker


class SyncEngine:
    def __init__(self, server_repo: ServerRepository, mapping_repo: MappingRepository, state_repo: StateRepository, history_repo: HistoryRepository, settings_repo: SettingsRepository, secret_store: SecretStore, known_hosts_manager: KnownHostsManager, path_mapper: PathMapper, startup_rescan_service: StartupRescanService, *, signals=None, logger: logging.Logger | None = None):
        self._server_repo = server_repo
        self._mapping_repo = mapping_repo
        self._state_repo = state_repo
        self._history_repo = history_repo
        self._settings_repo = settings_repo
        self._secret_store = secret_store
        self._known_hosts_manager = known_hosts_manager
        self._path_mapper = path_mapper
        self._startup_rescan_service = startup_rescan_service
        self._signals = signals
        self._logger = logger or logging.getLogger(__name__)
        self._observer_manager = ObserverManager(logger=self._logger)
        self._aggregator: EventAggregator | None = None
        self._dispatcher: Dispatcher | None = None
        self._workers: dict[int, ServerWorker] = {}
        self._queues: dict[int, PriorityQueue] = {}
        self._rescan_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._runtime_servers: dict[int, ServerProfile] = {}
        self._runtime_mappings: dict[int, SyncMapping] = {}
        self._state = MappingRunState.STOPPED.value
        self._last_error = ''
        if self._signals is not None:
            self._signals.error_occurred.connect(self._remember_error)

    @property
    def state(self) -> str:
        return self._state

    @property
    def last_error(self) -> str:
        return self._last_error

    def _remember_error(self, message: str) -> None:
        self._last_error = message

    def total_queue_length(self) -> int:
        return sum(q.qsize() for q in self._queues.values())

    def active_workers(self) -> int:
        return sum(1 for worker in self._workers.values() if worker.is_alive())

    def _load_runtime_config(self) -> None:
        self._runtime_servers = {server.id: server for server in self._server_repo.list_enabled() if server.id is not None}
        self._runtime_mappings = {mapping.id: mapping for mapping in self._mapping_repo.list_enabled() if mapping.id is not None and mapping.server_id in self._runtime_servers}

    def _build_worker(self, server: ServerProfile, queue: PriorityQueue) -> ServerWorker:
        remote_ops = RemoteOps()
        uploader = Uploader(remote_ops, stability_check_interval_ms=DEFAULT_STABILITY_CHECK_INTERVAL_MS, stability_max_checks=DEFAULT_STABILITY_MAX_CHECKS)
        connection_manager = ConnectionManager(self._known_hosts_manager, self._secret_store, logger=self._logger)
        return ServerWorker(server=server, queue=queue, connection_manager=connection_manager, uploader=uploader, state_repo=self._state_repo, history_repo=self._history_repo, signals=self._signals, max_retries=DEFAULT_MAX_RETRIES, retry_delays=DEFAULT_RETRY_DELAYS, logger=self._logger)

    def start_all(self) -> None:
        self.stop_all()
        self._stop_event = threading.Event()
        self._load_runtime_config()
        debounce_ms = self._settings_repo.get_int(SETTING_DEBOUNCE_MS, DEFAULT_DEBOUNCE_MS)
        self._queues = {server_id: PriorityQueue() for server_id in {m.server_id for m in self._runtime_mappings.values()}}
        self._dispatcher = Dispatcher(self._queues, signals=self._signals)
        for server_id, queue in self._queues.items():
            worker = self._build_worker(self._runtime_servers[server_id], queue)
            self._workers[server_id] = worker
            worker.start()
        self._aggregator = EventAggregator(self._runtime_mappings, self._path_mapper, self._dispatcher, debounce_ms=debounce_ms, logger=self._logger)
        self._aggregator.start()
        if self._runtime_mappings:
            self._observer_manager.start(list(self._runtime_mappings.values()), lambda mapping: MappingEventHandler(mapping, self._path_mapper, self._aggregator, logger=self._logger))
        self._rescan_thread = threading.Thread(target=self._run_startup_rescan, name='startup-rescan', daemon=True)
        self._rescan_thread.start()
        self._state = MappingRunState.RUNNING.value
        if self._signals is not None:
            self._signals.engine_state_changed.emit(self._state)
            self._signals.dashboard_refresh_requested.emit()

    def _run_startup_rescan(self) -> None:
        if self._dispatcher is None:
            return
        tasks = self._startup_rescan_service.build_tasks(list(self._runtime_mappings.values()), stop_event=self._stop_event)
        for task in tasks:
            if self._stop_event.is_set():
                return
            self._dispatcher.dispatch(task)
        if self._signals is not None:
            self._signals.dashboard_refresh_requested.emit()

    def stop_all(self) -> None:
        self._stop_event.set()
        self._observer_manager.stop()
        if self._aggregator is not None:
            self._aggregator.stop()
            self._aggregator.join(timeout=5)
            self._aggregator = None
        if self._rescan_thread is not None and self._rescan_thread.is_alive():
            self._rescan_thread.join(timeout=5)
        for worker in self._workers.values():
            worker.stop()
        for worker in self._workers.values():
            worker.join(timeout=5)
        self._workers.clear()
        self._queues.clear()
        self._dispatcher = None
        self._runtime_servers.clear()
        self._runtime_mappings.clear()
        self._state = MappingRunState.STOPPED.value
        if self._signals is not None:
            self._signals.engine_state_changed.emit(self._state)
            self._signals.queue_stats_changed.emit({'total_queue_length': 0, 'queues': {}})

    def reload_config(self) -> None:
        self.start_all()

    def start_mapping(self, mapping_id: int) -> None:
        self.reload_config()

    def stop_mapping(self, mapping_id: int) -> None:
        self.reload_config()
