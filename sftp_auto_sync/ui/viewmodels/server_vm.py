from __future__ import annotations

from sftp_auto_sync.services.server_service import ServerService


class ServerViewModel:
    def __init__(self, server_service: ServerService):
        self._server_service = server_service

    def rows(self) -> list[dict]:
        rows: list[dict] = []
        for server in self._server_service.list_all():
            rows.append(
                {
                    'id': server.id,
                    'name': server.name,
                    'host': server.host,
                    'port': server.port,
                    'username': server.username,
                    'auth_type': server.auth_type.value,
                    'host_key_policy': server.host_key_policy.value,
                    'enabled': 'Yes' if server.enabled else 'No',
                    'updated_at': server.updated_at or '',
                }
            )
        return rows
