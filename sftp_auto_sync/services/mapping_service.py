from __future__ import annotations

import logging
from pathlib import Path

from sftp_auto_sync.domain.errors import ValidationError
from sftp_auto_sync.domain.models import FileSnapshot
from sftp_auto_sync.domain.models import SyncMapping
from sftp_auto_sync.infra.db.state_repo import StateRepository
from sftp_auto_sync.infra.sftp.path_mapper import PathMapper
from sftp_auto_sync.infra.db.mapping_repo import MappingRepository
from sftp_auto_sync.services.validation_service import ValidationService


class MappingService:
    def __init__(self, mapping_repo: MappingRepository, validation_service: ValidationService, state_repo: StateRepository, path_mapper: PathMapper, logger: logging.Logger | None = None):
        self._mapping_repo = mapping_repo
        self._validation_service = validation_service
        self._state_repo = state_repo
        self._path_mapper = path_mapper
        self._logger = logger or logging.getLogger(__name__)

    def _iter_local_files(self, mapping: SyncMapping):
        root = Path(mapping.local_dir)
        iterable = root.rglob('*') if mapping.recursive else root.glob('*')
        for path in iterable:
            if path.is_dir() or path.is_symlink():
                continue
            yield path

    def _initialize_mapping_state(self, mapping: SyncMapping) -> None:
        if mapping.id is None:
            return
        for path in self._iter_local_files(mapping):
            if self._path_mapper.is_ignored(mapping, path):
                continue
            # Guard against paths that are unexpectedly outside the mapping root.
            try:
                relative = self._path_mapper.to_relative_path(mapping, path)
            except ValueError:
                # Skip files that can't be resolved relative to the mapping root
                # to avoid crashing the initialization when the root is misconfigured
                self._logger.debug(
                    'Skipping path %s for mapping %s: not under root', str(path), getattr(mapping, 'id', None)
                )
                continue
                # Skip files that can't be resolved relative to the mapping root
                # to avoid crashing the initialization when the root is misconfigured
                continue
            stat = path.stat()
            snapshot = FileSnapshot(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
            remote_path = self._path_mapper.to_remote_path(mapping, relative)
            self._state_repo.upsert_baseline(mapping.id, relative, snapshot, remote_path)

    def list_all(self) -> list[SyncMapping]:
        return self._mapping_repo.list_all()

    def list_enabled(self) -> list[SyncMapping]:
        return self._mapping_repo.list_enabled()

    def get(self, mapping_id: int) -> SyncMapping | None:
        return self._mapping_repo.get(mapping_id)

    def save(self, mapping: SyncMapping) -> SyncMapping:
        errors = self._validation_service.validate_mapping(mapping, self._mapping_repo.list_all())
        if errors:
            raise ValidationError(errors)
        if mapping.id is None:
            mapping.id = self._mapping_repo.create(mapping)
            self._initialize_mapping_state(mapping)
        else:
            self._mapping_repo.update(mapping)
        return self._mapping_repo.get(mapping.id) or mapping

    def reinitialize_baseline(self, mapping_id: int) -> SyncMapping:
        mapping = self._mapping_repo.get(mapping_id)
        if mapping is None:
            raise ValueError('Mapping not found.')
        self._state_repo.delete_by_mapping(mapping_id)
        self._initialize_mapping_state(mapping)
        return mapping

    def delete(self, mapping_id: int) -> None:
        self._mapping_repo.delete(mapping_id)
