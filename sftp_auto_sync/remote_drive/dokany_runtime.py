from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DOKAN_ROOT = Path(r'C:\Program Files\Dokan\Dokan Library-2.3.1')


@dataclass(frozen=True)
class DokanyRuntimeInfo:
    available: bool
    provider: str
    message: str
    install_dir: str | None = None
    dll_path: str | None = None
    lib_version: int | None = None
    driver_version: int | None = None


class DokanyLibrary:
    def __init__(self, dll_path: str | Path):
        self.dll_path = Path(dll_path)
        self._dll = ctypes.WinDLL(str(self.dll_path))
        self._dll.DokanVersion.restype = ctypes.c_ulong
        self._dll.DokanDriverVersion.restype = ctypes.c_ulong

    def version(self) -> int:
        return int(self._dll.DokanVersion())

    def driver_version(self) -> int:
        return int(self._dll.DokanDriverVersion())


def find_dokan_root() -> Path | None:
    if DEFAULT_DOKAN_ROOT.exists():
        return DEFAULT_DOKAN_ROOT
    base = Path(r'C:\Program Files\Dokan')
    if not base.exists():
        return None
    candidates = sorted((path for path in base.iterdir() if path.is_dir() and path.name.startswith('Dokan Library-')), reverse=True)
    return candidates[0] if candidates else None


def find_dokan_dll() -> Path | None:
    root = find_dokan_root()
    if root is None:
        return None
    for candidate in [root / 'dokan2.dll', root / 'x86' / 'dokan2.dll']:
        if candidate.exists():
            return candidate
    return None


def probe_dokany_runtime() -> DokanyRuntimeInfo:
    dll_path = find_dokan_dll()
    root = find_dokan_root()
    if dll_path is None or root is None:
        return DokanyRuntimeInfo(
            available=False,
            provider='none',
            message='Dokan runtime was not found. Install Dokan to enable real drive mounting.',
        )
    try:
        library = DokanyLibrary(dll_path)
        lib_version = library.version()
        driver_version = library.driver_version()
        return DokanyRuntimeInfo(
            available=True,
            provider='dokan2.dll',
            message='Dokan runtime is installed and loadable. Python callback bridge is still required for real mounting.',
            install_dir=str(root),
            dll_path=str(dll_path),
            lib_version=lib_version,
            driver_version=driver_version,
        )
    except Exception as exc:
        return DokanyRuntimeInfo(
            available=False,
            provider='dokan2.dll',
            message=f'Dokan runtime files were found but failed to load: {exc}',
            install_dir=str(root),
            dll_path=str(dll_path),
        )
