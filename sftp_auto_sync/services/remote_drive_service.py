from __future__ import annotations

import logging

from sftp_auto_sync.domain.errors import ValidationError
from sftp_auto_sync.domain.models import RemoteDriveMapping
from sftp_auto_sync.infra.db.remote_drive_mapping_repo import RemoteDriveMappingRepository
from sftp_auto_sync.remote_drive.mount_manager import MountManager
from sftp_auto_sync.remote_drive.models import MountStatus
from sftp_auto_sync.services.validation_service import ValidationService


class RemoteDriveService:
    def __init__(
        self,
        remote_drive_repo: RemoteDriveMappingRepository,
        validation_service: ValidationService,
        mount_manager: MountManager | None = None,
        logger: logging.Logger | None = None,
    ):
        self._remote_drive_repo = remote_drive_repo
        self._validation_service = validation_service
        self._mount_manager = mount_manager
        self._logger = logger or logging.getLogger(__name__)

    def list_all(self) -> list[RemoteDriveMapping]:
        return self._remote_drive_repo.list_all()

    def list_enabled(self) -> list[RemoteDriveMapping]:
        return self._remote_drive_repo.list_enabled()

    def get(self, mapping_id: int) -> RemoteDriveMapping | None:
        return self._remote_drive_repo.get(mapping_id)

    def save(self, mapping: RemoteDriveMapping) -> RemoteDriveMapping:
        mapping.drive_letter = mapping.drive_letter.strip().upper().rstrip(':')
        errors = self._validation_service.validate_remote_drive_mapping(mapping, self._remote_drive_repo.list_all())
        if errors:
            raise ValidationError(errors)
        if mapping.id is None:
            mapping.id = self._remote_drive_repo.create(mapping)
        else:
            self._remote_drive_repo.update(mapping)
        return self._remote_drive_repo.get(mapping.id) or mapping

    def delete(self, mapping_id: int) -> None:
        self.unmount(mapping_id)
        self._remote_drive_repo.delete(mapping_id)

    def mount(self, mapping_id: int) -> MountStatus:
        if self._mount_manager is None:
            return MountStatus(mapping_id=mapping_id, state='stopped', message='Mount manager is unavailable.')
        mapping = self.get(mapping_id)
        if mapping is None:
            return MountStatus(mapping_id=mapping_id, state='error', message='Remote drive mapping not found.')
        return self._mount_manager.mount(mapping)

    def unmount(self, mapping_id: int) -> MountStatus:
        if self._mount_manager is None:
            return MountStatus(mapping_id=mapping_id, state='stopped', message='Mount manager is unavailable.')
        return self._mount_manager.unmount(mapping_id)

    def unmount_all(self) -> None:
        if self._mount_manager is not None:
            self._mount_manager.unmount_all()

    def status_for(self, mapping_id: int) -> MountStatus:
        if self._mount_manager is None:
            return MountStatus(mapping_id=mapping_id, state='stopped', message='Mount manager is unavailable.')
        return self._mount_manager.status_for(mapping_id)

    def statuses(self) -> dict[int, MountStatus]:
        if self._mount_manager is None:
            return {}
        return self._mount_manager.statuses()

    def capability_summary(self) -> dict[str, object]:
        if self._mount_manager is None:
            return {'dokany_available': False, 'dokany_provider': 'none', 'dokany_message': 'Mount manager is unavailable.'}
        return self._mount_manager.capability_summary()

    def auto_mount_enabled(self) -> None:
        for mapping in self.list_enabled():
            if mapping.auto_mount:
                self.mount(mapping.id)
