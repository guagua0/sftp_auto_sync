from __future__ import annotations

from enum import Enum


class AuthType(str, Enum):
    PASSWORD = 'password'
    PRIVATE_KEY = 'private_key'


class HostKeyPolicy(str, Enum):
    STRICT = 'strict'
    TOFU = 'tofu'


class DeletePolicy(str, Enum):
    IGNORE = 'ignore'
    DELETE_FILE = 'delete_file'


class TaskAction(str, Enum):
    UPSERT = 'upsert'
    DELETE = 'delete'


class SyncStatus(str, Enum):
    PENDING = 'pending'
    RUNNING = 'running'
    SUCCESS = 'success'
    FAILED = 'failed'
    SKIPPED = 'skipped'


class MappingRunState(str, Enum):
    STOPPED = 'stopped'
    RUNNING = 'running'
    ERROR = 'error'


class ConnectionState(str, Enum):
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    ERROR = 'error'
