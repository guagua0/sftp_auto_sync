from __future__ import annotations

from pathlib import Path


class KnownHostsManager:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.ensure_exists()

    def ensure_exists(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
