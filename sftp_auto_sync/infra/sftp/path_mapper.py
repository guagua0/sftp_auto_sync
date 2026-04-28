from __future__ import annotations

import fnmatch
import os
from pathlib import Path, PurePosixPath

from sftp_auto_sync.app.constants import DEFAULT_IGNORE_PATTERNS
from sftp_auto_sync.domain.models import SyncMapping


class PathMapper:
    def __init__(self, default_ignore_patterns: list[str] | None = None):
        self._default_ignore_patterns = list(default_ignore_patterns or DEFAULT_IGNORE_PATTERNS)

    @staticmethod
    def _normalize_abs(path: str | Path) -> Path:
        return Path(os.path.abspath(str(path)))

    @staticmethod
    def _root(mapping: SyncMapping) -> Path:
        return Path(os.path.abspath(mapping.local_dir))

    @staticmethod
    def _to_posix_path(path: str | Path) -> str:
        return PurePosixPath(Path(path).as_posix()).as_posix()

    @staticmethod
    def _path_segments(posix_path: str) -> tuple[str, ...]:
        return tuple(segment for segment in PurePosixPath(posix_path).parts if segment not in {'', '.'})

    def _relative_path_or_none(self, mapping: SyncMapping, abs_path: Path) -> str | None:
        if not self.is_under_root(mapping, abs_path):
            return None
        try:
            return self.to_relative_path(mapping, abs_path)
        except ValueError:
            return None

    def _matches_directory_pattern(self, pattern: str, relative_path: str | None, abs_path: Path) -> bool:
        directory_name = pattern[:-1].strip().strip('/\\')
        if not directory_name:
            return False
        candidate_paths: list[str] = []
        if relative_path:
            candidate_paths.append(relative_path)
        candidate_paths.append(self._to_posix_path(abs_path))
        for candidate_path in candidate_paths:
            segments = self._path_segments(candidate_path)
            if directory_name in segments[:-1]:
                return True
        return False

    def _matches_file_pattern(self, pattern: str, relative_path: str | None, abs_path: Path) -> bool:
        normalized_pattern = pattern.strip()
        if not normalized_pattern:
            return False
        basename = abs_path.name
        if fnmatch.fnmatch(basename, normalized_pattern):
            return True
        if relative_path and '/' in normalized_pattern and fnmatch.fnmatch(relative_path, normalized_pattern):
            return True
        return False

    def is_under_root(self, mapping: SyncMapping, abs_path: str | Path) -> bool:
        root = self._root(mapping)
        candidate = self._normalize_abs(abs_path)
        try:
            common = os.path.commonpath([
                os.path.normcase(str(root)),
                os.path.normcase(str(candidate)),
            ])
        except ValueError:
            return False
        return common == os.path.normcase(str(root))

    def to_relative_path(self, mapping: SyncMapping, abs_path: str | Path) -> str:
        root = self._root(mapping)
        candidate = self._normalize_abs(abs_path)
        if not self.is_under_root(mapping, candidate):
            raise ValueError(f'{candidate} is outside mapping root {root}')
        rel = Path(os.path.relpath(candidate, root))
        rel_posix = PurePosixPath(rel.as_posix()).as_posix()
        if rel_posix in {'.', ''}:
            raise ValueError('Path resolves to mapping root, not a file.')
        return rel_posix

    def to_remote_path(self, mapping: SyncMapping, relative_path: str) -> str:
        return str(PurePosixPath(mapping.remote_dir) / PurePosixPath(relative_path))

    def is_ignored(self, mapping: SyncMapping, abs_path: Path) -> bool:
        path = self._normalize_abs(abs_path)
        relative_path = self._relative_path_or_none(mapping, path)
        patterns = [*self._default_ignore_patterns, *mapping.ignore_patterns]
        for pattern in patterns:
            normalized_pattern = pattern.strip()
            if not normalized_pattern:
                continue
            if normalized_pattern.endswith(('/', '\\')):
                if self._matches_directory_pattern(normalized_pattern, relative_path, path):
                    return True
                continue
            if self._matches_file_pattern(normalized_pattern, relative_path, path):
                return True
        return False
