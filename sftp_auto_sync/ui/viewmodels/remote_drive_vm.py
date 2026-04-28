from __future__ import annotations

from sftp_auto_sync.services.remote_drive_service import RemoteDriveService
from sftp_auto_sync.services.server_service import ServerService


class RemoteDriveViewModel:
    def __init__(self, remote_drive_service: RemoteDriveService, server_service: ServerService):
        self._remote_drive_service = remote_drive_service
        self._server_service = server_service

    def rows(self) -> list[dict]:
        server_names = {server.id: server.name for server in self._server_service.list_all()}
        statuses = self._remote_drive_service.statuses()
        rows: list[dict] = []
        for mapping in self._remote_drive_service.list_all():
            mapping_id = mapping.id
            if mapping_id is None:
                continue
            status = statuses.get(mapping_id) or self._remote_drive_service.status_for(mapping_id)
            drive_letter_display = status.drive_letter if status.drive_letter else f"{mapping.drive_letter}:"
            rows.append(
                {
                    'id': mapping_id,
                    'name': mapping.name,
                    'server_name': server_names.get(mapping.server_id, f'#{mapping.server_id}'),
                    'remote_root': mapping.remote_root,
                    'drive_letter': drive_letter_display,
                    'status': status.state,
                    'backend': status.backend,
                    'drive_mounted': 'Yes' if status.drive_mounted else 'No',
                    'status_message': status.message,
                    'pending_uploads': status.pending_uploads,
                    'auto_mount': 'Yes' if mapping.auto_mount else 'No',
                    'read_only': 'Yes' if mapping.read_only else 'No',
                    'enabled': 'Yes' if mapping.enabled else 'No',
                    'updated_at': mapping.updated_at or '',
                }
            )
        return rows
