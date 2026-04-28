from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sftp_auto_sync.domain.models import RemoteDriveMapping
from sftp_auto_sync.remote_drive.file_transfer_service import FileTransferService
from sftp_auto_sync.remote_drive.models import UploadTask
from sftp_auto_sync.remote_drive.session import RemoteDriveSession


class FakeSFTP:
    def __init__(self):
        self.files = {'/data/a.txt': b'hello'}
        self.directories = {'/', '/data'}
        self.download_count = 0
        self.upload_count = 0

    def listdir_attr(self, remote_dir: str):
        if remote_dir != '/data':
            return []
        return [SimpleNamespace(filename='a.txt', st_mode=0o100644, st_size=5, st_mtime=1)]

    def stat(self, remote_path: str):
        if remote_path in self.directories:
            return SimpleNamespace(st_size=0, st_mtime=1, st_mtime_ns=1_000_000_000)
        data = self.files[remote_path]
        return SimpleNamespace(st_size=len(data), st_mtime=1, st_mtime_ns=1_000_000_000)

    def get(self, remote_path: str, local_path: str):
        self.download_count += 1
        Path(local_path).write_bytes(self.files[remote_path])

    def put(self, local_path: str, remote_path: str):
        self.upload_count += 1
        self.files[remote_path] = Path(local_path).read_bytes()

    def rename(self, old: str, new: str):
        if old in self.files:
            self.files[new] = self.files.pop(old)
        elif old in self.directories:
            self.directories.add(new)
            self.directories.discard(old)

    def mkdir(self, remote_dir: str):
        self.directories.add(remote_dir)
        return None

    def remove(self, remote_path: str):
        self.files.pop(remote_path, None)


class ChangingFakeSFTP(FakeSFTP):
    def __init__(self):
        super().__init__()
        self.files = {'/data/a.txt': b''}
        self._mtime_ns = {'/data/a.txt': 1_000_000_000}

    def stat(self, remote_path: str):
        if remote_path in self.directories:
            return SimpleNamespace(st_size=0, st_mtime=1, st_mtime_ns=1_000_000_000)
        data = self.files[remote_path]
        mtime_ns = self._mtime_ns.get(remote_path, 1_000_000_000)
        return SimpleNamespace(st_size=len(data), st_mtime=mtime_ns / 1_000_000_000, st_mtime_ns=mtime_ns)

    def update_remote(self, remote_path: str, payload: bytes, *, mtime_ns: int):
        self.files[remote_path] = payload
        self._mtime_ns[remote_path] = mtime_ns


class FlakyDownloadFakeSFTP(FakeSFTP):
    def __init__(self):
        super().__init__()
        self.fail_downloads_remaining = 2

    def get(self, remote_path: str, local_path: str):
        self.download_count += 1
        if self.fail_downloads_remaining > 0:
            self.fail_downloads_remaining -= 1
            raise OSError('temporary download failure')
        Path(local_path).write_bytes(self.files[remote_path])


def test_remote_drive_session_downloads_once_and_reuses_cache(tmp_path):
    fake = FakeSFTP()
    session = RemoteDriveSession(
        RemoteDriveMapping(id=1, name='rd1', server_id=1, remote_root='/data', drive_letter='R'),
        tmp_path,
        FileTransferService(lambda: fake),
    )
    session.start()
    try:
        first = session.ensure_cached('/data/a.txt')
        second = session.ensure_cached('/data/a.txt')
        assert Path(first.local_cache_path).read_bytes() == b'hello'
        assert first.local_cache_path == second.local_cache_path
        assert fake.download_count == 1
    finally:
        session.stop()


def test_remote_drive_session_mark_dirty_uploads_file(tmp_path):
    fake = FakeSFTP()
    session = RemoteDriveSession(
        RemoteDriveMapping(id=1, name='rd1', server_id=1, remote_root='/data', drive_letter='R'),
        tmp_path,
        FileTransferService(lambda: fake),
    )
    session.start()
    try:
        entry = session.ensure_cached('/data/a.txt')
        Path(entry.local_cache_path).write_bytes(b'world')
        session.mark_dirty('/data/a.txt')
        assert fake.files['/data/a.txt'] == b'hello'
        session._upload_task(UploadTask(remote_path='/data/a.txt', run_at=0, reason='test', retry_count=0))
        assert fake.files['/data/a.txt'] == b'world'
        cached = session.cache_index.get('/data/a.txt')
        assert cached is not None
        assert cached.is_dirty is False
    finally:
        session.stop()


def test_remote_drive_session_write_read_rename_delete(tmp_path):
    fake = FakeSFTP()
    session = RemoteDriveSession(
        RemoteDriveMapping(id=1, name='rd1', server_id=1, remote_root='/data', drive_letter='R'),
        tmp_path,
        FileTransferService(lambda: fake),
    )
    session.start()
    try:
        session.write_bytes('/data/new.txt', b'abc')
        assert session.read_bytes('/data/new.txt') == b'abc'
        session._upload_task(UploadTask(remote_path='/data/new.txt', run_at=0, reason='test', retry_count=0))
        assert fake.files['/data/new.txt'] == b'abc'
        session.rename_file('/data/new.txt', '/data/renamed.txt')
        assert '/data/renamed.txt' in fake.files
        assert '/data/new.txt' not in fake.files
        session.delete_file('/data/renamed.txt')
        assert '/data/renamed.txt' not in fake.files
    finally:
        session.stop()


def test_remote_drive_session_refreshes_stale_empty_cache(tmp_path):
    fake = ChangingFakeSFTP()
    session = RemoteDriveSession(
        RemoteDriveMapping(id=1, name='rd1', server_id=1, remote_root='/data', drive_letter='R'),
        tmp_path,
        FileTransferService(lambda: fake),
    )
    session.start()
    try:
        first = session.ensure_cached('/data/a.txt')
        assert Path(first.local_cache_path).read_bytes() == b''
        fake.update_remote('/data/a.txt', b'hello', mtime_ns=2_000_000_000)
        second = session.ensure_cached('/data/a.txt')
        assert Path(second.local_cache_path).read_bytes() == b'hello'
        assert second.remote_size == 5
        assert second.remote_mtime_ns == 2_000_000_000
    finally:
        session.stop()


def test_remote_drive_session_retries_download_until_success(tmp_path):
    fake = FlakyDownloadFakeSFTP()
    session = RemoteDriveSession(
        RemoteDriveMapping(id=1, name='rd1', server_id=1, remote_root='/data', drive_letter='R'),
        tmp_path,
        FileTransferService(lambda: fake),
    )
    session.DOWNLOAD_RETRY_DELAY_SEC = 0
    session.start()
    try:
        entry = session.ensure_cached('/data/a.txt')
        assert Path(entry.local_cache_path).read_bytes() == b'hello'
        assert fake.download_count == 3
        assert entry.last_error is None
    finally:
        session.stop()
