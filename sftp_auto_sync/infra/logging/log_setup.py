from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sftp_auto_sync.app.app_paths import AppPaths
from sftp_auto_sync.app.constants import LOG_BACKUP_COUNT, LOG_MAX_BYTES

BEIJING_TZ = timezone(timedelta(hours=8))


class BeijingTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, tz=BEIJING_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y/%m/%d %H:%M:%S')


class SignalLogHandler(logging.Handler):
    def __init__(self, signals=None):
        super().__init__()
        self._signals = signals

    def emit(self, record: logging.LogRecord) -> None:
        if self._signals is None:
            return
        try:
            self._signals.log_message.emit(
                {
                    'level': record.levelname,
                    'message': self.format(record),
                    'logger': record.name,
                }
            )
        except Exception:
            return


def _build_file_handler(log_dir: Path, filename: str, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    handler = RotatingFileHandler(log_dir / filename, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _resolve_fallback_log_dir() -> Path:
    fallback_dir = Path(tempfile.gettempdir()) / 'SFTPAutoSync' / 'logs'
    fallback_dir.mkdir(parents=True, exist_ok=True)
    return fallback_dir


def setup_logging(paths: AppPaths, signals=None) -> logging.Logger:
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = BeijingTimeFormatter('%(asctime)s | %(levelname)s | %(name)s | %(threadName)s | %(message)s')

    signal_handler = SignalLogHandler(signals)
    signal_handler.setLevel(logging.INFO)
    signal_handler.setFormatter(formatter)
    logger.addHandler(signal_handler)

    try:
        app_handler = _build_file_handler(paths.logs_dir, 'app.log', logging.INFO, formatter)
        error_handler = _build_file_handler(paths.logs_dir, 'error.log', logging.ERROR, formatter)
    except OSError as exc:
        fallback_dir = _resolve_fallback_log_dir()
        app_handler = _build_file_handler(fallback_dir, 'app.log', logging.INFO, formatter)
        error_handler = _build_file_handler(fallback_dir, 'error.log', logging.ERROR, formatter)
        logger.addHandler(app_handler)
        logger.addHandler(error_handler)
        logger.warning(
            'Primary log directory is unavailable; using fallback log directory.',
            extra={
                'primary_log_dir': str(paths.logs_dir),
                'fallback_log_dir': str(fallback_dir),
                'log_error': str(exc),
            },
        )
        return logger

    logger.addHandler(app_handler)
    logger.addHandler(error_handler)
    return logger
