"""Unicode clipboard access for the Windows desktop bridge."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os


def _libraries():
    if os.name != "nt":
        return None
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.OpenClipboard.argtypes = [wintypes.HWND]
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetClipboardData.argtypes = [wintypes.UINT]
    user.GetClipboardData.restype = wintypes.HANDLE
    user.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user.SetClipboardData.restype = wintypes.HANDLE
    kernel.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel.GlobalFree.argtypes = [wintypes.HGLOBAL]
    return user, kernel


def read_clipboard():
    libraries = _libraries()
    if not libraries:
        return ""
    user, kernel = libraries
    if not user.OpenClipboard(None):
        return ""
    try:
        handle = user.GetClipboardData(13)
        address = kernel.GlobalLock(handle) if handle else None
        if not address:
            return ""
        try:
            return ctypes.wstring_at(address)
        finally:
            kernel.GlobalUnlock(handle)
    finally:
        user.CloseClipboard()


def write_clipboard(value: str):
    libraries = _libraries()
    if not libraries:
        return False
    user, kernel = libraries
    if not user.OpenClipboard(user.GetForegroundWindow()):
        return False
    handle = None
    try:
        data = value.encode("utf-16-le") + b"\0\0"
        handle = kernel.GlobalAlloc(2, len(data))
        address = kernel.GlobalLock(handle) if handle else None
        if not address:
            return False
        ctypes.memmove(address, data, len(data))
        kernel.GlobalUnlock(handle)
        if not user.EmptyClipboard() or not user.SetClipboardData(13, handle):
            return False
        handle = None
        return True
    finally:
        if handle:
            kernel.GlobalFree(handle)
        user.CloseClipboard()
