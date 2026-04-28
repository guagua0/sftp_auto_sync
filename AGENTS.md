# AGENTS.md - SFTP Auto Sync Project

## Project Overview

A Python desktop application for SFTP file synchronization with virtual drive mounting capabilities on Windows. Uses PySide6 for the GUI and supports WinFSPy for creating virtual drive letters.

## Environment Setup

```bash
# Activate the development environment
conda activate py39

# Install dependencies
pip install -r requirements.txt

# Additional dependency for virtual drive (WinFSPy)
pip install winfspy
```

## Build/Lint/Test Commands

```bash
# Run the application
python -m sftp_auto_sync.app.main

# Run all tests
pytest sftp_auto_sync/tests/

# Run a single test file
pytest sftp_auto_sync/tests/test_remote_drive_session.py

# Run a single test function
pytest sftp_auto_sync/tests/test_remote_drive_session.py::test_remote_drive_session_downloads_once_and_reuses_cache

# Run tests with verbose output
pytest -v sftp_auto_sync/tests/

# Run tests with coverage
pytest --cov=sftp_auto_sync sftp_auto_sync/tests/
```

## Project Structure

```
sftp_auto_sync/
├── app/                    # Application entry point, bootstrap, signals
├── domain/                 # Core domain models, enums, errors
├── infra/                  # Infrastructure: DB, SFTP, logging, secrets, watcher
│   ├── db/                 # SQLite repositories and migrations
│   ├── sftp/               # SFTP connection and operations
│   ├── secrets/            # Keyring-based secret storage
│   └── watcher/            # File system watcher
├── remote_drive/           # Virtual drive implementation (WinFSPy)
├── services/               # Business logic services
├── ui/                     # PySide6 UI components
│   ├── dialogs/            # Dialog windows
│   ├── pages/              # Main page widgets
│   └── viewmodels/         # View models for MVVM pattern
└── workers/                # Background worker threads
```

## Code Style Guidelines

### Imports

```python
# Standard library imports first
from __future__ import annotations
import logging
import threading
from pathlib import Path

# Third-party imports second
from PySide6.QtWidgets import QWidget
import paramiko

# Local imports last (absolute imports preferred)
from sftp_auto_sync.domain.models import ServerProfile
from sftp_auto_sync.infra.db.connection_factory import ConnectionFactory
```

### Type Annotations

- Always use `from __future__ import annotations` at the top of files
- Use modern Python type syntax: `int | None` instead of `Optional[int]`
- Use `list[str]` instead of `List[str]` (no need to import from typing)
- Use `dict[str, object]` instead of `Dict[str, object]`

```python
# Good
def get(self, server_id: int) -> ServerProfile | None:
    ...

def list_all(self) -> list[ServerProfile]:
    ...
```

### Dataclasses

- Use `@dataclass` for model classes
- Do NOT use `slots=True` (Python 3.9 compatibility)
- Provide default values for optional fields

```python
# Good
@dataclass
class ServerProfile:
    id: int | None = None
    name: str = ''
    host: str = ''
    port: int = 22
    enabled: bool = True
```

### Naming Conventions

- **Classes**: PascalCase (e.g., `ServerProfile`, `RemoteDriveSession`)
- **Functions/Methods**: snake_case (e.g., `get_server`, `list_dir`)
- **Private attributes**: `_prefix` (e.g., `_sessions`, `_guard`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `DEFAULT_TIMEOUT_SEC`)
- **Enum values**: UPPER_SNAKE_CASE (e.g., `AUTH_TYPE_PASSWORD`)

### Error Handling

- Use custom exceptions from `domain/errors.py`
- Catch specific exceptions, not bare `except:`
- Log exceptions with context before re-raising or handling

```python
from sftp_auto_sync.domain.errors import ValidationError, ConnectionError

try:
    # operation
except ValidationError:
    raise
except Exception as exc:
    self._logger.exception('Operation failed: %s', exc)
    raise ConnectionError(str(exc)) from exc
```

### Logging

```python
# Use module-level logger
self._logger = logger or logging.getLogger(__name__)

# Log levels
self._logger.debug('Detailed diagnostic info: %s', value)
self._logger.info('Normal operation: %s', description)
self._logger.warning('Unexpected but handled: %s', issue)
self._logger.error('Error occurred: %s', error)
self._logger.exception('Exception with traceback: %s', exc)  # includes traceback
```

### Threading

- Use `threading.Lock` or `threading.RLock` for thread safety
- Daemon threads for background tasks: `threading.Thread(target=fn, daemon=True)`
- Use QTimer for UI thread communication from background threads

### Qt/UI Guidelines

- Use signals/slots for cross-thread UI updates
- Never block the UI thread with long operations
- Use background threads with QTimer polling for status checks

```python
def mount_selected(self) -> None:
    def do_mount():
        self._mount_status = self._remote_drive_service.mount(mapping_id)
    
    thread = threading.Thread(target=do_mount, daemon=True)
    thread.start()
    
    self._mount_timer = QTimer()
    self._mount_timer.timeout.connect(check_result)
    self._mount_timer.start(500)  # Check every 500ms
```

### Repository Pattern

- All DB access through repository classes
- Use `ConnectionFactory.connect()` context manager
- Return domain models, not raw SQL rows

```python
class ServerRepository:
    def __init__(self, connection_factory: ConnectionFactory):
        self._connection_factory = connection_factory
    
    def get(self, server_id: int) -> ServerProfile | None:
        with self._connection_factory.connect() as conn:
            cursor = conn.execute('SELECT * FROM servers WHERE id = ?', (server_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            return self._row_to_profile(row)
```

## Testing Guidelines

- Use `pytest` with `tmp_path` fixture for file operations
- Create fake/stub classes for external dependencies (SFTP, etc.)
- Test file naming: `test_<module_name>.py`
- Test function naming: `test_<class>_<method>_<scenario>`

```python
class FakeSFTP:
    def __init__(self):
        self.files = {'/data/a.txt': b'hello'}
    
    def listdir_attr(self, remote_dir: str):
        return [SimpleNamespace(filename='a.txt', st_mode=0o100644)]

def test_remote_drive_session_downloads_once_and_reuses_cache(tmp_path):
    fake = FakeSFTP()
    session = RemoteDriveSession(mapping, tmp_path, FileTransferService(lambda: fake))
    session.start()
    try:
        # assertions
    finally:
        session.stop()
```

## Python Version

- Target Python 3.9 (required by WinFSPy)
- Avoid Python 3.10+ only features like `dataclass(slots=True)`
