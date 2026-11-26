from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def text_scale():
    if sys.platform != 'win32':
        return 1.0
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Accessibility') as key:
            value, _ = winreg.QueryValueEx(key, 'TextScaleFactor')
        return max(1.0, min(1.10, int(value) / 100))
    except (OSError, ValueError, TypeError):
        return 1.0


def reduce_motion():
    if sys.platform != 'win32':
        return False
    try:
        enabled = wintypes.BOOL()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x1042, 0, ctypes.byref(enabled), 0)
        return bool(ok) and not bool(enabled.value)
    except (AttributeError, OSError, ValueError):
        return False


class _HighContrast(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.UINT),
        ('dwFlags', wintypes.DWORD),
        ('lpszDefaultScheme', wintypes.LPWSTR),
    ]


def high_contrast():
    if sys.platform != 'win32':
        return False
    try:
        settings = _HighContrast()
        settings.cbSize = ctypes.sizeof(_HighContrast)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0042, settings.cbSize, ctypes.byref(settings), 0)
        return bool(ok) and bool(settings.dwFlags & 0x1)
    except (AttributeError, OSError, ValueError):
        return False
