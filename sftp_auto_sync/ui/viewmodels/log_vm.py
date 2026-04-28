from __future__ import annotations

from sftp_auto_sync.infra.db.history_repo import HistoryRepository
from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.server_service import ServerService


class LogViewModel:
    def __init__(self, history_repo: HistoryRepository, server_service: ServerService, mapping_service: MappingService):
        self._history_repo = history_repo
        self._server_service = server_service
        self._mapping_service = mapping_service

    def rows(self, *, limit: int = 500, mapping_id: int | None = None, server_id: int | None = None, status: str | None = None, keyword: str | None = None) -> list[dict]:
        return self._history_repo.list_recent(limit, mapping_id=mapping_id, server_id=server_id, status=status, keyword=keyword)

    def server_options(self) -> list[tuple[int, str]]:
        return [(server.id, server.name) for server in self._server_service.list_all() if server.id is not None]

    def mapping_options(self) -> list[tuple[int, str]]:
        return [(mapping.id, mapping.name) for mapping in self._mapping_service.list_all() if mapping.id is not None]

    def clear_all(self) -> None:
        self._history_repo.clear_all()
