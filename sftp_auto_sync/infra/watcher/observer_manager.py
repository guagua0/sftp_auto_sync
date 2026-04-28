from __future__ import annotations

import logging

from watchdog.observers import Observer

from sftp_auto_sync.domain.models import SyncMapping


class ObserverManager:
    def __init__(self, logger: logging.Logger | None = None):
        self._logger = logger or logging.getLogger(__name__)
        self._observer: Observer | None = None
        self._watches: dict[int, object] = {}

    def start(self, mappings: list[SyncMapping], handler_factory) -> None:
        self.stop()
        observer = Observer()
        for mapping in mappings:
            if mapping.id is None:
                continue
            watch = observer.schedule(handler_factory(mapping), mapping.local_dir, recursive=mapping.recursive)
            self._watches[mapping.id] = watch
        observer.start()
        self._observer = observer

    def stop(self) -> None:
        if self._observer is None:
            return
        try:
            self._observer.unschedule_all()
        except Exception:
            pass
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        self._watches.clear()

    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()
