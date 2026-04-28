from __future__ import annotations

import logging
import threading
from pathlib import Path

from sftp_auto_sync.domain.models import RemoteDriveMapping
from sftp_auto_sync.infra.secrets.secret_store import SecretStore
from sftp_auto_sync.infra.sftp.connection_manager import ConnectionManager
from sftp_auto_sync.infra.sftp.host_keys import KnownHostsManager
from sftp_auto_sync.remote_drive.file_transfer_service import FileTransferService
from sftp_auto_sync.remote_drive.models import MountStatus
from sftp_auto_sync.remote_drive.session import RemoteDriveSession
from sftp_auto_sync.remote_drive.virtual_drive_facade import VirtualDriveFacade
from sftp_auto_sync.remote_drive.winfspy_adapter import WinFSPyAdapter
from sftp_auto_sync.remote_drive.winfspy_runtime import probe_winfspy_runtime
from sftp_auto_sync.services.server_service import ServerService


class MountManager:
    def __init__(
        self,
        *,
        server_service: ServerService,
        secret_store: SecretStore,
        known_hosts_manager: KnownHostsManager,
        cache_root: str | Path,
        logger: logging.Logger | None = None,
    ):
        self._server_service = server_service
        self._secret_store = secret_store
        self._known_hosts_manager = known_hosts_manager
        self._cache_root = Path(cache_root)
        self._logger = logger or logging.getLogger(__name__)
        self._guard = threading.RLock()
        self._sessions: dict[int, RemoteDriveSession] = {}
        self._connections: dict[int, ConnectionManager] = {}
        self._statuses: dict[int, MountStatus] = {}
        self._winfspy_runtime = probe_winfspy_runtime()
        self._winfspy_adapter: WinFSPyAdapter | None = None
        self._drive_letters: dict[int, str] = {}
        self._available_drives = self._get_available_drives()

    def _get_available_drives(self) -> set[str]:
        """获取可用盘符列表"""
        import ctypes
        used = set()
        
        # 使用 GetLogicalDrives 获取已使用的盘符
        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for i in range(26):
                if bitmask & (1 << i):
                    drive = chr(ord('A') + i) + ':'
                    used.add(drive)
        except Exception:
            pass
        
        all_drives = set(chr(i) + ':' for i in range(ord('A'), ord('Z') + 1))
        return all_drives - used
    
    def _allocate_drive_letter(self) -> str:
        """分配一个可用的盘符"""
        # 重新获取可用盘符
        self._available_drives = self._get_available_drives()
        
        if self._available_drives:
            # 优先使用 Z, Y, X... 等靠后的盘符
            drive = sorted(self._available_drives, reverse=True)[0]
            self._available_drives.discard(drive)
            return drive
        return 'R:'

    def _release_drive_letter(self, drive: str) -> None:
        if drive not in self._available_drives:
            self._available_drives.add(drive)

    def _ensure_winfspy_adapter(self) -> WinFSPyAdapter | None:
        if self._winfspy_adapter is None:
            if not self._winfspy_runtime.available:
                return None
            try:
                facade = VirtualDriveFacade(self)
                self._winfspy_adapter = WinFSPyAdapter(facade, logger=self._logger)
            except Exception as exc:
                self._logger.warning('Failed to create WinFSPy adapter: %s', exc)
                return None
        return self._winfspy_adapter

    def mount(self, mapping: RemoteDriveMapping) -> MountStatus:
        if mapping.id is None:
            raise ValueError('RemoteDriveMapping.id is required for mount().')
        self._logger.info('Starting mount for mapping %s (id=%s)', mapping.name, mapping.id)
        with self._guard:
            if mapping.id in self._sessions:
                previous = self._statuses.get(mapping.id)
                status = self._build_status(
                    mapping.id,
                    'running',
                    'Session already started.',
                    backend=previous.backend if previous else 'session_only',
                    drive_mounted=previous.drive_mounted if previous else False,
                )
                self._statuses[mapping.id] = status
                return status

            server = self._server_service.get(mapping.server_id)
            if server is None:
                status = self._build_status(mapping.id, 'error', 'Server not found.', backend='session_only', drive_mounted=False)
                self._statuses[mapping.id] = status
                return status

            self._logger.info('Connecting to server %s:%d (timeout %ds)', server.host, server.port, server.connect_timeout_sec)
            
            connection_manager = ConnectionManager(self._known_hosts_manager, self._secret_store, logger=self._logger)

            try:
                # 提前测试连接，避免在挂载后才暴露连接问题
                self._logger.info('Testing SFTP connection...')
                test_sftp = connection_manager.connect(server)
                self._logger.info('SFTP connection OK')
                # 关闭测试连接，后续使用时再创建新连接
                connection_manager.close()
                # 重新创建连接管理器
                connection_manager = ConnectionManager(self._known_hosts_manager, self._secret_store, logger=self._logger)
            except Exception as conn_err:
                self._logger.error('SFTP connection failed: %s', conn_err)
                status = self._build_status(mapping.id, 'error', f'SFTP连接失败: {conn_err}', backend='session_only', drive_mounted=False)
                self._statuses[mapping.id] = status
                return status

            def sftp_factory():
                return connection_manager.connect(server)[1]

            self._logger.info('Creating session for mapping %s', mapping.name)
            session = RemoteDriveSession(
                mapping=mapping,
                cache_root=mapping.cache_root or self._cache_root,
                transfer_service=FileTransferService(sftp_factory),
                logger=self._logger,
            )
            try:
                self._logger.info('Starting session for mapping %s', mapping.name)
                session.start()
                self._sessions[mapping.id] = session
                self._connections[mapping.id] = connection_manager
                self._logger.info('Session started, now mounting drive')

                adapter = self._ensure_winfspy_adapter()
                if adapter and self._winfspy_runtime.available:
                    self._logger.info('WinFSPy available, allocating drive letter')
                    drive_letter = self._allocate_drive_letter()
                    self._logger.info('Calling adapter.mount with drive %s', drive_letter)
                    result = adapter.mount_with_label(mapping.id, mapping.name, drive_letter)

                    if result.ok:
                        self._drive_letters[mapping.id] = drive_letter
                        drive_letter_info = f' at {drive_letter}'
                        status = self._build_status(
                            mapping.id,
                            'running',
                            f'Drive mounted successfully{drive_letter_info} (winfspy {self._winfspy_runtime.lib_version}).',
                            backend='winfspy_mounted',
                            drive_mounted=True,
                            drive_letter=drive_letter,
                        )
                    else:
                        self._release_drive_letter(drive_letter)
                        status = self._build_status(
                            mapping.id,
                            'degraded',
                            f'Session started, but drive mount failed: {result.message}',
                            backend='winfspy_runtime_ready',
                            drive_mounted=False,
                        )
                else:
                    self._logger.warning('WinFSPy not available, skipping drive mount')
                    status = self._build_status(
                        mapping.id,
                        'degraded',
                        'Session started. WinFSPy not available - drive mount skipped.',
                        backend='session_only',
                        drive_mounted=False,
                    )

                self._statuses[mapping.id] = status
                self._logger.info('Mount complete for mapping %s: %s', mapping.name, status.state)
                return status
            except Exception as exc:
                self._logger.exception('Mount failed for mapping %s', mapping.name)
                try:
                    connection_manager.close()
                except:
                    pass
                status = self._build_status(mapping.id, 'error', str(exc), backend='session_only', drive_mounted=False)
                self._statuses[mapping.id] = status
                self._logger.exception('Remote drive mount failed: %s', mapping.name)
                return status

    def unmount(self, mapping_id: int) -> MountStatus:
        with self._guard:
            if mapping_id in self._drive_letters:
                adapter = self._ensure_winfspy_adapter()
                if adapter:
                    try:
                        adapter.unmount(mapping_id)
                    except Exception as exc:
                        self._logger.warning('WinFSPy unmount warning: %s', exc)
                drive = self._drive_letters.pop(mapping_id)
                self._release_drive_letter(drive)

            session = self._sessions.pop(mapping_id, None)
            connection_manager = self._connections.pop(mapping_id, None)
            if session is not None:
                try:
                    session.stop()
                except Exception:
                    self._logger.exception('Remote drive session stop failed: %s', mapping_id)
            if connection_manager is not None:
                connection_manager.close()
            backend = 'winfspy_mounted' if self._winfspy_runtime.available else 'session_only'
            status = self._build_status(mapping_id, 'stopped', 'Session stopped.', backend=backend, drive_mounted=False)
            self._statuses[mapping_id] = status
            return status

    def unmount_all(self) -> None:
        with self._guard:
            mapping_ids = list(self._sessions.keys())
        for mapping_id in mapping_ids:
            self.unmount(mapping_id)

    def status_for(self, mapping_id: int) -> MountStatus:
        with self._guard:
            session = self._sessions.get(mapping_id)
            if session is not None:
                previous = self._statuses.get(mapping_id)
                pending_uploads = session.upload_scheduler.pending_count()
                drive_letter = self._drive_letters.get(mapping_id)

                message = previous.message if previous else 'Session started.'
                if previous and previous.drive_mounted and drive_letter:
                    message = f'Drive mounted at {drive_letter}.'

                return self._build_status(
                    mapping_id,
                    previous.state if previous and previous.state != 'stopped' else 'running',
                    message,
                    pending_uploads=pending_uploads,
                    backend=previous.backend if previous else 'session_only',
                    drive_mounted=previous.drive_mounted if previous else False,
                    drive_letter=drive_letter,
                )
            default_backend = 'winfspy_mounted' if self._winfspy_runtime.available else 'session_only'
            return self._statuses.get(mapping_id, self._build_status(mapping_id, 'stopped', 'Not mounted.', backend=default_backend, drive_mounted=False))

    def statuses(self) -> dict[int, MountStatus]:
        with self._guard:
            mapping_ids = set(self._statuses) | set(self._sessions)
        return {mapping_id: self.status_for(mapping_id) for mapping_id in mapping_ids}

    def is_mounted(self, mapping_id: int) -> bool:
        with self._guard:
            return mapping_id in self._sessions

    def is_drive_mounted(self, mapping_id: int) -> bool:
        with self._guard:
            return mapping_id in self._drive_letters

    def get_drive_letter(self, mapping_id: int) -> str | None:
        with self._guard:
            return self._drive_letters.get(mapping_id)

    def session_for(self, mapping_id: int) -> RemoteDriveSession | None:
        with self._guard:
            return self._sessions.get(mapping_id)

    def capability_summary(self) -> dict[str, object]:
        return {
            'winfspy_available': self._winfspy_runtime.available,
            'winfspy_message': self._winfspy_runtime.message,
            'lib_version': self._winfspy_runtime.lib_version,
        }

    @staticmethod
    def _build_status(mapping_id: int, state: str, message: str, pending_uploads: int = 0, *, backend: str, drive_mounted: bool, drive_letter: str | None = None) -> MountStatus:
        return MountStatus(
            mapping_id=mapping_id,
            state=state,
            message=message,
            pending_uploads=pending_uploads,
            backend=backend,
            drive_mounted=drive_mounted,
            drive_letter=drive_letter,
        )
