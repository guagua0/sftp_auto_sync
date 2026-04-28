from __future__ import annotations

from sftp_auto_sync.services.mapping_service import MappingService
from sftp_auto_sync.services.server_service import ServerService


class MappingViewModel:
    def __init__(self, mapping_service: MappingService, server_service: ServerService):
        self._mapping_service = mapping_service
        self._server_service = server_service

    def rows(self) -> list[dict]:
        server_names = {server.id: server.name for server in self._server_service.list_all()}
        rows: list[dict] = []
        for mapping in self._mapping_service.list_all():
            rows.append(
                {
                    'id': mapping.id,
                    'name': mapping.name,
                    'server_name': server_names.get(mapping.server_id, f'#{mapping.server_id}'),
                    'local_dir': mapping.local_dir,
                    'remote_dir': mapping.remote_dir,
                    'recursive': 'Yes' if mapping.recursive else 'No',
                    'delete_policy': mapping.delete_policy.value,
                    'startup_rescan': 'Yes' if mapping.startup_rescan else 'No',
                    'enabled': 'Yes' if mapping.enabled else 'No',
                    'updated_at': mapping.updated_at or '',
                }
            )
        return rows
