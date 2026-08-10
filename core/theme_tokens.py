from __future__ import annotations

"""Pure-Python theme tokens shared by the GUI and pre-GUI launcher.

This module deliberately has no Qt dependency. The Windows source launcher can
therefore render the exact saved Leon palette before the virtual environment or
PySide6 is available, while ``ui.theme`` remains the Qt-facing adapter.
"""

from collections import OrderedDict
from copy import deepcopy
from typing import Any


THEME_TOKENS: "OrderedDict[str, dict[str, Any]]" = OrderedDict(
    (
        item["name"],
        item,
    )
    for item in (
        {
            "name": "aurora",
            "display_name": "شفق نیمه‌شب",
            "display_name_en": "Midnight Aurora",
            "dark": True,
            "background_a": "rgba(2, 5, 14, 250)",
            "background_b": "rgba(7, 18, 40, 248)",
            "background_c": "rgba(13, 7, 25, 250)",
            "surface": "rgba(5, 9, 20, 244)",
            "glass": "rgba(15, 31, 58, 142)",
            "glass_strong": "rgba(8, 18, 38, 218)",
            "border": "rgba(147, 177, 231, 68)",
            "text": "#F7FAFF",
            "muted": "#9AAAC2",
            "accent": "#F0C878",
            "accent_hover": "#FFE6A6",
            "accent_soft": "#FFF2C9",
            "accent_text": "#090B12",
            "success": "#62DDA9",
            "danger": "#FF6F91",
            "warning": "#FFCA6B",
            "input_bg": "rgba(2, 8, 20, 190)",
            "input_focus": "rgba(10, 27, 54, 236)",
            "control_hover": "rgba(120, 166, 255, 28)",
            "progress_bg": "rgba(1, 5, 14, 210)",
            "scroll_handle": "rgba(240, 200, 120, 112)",
            "primary_start": "#8C5DCC",
            "primary_end": "#F0C878",
        },
        {
            "name": "obsidian",
            "display_name": "آبسیدین طلایی",
            "display_name_en": "Golden Obsidian",
            "dark": True,
            "background_a": "rgba(3, 4, 8, 248)",
            "background_b": "rgba(4, 14, 31, 246)",
            "background_c": "rgba(10, 10, 12, 248)",
            "surface": "rgba(3, 6, 13, 246)",
            "glass": "rgba(10, 25, 48, 132)",
            "glass_strong": "rgba(6, 13, 26, 214)",
            "border": "rgba(214, 173, 96, 76)",
            "text": "#FFF9EA",
            "muted": "#AEB8C8",
            "accent": "#D6AD60",
            "accent_hover": "#F0D38A",
            "accent_soft": "#FFE7A8",
            "accent_text": "#070707",
            "success": "#79D6A3",
            "danger": "#FF8292",
            "warning": "#F4C76A",
            "input_bg": "rgba(0, 4, 12, 182)",
            "input_focus": "rgba(4, 15, 34, 238)",
            "control_hover": "rgba(214, 173, 96, 32)",
            "progress_bg": "rgba(0, 3, 10, 200)",
            "scroll_handle": "rgba(214, 173, 96, 104)",
            "primary_start": "#9A6C24",
            "primary_end": "#FFE7A8",
        },
        {
            "name": "royal_navy",
            "display_name": "سرمه‌ای سلطنتی",
            "display_name_en": "Royal Navy",
            "dark": True,
            "background_a": "rgba(2, 10, 25, 250)",
            "background_b": "rgba(5, 25, 52, 248)",
            "background_c": "rgba(5, 6, 11, 250)",
            "surface": "rgba(3, 12, 27, 248)",
            "glass": "rgba(15, 39, 72, 142)",
            "glass_strong": "rgba(7, 24, 48, 218)",
            "border": "rgba(232, 194, 111, 84)",
            "text": "#FFF9EA",
            "muted": "#B7C2D4",
            "accent": "#E3BC68",
            "accent_hover": "#FFE09A",
            "accent_soft": "#FFF0BE",
            "accent_text": "#080A0E",
            "success": "#7ED9A6",
            "danger": "#FF8795",
            "warning": "#F6CB70",
            "input_bg": "rgba(1, 8, 20, 192)",
            "input_focus": "rgba(4, 22, 47, 238)",
            "control_hover": "rgba(227, 188, 104, 34)",
            "progress_bg": "rgba(0, 5, 15, 202)",
            "scroll_handle": "rgba(227, 188, 104, 112)",
            "primary_start": "#A7792A",
            "primary_end": "#FFF0BE",
        },
        {
            "name": "light",
            "display_name": "روشنِ عاجی",
            "display_name_en": "Ivory Light",
            "dark": False,
            "background_a": "rgba(250, 247, 238, 252)",
            "background_b": "rgba(235, 241, 248, 250)",
            "background_c": "rgba(255, 252, 244, 252)",
            "surface": "rgba(255, 255, 255, 252)",
            "glass": "rgba(255, 255, 255, 204)",
            "glass_strong": "rgba(248, 250, 253, 242)",
            "border": "rgba(18, 45, 78, 48)",
            "text": "#10243D",
            "muted": "#5C6C80",
            "accent": "#B8862D",
            "accent_hover": "#986A18",
            "accent_soft": "#7A5515",
            "accent_text": "#FFFFFF",
            "success": "#178551",
            "danger": "#C53C4D",
            "warning": "#A66B00",
            "input_bg": "rgba(255, 255, 255, 238)",
            "input_focus": "rgba(247, 250, 255, 255)",
            "control_hover": "rgba(184, 134, 45, 24)",
            "progress_bg": "rgba(19, 42, 68, 20)",
            "scroll_handle": "rgba(16, 36, 61, 82)",
            "primary_start": "#8F651E",
            "primary_end": "#D8B566",
        },
        {
            "name": "youtube",
            "display_name": "استودیوی یوتیوب",
            "display_name_en": "YouTube Studio",
            "dark": True,
            "background_a": "rgba(10, 10, 10, 252)",
            "background_b": "rgba(22, 22, 22, 250)",
            "background_c": "rgba(7, 7, 7, 252)",
            "surface": "rgba(15, 15, 15, 250)",
            "glass": "rgba(35, 35, 35, 184)",
            "glass_strong": "rgba(26, 26, 26, 238)",
            "border": "rgba(255, 255, 255, 38)",
            "text": "#F1F1F1",
            "muted": "#AAAAAA",
            "accent": "#FF0033",
            "accent_hover": "#FF4E67",
            "accent_soft": "#FFFFFF",
            "accent_text": "#FFFFFF",
            "success": "#2BAA66",
            "danger": "#FF5A6D",
            "warning": "#FFB84D",
            "input_bg": "rgba(18, 18, 18, 242)",
            "input_focus": "rgba(35, 35, 35, 252)",
            "control_hover": "rgba(255, 255, 255, 22)",
            "progress_bg": "rgba(255, 255, 255, 24)",
            "scroll_handle": "rgba(255, 255, 255, 82)",
            "primary_start": "#C60028",
            "primary_end": "#FF3359",
        },
    )
)

ALIASES = {
    "midnight": "obsidian",
    "pearl": "royal_navy",
    "youtube_dark": "youtube",
}


def normalize_theme_name(name: str | None, default: str = "youtube") -> str:
    raw = str(name or "").strip().lower()
    normalized = ALIASES.get(raw, raw)
    return normalized if normalized in THEME_TOKENS else default


def theme_tokens(name: str | None, default: str = "youtube") -> dict[str, Any]:
    return deepcopy(THEME_TOKENS[normalize_theme_name(name, default)])
