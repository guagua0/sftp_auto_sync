from __future__ import annotations

import itertools
import logging
import threading
import time
from pathlib import Path
from queue import Empty, PriorityQueue

from sftp_auto_sync.app.constants import DEFAULT_MAX_RETRIES, DEFAULT_RETRY_DELAYS, DEFAULT_RETRY_PRIORITY
from sftp_auto_sync.domain.dto import TaskQueueItem
from sftp_auto_sync.domain.enums import SyncStatus, TaskAction
from sftp_auto_sync.domain.errors import AuthError, ConnectionError, HostKeyError, NonRetryableError, RetryableError, SkippedTaskError
from sftp_auto_sync.domain.models import ServerProfile, SyncTask
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.infra.db.state_repo import StateRepository
from sftp_auto_sync.infra.sftp.connection_manager import ConnectionManager
from sftp_auto_sync.infra.sftp.uploader import Uploader


class ServerWorker(threading.Thread):
    def __init__(self, server: ServerProfile, queue: PriorityQueue, connection_manager: ConnectionManager, uploader: Uploader, state_repo: StateRepository, history_repo: HistoryRepository, *, signals=None, max_retries: int = DEFAULT_MAX_RETRIES, retry_delays: list[int] | None = None, logger: logging.Logger | None = None):
        super().__init__(daemon=True, name=f'server-worker-{server.id}')
        self._server = server
        self._queue = queue
        self._connection_manager = connection_manager
        self._uploader = uploader
        self._state_repo = state_repo
        self._history_repo = history_repo
        self._signals = signals
        self._max_retries = max_retries
        self._retry_delays = list(retry_delays or DEFAULT_RETRY_DELAYS)
        self._logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._sequence = itertools.count()

    def stop(self) -> None:
        self._stop_event.set()
        self._connection_manager.close()

    def _emit_status(self, task: SyncTask | None, status: str, message: str = '') -> None:
        if self._signals is None:
            return
        self._signals.worker_status.emit({
            'server_id': self._server.id,
            'server_name': self._server.name,
            'task_id': task.task_id if task else None,
            'mapping_id': task.mapping_id if task else None,
            'relative_path': task.relative_path if task else None,
            'status': status,
            'message': message,
            'ts': time.time(),
        })

    def _emit_queue_stats(self) -> None:
        if self._signals is None:
            return
        self._signals.queue_stats_changed.emit({'total_queue_length': self._queue.qsize(), 'queues': {self._server.id: self._queue.qsize()}})

    def _requeue(self, task: SyncTask, delay: int, message: str) -> None:
        retry_task = SyncTask(
            task_id=task.task_id,
            mapping_id=task.mapping_id,
            server_id=task.server_id,
            action=task.action,
            local_path=task.local_path,
            relative_path=task.relative_path,
            remote_path=task.remote_path,
            source='retry',
            priority=DEFAULT_RETRY_PRIORITY,
            retry_count=task.retry_count + 1,
            enqueue_ts=time.time(),
        )
        self._queue.put(TaskQueueItem(DEFAULT_RETRY_PRIORITY, time.time() + delay, next(self._sequence), retry_task))
        self._emit_status(task, SyncStatus.PENDING.value, f'Retry scheduled in {delay}s: {message}')

    def _record_failure(self, task: SyncTask, message: str) -> None:
        if task.action == TaskAction.UPSERT:
            self._state_repo.upsert_failure(task.mapping_id, task.relative_path, task.remote_path, message)
        self._history_repo.add(mapping_id=task.mapping_id, server_id=task.server_id, action=task.action.value, relative_path=task.relative_path, remote_path=task.remote_path, status=SyncStatus.FAILED.value, message=message, source=task.source)
        self._emit_status(task, SyncStatus.FAILED.value, message)
        if self._signals is not None:
            self._signals.history_changed.emit()
            self._signals.error_occurred.emit(message)

    def _record_success(self, task: SyncTask, message: str) -> None:
        self._history_repo.add(mapping_id=task.mapping_id, server_id=task.server_id, action=task.action.value, relative_path=task.relative_path, remote_path=task.remote_path, status=SyncStatus.SUCCESS.value, message=message, source=task.source)
        self._emit_status(task, SyncStatus.SUCCESS.value, message)
        if self._signals is not None:
            self._signals.history_changed.emit()

    def _record_skipped(self, task: SyncTask, message: str) -> None:
        self._history_repo.add(mapping_id=task.mapping_id, server_id=task.server_id, action=task.action.value, relative_path=task.relative_path, remote_path=task.remote_path, status=SyncStatus.SKIPPED.value, message=message, source=task.source)
        self._emit_status(task, SyncStatus.SKIPPED.value, message)
        if self._signals is not None:
            self._signals.history_changed.emit()

    def run(self) -> None:
        self._emit_status(None, 'idle', 'Worker started.')
        while not self._stop_event.is_set():
            try:
                item: TaskQueueItem = self._queue.get(timeout=0.5)
            except Empty:
                continue
            task = item.task
            try:
                now = time.time()
                if item.available_at > now:
                    self._queue.put(item)
                    time.sleep(min(0.5, item.available_at - now))
                    continue
                self._emit_status(task, SyncStatus.RUNNING.value)
                _, sftp = self._connection_manager.connect(self._server)
                if task.action == TaskAction.UPSERT:
                    if not task.local_path:
                        raise NonRetryableError('UPSERT task has no local path.')
                    local_path = Path(task.local_path)
                    self._uploader.wait_until_stable(local_path)
                    snapshot = self._uploader.upload_file(sftp, local_path, task.remote_path)
                    self._state_repo.upsert_success(task.mapping_id, task.relative_path, snapshot, task.remote_path)
                    self._record_success(task, 'Uploaded')
                elif task.action == TaskAction.DELETE:
                    self._uploader.delete_file(sftp, task.remote_path)
                    self._state_repo.delete(task.mapping_id, task.relative_path)
                    self._record_success(task, 'Deleted')
            except SkippedTaskError as exc:
                self._record_skipped(task, str(exc))
            except (AuthError, HostKeyError, NonRetryableError) as exc:
                self._connection_manager.close()
                self._record_failure(task, str(exc))
            except (RetryableError, ConnectionError, OSError, EOFError) as exc:
                self._connection_manager.close()
                if task.retry_count < self._max_retries:
                    delay = self._retry_delays[min(task.retry_count, len(self._retry_delays) - 1)]
                    self._requeue(task, delay, str(exc))
                else:
                    self._record_failure(task, str(exc))
            except Exception as exc:
                self._connection_manager.close()
                if task.retry_count < self._max_retries:
                    delay = self._retry_delays[min(task.retry_count, len(self._retry_delays) - 1)]
                    self._requeue(task, delay, str(exc))
                else:
                    self._record_failure(task, str(exc))
            finally:
                self._queue.task_done()
                self._emit_queue_stats()
        self._connection_manager.close()
        self._emit_status(None, 'stopped', 'Worker stopped.')
