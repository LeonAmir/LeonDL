from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.downloader import create_temporary_cookie_file

try:
    import yt_dlp
except ImportError:
    yt_dlp = None


@dataclass(frozen=True)
class SearchService:
    key: str
    label_fa: str
    label_en: str
    prefix: str
    service_name: str

    def label(self, language: str) -> str:
        return self.label_en if language == "en" else self.label_fa


SEARCH_SERVICES: dict[str, SearchService] = {
    "youtube": SearchService(
        "youtube",
        "YouTube — ویدئو و کانال",
        "YouTube — videos and channels",
        "ytsearch",
        "YouTube",
    ),
    "soundcloud": SearchService(
        "soundcloud",
        "SoundCloud — آهنگ و پادکست",
        "SoundCloud — tracks and podcasts",
        "scsearch",
        "SoundCloud",
    ),
}


def _thumbnail_url(entry: dict[str, Any], service_key: str) -> str:
    identifier = str(entry.get("id") or "").strip()
    # Use YouTube's stable JPEG endpoint. It is more reliable in Qt builds
    # than some WebP/AVIF URLs returned by the extractor.
    if service_key == "youtube" and identifier:
        return f"https://i.ytimg.com/vi/{identifier}/hqdefault.jpg"
    direct = str(entry.get("thumbnail") or entry.get("artwork_url") or "").strip()
    if direct.startswith(("http://", "https://")):
        return direct
    thumbnails = entry.get("thumbnails") or []
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if not isinstance(item, dict):
                continue
            value = str(item.get("url") or "").strip()
            if value.startswith(("http://", "https://")):
                return value
    return ""


def _friendly_url(entry: dict[str, Any], service_key: str) -> str:
    for key in ("webpage_url", "original_url", "url"):
        value = str(entry.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            return value
    identifier = str(entry.get("id") or entry.get("url") or "").strip()
    if service_key == "youtube" and identifier:
        return f"https://www.youtube.com/watch?v={identifier}"
    return identifier


class SearchWorker(QThread):
    started_search = Signal(str)
    ready = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        service_key: str,
        query: str,
        limit: int,
        options: dict[str, Any] | None = None,
        manual_cookie_text: str = "",
        manual_cookie_domain: str = "",
        language: str = "fa",
    ) -> None:
        super().__init__()
        self.service_key = service_key if service_key in SEARCH_SERVICES else "youtube"
        self.query = str(query or "").strip()
        self.limit = max(1, min(50, int(limit)))
        self.options = dict(options or {})
        self.manual_cookie_text = str(manual_cookie_text or "")
        self.manual_cookie_domain = str(manual_cookie_domain or "")
        self.language = "en" if language == "en" else "fa"

    def run(self) -> None:
        if yt_dlp is None:
            self.failed.emit("yt-dlp is not installed." if self.language == "en" else "کتابخانه yt-dlp نصب نشده است.")
            return
        if not self.query:
            self.failed.emit("Enter a search term." if self.language == "en" else "عبارت جست‌وجو را وارد کنید.")
            return

        service = SEARCH_SERVICES[self.service_key]
        search_url = f"{service.prefix}{self.limit}:{self.query}"
        self.started_search.emit(search_url)
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "playlistend": self.limit,
            "lazy_playlist": False,
            "ignoreerrors": True,
            "socket_timeout": 20,
            **self.options,
        }
        temporary_cookie_file = None
        try:
            if self.manual_cookie_text.strip():
                temporary_cookie_file = create_temporary_cookie_file(
                    self.manual_cookie_text,
                    self.manual_cookie_domain or ("youtube.com" if self.service_key == "youtube" else "soundcloud.com"),
                )
                options["cookiefile"] = str(temporary_cookie_file)
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(search_url, download=False)
            entries = list((info or {}).get("entries") or []) if isinstance(info, dict) else []
            results: list[dict[str, Any]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                url = _friendly_url(entry, self.service_key)
                if not url:
                    continue
                entry_type = str(entry.get("_type") or "").lower()
                # Search pages may return channel/playlist containers. They can
                # still be downloaded, but individual media results are shown
                # first and containers are labelled explicitly by the UI.
                results.append(
                    {
                        "title": str(entry.get("title") or entry.get("id") or "Untitled"),
                        "url": url,
                        "thumbnail": _thumbnail_url(entry, self.service_key),
                        "uploader": str(entry.get("uploader") or entry.get("channel") or entry.get("uploader_id") or "—"),
                        "duration": entry.get("duration"),
                        "view_count": entry.get("view_count"),
                        "service": service.service_name,
                        "service_key": self.service_key,
                        "entry_type": entry_type,
                        "id": str(entry.get("id") or ""),
                    }
                )
                if len(results) >= self.limit:
                    break
            self.ready.emit(results)
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            self.failed.emit(message)
        finally:
            if temporary_cookie_file is not None:
                temporary_cookie_file.unlink(missing_ok=True)
