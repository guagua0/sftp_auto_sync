from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    engine_state_changed = Signal(str)
    worker_status = Signal(object)
    queue_stats_changed = Signal(object)
    history_changed = Signal()
    config_changed = Signal()
    error_occurred = Signal(str)
    dashboard_refresh_requested = Signal()
    log_message = Signal(object)
