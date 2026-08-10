from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any


def _set_accent_state(widget: Any, state: int, gradient_color: int = 0) -> bool:
    """Set the Windows accent policy only when explicitly opted in.

    SetWindowCompositionAttribute is undocumented and has caused native process
    termination on a subset of Windows/GPU combinations.  The Qt glass design
    works without it, so stability is the default.  Advanced users may opt in
    by setting LEON_ENABLE_NATIVE_BLUR=1 before launch.
    """
    if sys.platform != "win32" or os.environ.get("LEON_ENABLE_NATIVE_BLUR") != "1":
        return False

    try:
        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WindowCompositionAttributeData(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t),
            ]

        accent = AccentPolicy(
            AccentState=state,
            AccentFlags=2 if state else 0,
            GradientColor=gradient_color,
            AnimationId=0,
        )
        data = WindowCompositionAttributeData(
            Attribute=19,
            Data=ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
            SizeOfData=ctypes.sizeof(accent),
        )
        function = ctypes.windll.user32.SetWindowCompositionAttribute
        function.argtypes = [wintypes.HWND, ctypes.POINTER(WindowCompositionAttributeData)]
        function.restype = wintypes.BOOL
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        return bool(function(hwnd, ctypes.byref(data)))
    except Exception:
        return False


def disable_native_blur(widget: Any) -> bool:
    """Disable Acrylic before a window-state transition.

    Windows/DWM can become unstable when a translucent frameless window keeps
    Acrylic enabled while its native surface is being maximized or restored.
    """
    return _set_accent_state(widget, 0, 0)


def enable_native_blur(widget: Any, *, dark: bool = True) -> bool:
    """Best-effort Acrylic blur on Windows; harmless no-op elsewhere."""
    # GradientColor uses AABBGGRR ordering.
    tint = 0xD928160B if dark else 0xCFFFFFFF
    return _set_accent_state(widget, 4, tint)
