from __future__ import annotations

import threading

from sftp_auto_sync.remote_drive.upload_scheduler import UploadScheduler


def test_upload_scheduler_debounces_same_remote_path():
    seen: list[str] = []
    done = threading.Event()

    def callback(task):
        seen.append(task.remote_path)
        done.set()

    scheduler = UploadScheduler(callback, debounce_sec=0.05)
    scheduler.start()
    try:
        scheduler.schedule('/data/a.txt')
        scheduler.schedule('/data/a.txt')
        assert done.wait(1)
        assert seen == ['/data/a.txt']
    finally:
        scheduler.stop()
