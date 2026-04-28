from __future__ import annotations

import heapq
import logging
import threading
import time

from sftp_auto_sync.remote_drive.models import UploadTask


class UploadScheduler:
    def __init__(self, upload_callback, *, debounce_sec: float = 1.0, logger: logging.Logger | None = None):
        self._upload_callback = upload_callback
        self._debounce_sec = debounce_sec
        self._logger = logger or logging.getLogger(__name__)
        self._guard = threading.RLock()
        self._cv = threading.Condition(self._guard)
        self._queue: list[tuple[float, int, UploadTask]] = []
        self._scheduled: dict[str, UploadTask] = {}
        self._sequence = 0
        self._stop = False
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._guard:
            if self._worker is not None and self._worker.is_alive():
                return
            self._stop = False
            self._worker = threading.Thread(target=self._run, name='remote-drive-upload', daemon=True)
            self._worker.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=5)

    def schedule(self, remote_path: str, *, reason: str = 'dirty', delay_sec: float | None = None, retry_count: int = 0) -> None:
        with self._cv:
            run_at = time.time() + (self._debounce_sec if delay_sec is None else delay_sec)
            task = UploadTask(remote_path=remote_path, run_at=run_at, reason=reason, retry_count=retry_count)
            self._scheduled[remote_path] = task
            self._sequence += 1
            heapq.heappush(self._queue, (run_at, self._sequence, task))
            self._cv.notify_all()

    def pending_count(self) -> int:
        with self._guard:
            return len(self._scheduled)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._stop and not self._queue:
                    self._cv.wait()
                if self._stop:
                    return
                run_at, _, task = self._queue[0]
                now = time.time()
                if run_at > now:
                    self._cv.wait(timeout=run_at - now)
                    continue
                heapq.heappop(self._queue)
                current = self._scheduled.get(task.remote_path)
                if current is not task:
                    continue
                self._scheduled.pop(task.remote_path, None)
            try:
                self._upload_callback(task)
            except Exception:
                self._logger.exception('Remote drive upload task failed: %s', task.remote_path)
