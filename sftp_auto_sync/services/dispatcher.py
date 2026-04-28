from __future__ import annotations

import itertools
import time
from queue import PriorityQueue

from sftp_auto_sync.domain.dto import TaskQueueItem
from sftp_auto_sync.domain.models import SyncTask


class Dispatcher:
    def __init__(self, server_queues: dict[int, PriorityQueue], signals=None):
        self._server_queues = server_queues
        self._signals = signals
        self._sequence = itertools.count()

    def dispatch(self, task: SyncTask, *, available_at: float | None = None) -> None:
        queue = self._server_queues.get(task.server_id)
        if queue is None:
            return
        queue.put(
            TaskQueueItem(
                priority=task.priority,
                available_at=available_at if available_at is not None else time.time(),
                sequence=next(self._sequence),
                task=task,
            )
        )
        self._emit_queue_stats()

    def _emit_queue_stats(self) -> None:
        if self._signals is None:
            return
        payload = {
            'total_queue_length': sum(q.qsize() for q in self._server_queues.values()),
            'queues': {server_id: queue.qsize() for server_id, queue in self._server_queues.items()},
        }
        self._signals.queue_stats_changed.emit(payload)
