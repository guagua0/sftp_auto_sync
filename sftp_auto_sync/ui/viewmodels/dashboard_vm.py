from __future__ import annotations

from sftp_auto_sync.domain.dto import DashboardSnapshot
from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.server_service import ServerService
from sftp_auto_sync.services.sync_engine import SyncEngine


class DashboardViewModel:
    def __init__(self, server_service: ServerService, mapping_service: MappingService, history_repo: HistoryRepository, sync_engine: SyncEngine):
        self._server_service = server_service
        self._mapping_service = mapping_service
        self._history_repo = history_repo
        self._sync_engine = sync_engine

    def snapshot(self) -> DashboardSnapshot:
        servers = self._server_service.list_all()
        mappings = self._mapping_service.list_all()
        enabled_mappings = [mapping for mapping in mappings if mapping.enabled]
        return DashboardSnapshot(
            total_servers=len(servers),
            enabled_servers=sum(1 for server in servers if server.enabled),
            total_mappings=len(mappings),
            enabled_mappings=len(enabled_mappings),
            running_mappings=len(enabled_mappings),
            engine_state=self._sync_engine.state,
            queue_length=self._sync_engine.total_queue_length(),
            active_workers=self._sync_engine.active_workers(),
            last_error=self._sync_engine.last_error,
        )

    def recent_history(self, limit: int = 20) -> list[dict]:
        return self._history_repo.list_recent(limit)
