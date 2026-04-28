@echo off
call conda activate py39
start "" pythonw -m sftp_auto_sync.app.main
exit /b 0
