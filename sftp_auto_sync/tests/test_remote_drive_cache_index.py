from __future__ import annotations

from sftp_auto_sync.remote_drive.cache_index import CacheIndex


def test_cache_index_get_or_create_and_mark_dirty():
    index = CacheIndex()
    entry = index.get_or_create('/data/a.txt', 'C:/cache/a.bin')
    assert entry.remote_path == '/data/a.txt'
    assert index.get('/data/a.txt') is entry

    index.mark_dirty('/data/a.txt', dirty=True, error='x')
    updated = index.get('/data/a.txt')
    assert updated is not None
    assert updated.is_dirty is True
    assert updated.last_error == 'x'


def test_cache_index_rename_moves_entry():
    index = CacheIndex()
    index.get_or_create('/data/a.txt', 'C:/cache/a.bin')

    renamed = index.rename('/data/a.txt', '/data/b.txt', 'C:/cache/b.bin')
    assert renamed is not None
    assert index.get('/data/a.txt') is None
    assert index.get('/data/b.txt') is renamed
    assert renamed.local_cache_path == 'C:/cache/b.bin'
