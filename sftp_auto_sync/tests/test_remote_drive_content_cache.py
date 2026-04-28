from __future__ import annotations

from sftp_auto_sync.remote_drive.content_cache import ContentCache


def test_content_cache_write_and_delete(tmp_path):
    cache = ContentCache(tmp_path, 'mount1')
    path = cache.write_bytes_atomic('/remote/a.txt', b'hello')
    assert path.exists()
    assert cache.has_cached_file('/remote/a.txt') is True
    assert path.read_bytes() == b'hello'

    cache.delete('/remote/a.txt')
    assert cache.has_cached_file('/remote/a.txt') is False


def test_content_cache_reset_clears_mount_directory(tmp_path):
    cache = ContentCache(tmp_path, 'mount2')
    cache.write_bytes_atomic('/remote/a.txt', b'hello')
    cache.reset()
    remaining = {path.name for path in cache.base_dir.iterdir()}
    assert remaining == {'files', 'tmp'}

