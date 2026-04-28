from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WinFSPyRuntime:
    available: bool = False
    lib_version: str | None = None
    driver_version: str | None = None
    message: str = ''


def probe_winfspy_runtime() -> WinFSPyRuntime:
    result = WinFSPyRuntime()
    
    try:
        import winfspy
        result.lib_version = getattr(winfspy, '__version__', 'unknown')
        
        import winfspy.plumbing
        if hasattr(winfspy.plumbing, 'lib'):
            result.available = True
            result.message = 'WinFSPy is available'
        else:
            result.message = 'WinFSPy FFI library not found'
            
    except ImportError as exc:
        result.message = f'WinFSPy not installed: {exc}'
    except Exception as exc:
        result.message = f'WinFSPy check failed: {exc}'
    
    return result