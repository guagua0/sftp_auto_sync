from __future__ import annotations

from dataclasses import dataclass, field

from sftp_auto_sync.domain.models import SyncTask


@dataclass(order=True)
class TaskQueueItem:
    priority: int
    available_at: float
    sequence: int
    task: SyncTask = field(compare=False)


@dataclass
class DashboardSnapshot:
    total_servers: int
    enabled_servers: int
    total_mappings: int
    enabled_mappings: int
    running_mappings: int
    engine_state: str
    queue_length: int
    active_workers: int
    last_error: str = ''
