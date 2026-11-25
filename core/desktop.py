"""Application state and the allowlisted desktop bridge for the web interface."""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
import sys
import tempfile
import threading
import webbrowser
from collections import deque
from pathlib import Path

from core import browser_bridge
from core.auth_store import AuthProfileStore, domains_for_urls
from core.clipboard import read_clipboard, write_clipboard
from core.downloader import (
    BROWSERS, PRESETS, VIDEO_CODECS, DownloadWorker, PreviewWorker, available_video_codecs,
    cookie_text_to_netscape, estimate_selected_media_size, javascript_runtime_options, service_identity,
)
from core.history_store import HistoryStore
from core.later_store import LaterStore
from core.package_manager import PackageActionWorker, PackageStatusWorker, PrerequisiteWorker
from core.search import SEARCH_SERVICES, SearchWorker
from core.sound_events import (
    DEFAULT_SOUND_THEME, DEFAULT_VOLUME, SOUND_EVENTS,
    play_system_sound, resolve_sound_path,
)
from core.theme_tokens import THEME_TOKENS, normalize_theme_name
from core.updater import UpdateCheckWorker, UpdateDownloadWorker, compare_versions, launch_applier

CONFIG = Path.home() / ".yt_dlp_liquid"
_EVENT_AUDIO = {
    "error": "error.mp3",
    "cancelled": "error.mp3",
    "warning": "windows_xp_hardware.mp3",
    "notification": "ballon.mp3",
    "download_complete": "windows_xp_notify.mp3",
    "queue_complete": "windows_xp_notify.mp3",
}


DEFAULTS = {
    "output_dir": str(Path.home() / "Downloads"), "language": "fa", "theme": "youtube",
    "preset": "auto", "audio_language": "", "subtitle_language": "all", "fragments": 4,
    "organize_service": True, "playlist": False, "metadata": False, "thumbnail": False,
    "subtitles": False, "auto_subtitles": False, "mark_watched": False, "clipboard_monitor": False,
    "auth_source": "none", "browser": "Chrome", "browser_profile": "", "cookie_file": "",
    "cookie_domain": "", "remember_auth": False, "js_runtime": "auto", "js_runtime_path": "",
    "sound_enabled": True, "sound_theme": DEFAULT_SOUND_THEME, "sound_volume": DEFAULT_VOLUME,
    "sound_events": {}, "sound_custom": {}, "search_service": "youtube", "search_limit": 10,
    "spotify_use_official_api": False, "spotify_client_id": "", "spotify_proxy": "", "google_play_email": "",
}
ACTIONS = {
    "preview", "download", "cancel", "remove", "save", "queue_add", "queue_remove", "queue_quality",
    "queue_run", "queue_clear", "history_clear", "history_folder", "open_folder", "choose_folder",
    "choose_file", "search", "packages", "package", "bridge", "bridge_install", "bridge_uninstall",
    "sound_test", "update_check", "update_download", "update_apply",
    "auth_clear", "ready", "clipboard_read", "clipboard_write", "window_close",
}
PACKAGE_KEYS = {"yt_dlp", "yt_dlp_ejs", "curl_cffi", "gallery_dl", "spotdl", "apkeep", "ffmpeg", "deno", "pyinstaller"}


def links(value):
    values = value.splitlines() if isinstance(value, str) else value
    return list(dict.fromkeys(line.strip() for line in values if isinstance(line, str) and line.strip()))


class Desktop:
    def __init__(self, version, config=CONFIG):
        self._lock = threading.RLock()
        self._config = Path(config)
        self._settings_path = self._config / "settings.json"
        self._history = HistoryStore(self._config)
        self._later = LaterStore(self._config)
        self._auth_store = AuthProfileStore(self._config)
        self._window = None
        self._allowed_close = False
        self._close_confirmation = False
        self._clipboard = ""
        self._bridge_auth_domains = set()
        self._bridge_poll = 0.0
        self._worker = None
        self._preview_worker = None
        self._search_worker = None
        self._package_worker = None
        self._package_status_worker = None
        self._update_worker = None
        self._update = None
        self._stage = None
        self._queue_groups = []
        self._logs = deque(maxlen=400)
        self._events = deque(maxlen=100)
        self._serial = 0
        self._incoming = deque(maxlen=100)
        self._preview = {}
        self._search = []
        self._packages = []
        self._progress = {}
        self._batch = []
        self._ready = False
        self._message = ""
        self._version = version
        self._manual_cookie = ""
        self._spotify_secret = ""
        self._google_token = ""
        self._settings = dict(DEFAULTS)
        try:
            saved = json.loads(self._settings_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self._settings.update(saved)
        except (OSError, ValueError):
            pass
        self._settings["theme"] = normalize_theme_name(self._settings.get("theme"))

    def _request_close_confirmation(self):
        self._close_confirmation = True

    def _sync_native_caption(self):
        if sys.platform != "win32" or self._window is None or self._window.native is None:
            return
        try:
            import ctypes

            handle = ctypes.c_void_p(self._window.native.Handle.ToInt64())
            dark = ctypes.c_int(self._settings["theme"] != "light")
            api = ctypes.windll.dwmapi.DwmSetWindowAttribute
            value = ctypes.byref(dark)
            size = ctypes.sizeof(dark)
            if api(handle, 20, value, size):
                api(handle, 19, value, size)
        except (OSError, AttributeError, OverflowError):
            pass

    def _log(self, text):
        with self._lock:
            self._logs.append(str(text))

    def _message_changed(self, text):
        with self._lock:
            self._message = str(text)
            self._logs.append(self._message)

    def _save(self, values):
        for key in DEFAULTS.keys() & values.keys():
            if isinstance(values[key], type(DEFAULTS[key])):
                self._settings[key] = values[key]
        for key, attribute in (("manual_cookie", "_manual_cookie"),
                               ("spotify_client_secret", "_spotify_secret"), ("google_play_aas_token", "_google_token")):
            if isinstance(values.get(key), str):
                setattr(self, attribute, values[key])
        self._settings["theme"] = normalize_theme_name(self._settings.get("theme"))
        if "theme" in values:
            self._sync_native_caption()
        self._settings["language"] = "en" if self._settings.get("language") == "en" else "fa"
        if self._settings["preset"] not in PRESETS:
            self._settings["preset"] = "auto"
        self._settings["sound_volume"] = max(0, min(100, self._settings["sound_volume"]))
        self._settings["fragments"] = max(1, min(16, self._settings["fragments"]))
        self._config.mkdir(parents=True, exist_ok=True)
        fd, filename = tempfile.mkstemp(prefix="settings-", dir=self._config)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._settings, stream, ensure_ascii=False, indent=2)
            os.replace(filename, self._settings_path)
        finally:
            Path(filename).unlink(missing_ok=True)

    def _auth(self, urls):
        s = self._settings
        source = s["auth_source"]
        opts = {}
        manual = ""
        domain = s["cookie_domain"]
        domains = domains_for_urls(urls)
        self._auth_store.refresh()
        bridge_domains = [name for name in domains if name in self._bridge_auth_domains]
        extension_required = source == "extension" or bool(bridge_domains)
        match = None
        if extension_required:
            candidate = domains[0] if len(domains) == 1 else ""
            record = self._auth_store.profile(candidate, valid_only=False)
            if record and record.get("method") == "extension":
                match = candidate, record
            elif source == "extension":
                raise ValueError("Send cookies for one site from the Chrome extension first.")
        elif source in {"saved", "auto"} or (source == "none" and s["remember_auth"]):
            match = self._auth_store.profile_for_urls(urls)
        if match:
            domain, record = match
            method = record.get("method", "none")
            if method == "browser":
                browser = str(record.get("browser") or "")
                opts["cookiesfrombrowser"] = (BROWSERS.get(browser, browser.lower()),
                                              record.get("browser_profile") or None, None, None)
            elif method == "manual" or (method == "extension" and record.get("secret_file")):
                manual = self._auth_store.read_manual_secret(record)
                domain = record.get("cookie_domain") or domain
            elif method in {"file", "extension"}:
                path = Path(record.get("cookie_file") or "")
                if not path.is_file():
                    raise ValueError("The saved cookie file could not be found.")
                opts["cookiefile"] = str(path)
        elif source == "browser":
            browser = BROWSERS.get(s["browser"])
            if browser:
                opts["cookiesfrombrowser"] = (browser, s["browser_profile"] or None, None, None)
                if s["remember_auth"]:
                    self._auth_store.remember_browser(domains, s["browser"], s["browser_profile"])
        elif source == "file" and s["cookie_file"]:
            path = Path(s["cookie_file"]).expanduser()
            if not path.is_file():
                raise ValueError("Cookie file could not be found.")
            opts["cookiefile"] = str(path)
            if s["remember_auth"]:
                opts["cookiefile"] = str(self._auth_store.remember_cookie_file(domains, path))
        elif source == "manual":
            manual = self._manual_cookie
            if manual:
                cookie_text_to_netscape(manual, domain)
            if manual and s["remember_auth"]:
                self._auth_store.remember_manual(domains, manual, domain)
        runtime, _ = javascript_runtime_options(s["js_runtime"], s["js_runtime_path"])
        opts.update(runtime)
        return opts, manual, domain

    def _mark_auth_valid(self, url, used_auth):
        if used_auth:
            domains = domains_for_urls([url])
            if self._settings["remember_auth"] or self._bridge_auth_domains.intersection(domains):
                self._auth_store.mark_valid(domains)
                self._bridge_auth_domains.difference_update(domains)

    def _download_options(self, urls, codecs):
        s = self._settings
        opts, manual, domain = self._auth(urls)
        preset = PRESETS[s["preset"]]
        out = Path(s["output_dir"]).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        folder = out / "%(webpage_url_domain|Other)s" if s["organize_service"] else out
        opts.update({
            "format": preset.format_selector, "outtmpl": str(folder / "%(title).180B [%(id)s].%(ext)s"),
            "noplaylist": not s["playlist"], "continuedl": True, "part": True, "retries": 10,
            "fragment_retries": 10, "concurrent_fragment_downloads": s["fragments"],
            "windowsfilenames": os.name == "nt", "ignoreerrors": False, "mark_watched": s["mark_watched"],
            "_leon_output_root": str(out), "_leon_audio_language": s["audio_language"],
            "_leon_video_codecs": {} if preset.key.startswith("audio_") else codecs,
            "_leon_google_play_email": s["google_play_email"], "_leon_google_play_aas_token": self._google_token,
            "_leon_spotify_format": "m4a" if preset.key == "audio_m4a" else "mp3",
            "_leon_spotify_use_official_api": s["spotify_use_official_api"],
            "_leon_spotify_client_id": s["spotify_client_id"], "_leon_spotify_client_secret": self._spotify_secret,
            "_leon_spotify_proxy": s["spotify_proxy"],
        })
        if preset.merge_output_format:
            opts["merge_output_format"] = preset.merge_output_format
        if preset.format_sort:
            opts["format_sort"] = list(preset.format_sort)
        processors = []
        if preset.audio_codec:
            processor = {"key": "FFmpegExtractAudio", "preferredcodec": preset.audio_codec}
            if preset.audio_codec == "mp3":
                processor["preferredquality"] = "0"
            processors.append(processor)
        if s["metadata"]:
            processors.append({"key": "FFmpegMetadata"})
        if s["thumbnail"]:
            opts["writethumbnail"] = True
            processors.append({"key": "EmbedThumbnail"})
        if s["subtitles"]:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = s["auto_subtitles"]
            opts["subtitleslangs"] = [s["subtitle_language"] or "all"]
            if not preset.key.startswith("audio_"):
                processors.append({"key": "FFmpegEmbedSubtitle"})
        if processors:
            opts["postprocessors"] = processors
        return opts, manual, domain

    def _preview_urls(self, urls):
        if self._preview_worker and self._preview_worker.isRunning():
            self._preview_worker.requestInterruption()
        opts, manual, domain = self._auth(urls)
        if self._settings["mark_watched"] and (manual or opts.get("cookiefile") or opts.get("cookiesfrombrowser")):
            opts["mark_watched"] = True
        worker = PreviewWorker(urls, opts, manual, domain, self._settings["language"])
        self._preview_worker = worker
        self._preview = {url: {"url": url, "title": url, "status": "pending"} for url in urls}

        def ready(index, info):
            with self._lock:
                url = urls[index]
                if self._preview_worker is worker and url in self._preview:
                    self._mark_auth_valid(url, manual or opts.get("cookiefile") or opts.get("cookiesfrombrowser"))
                    self._preview[url] = {"url": url, "status": "ready", **info,
                                          "codecs": available_video_codecs(info)}

        def failed(index, message, url):
            with self._lock:
                if self._preview_worker is worker and url in self._preview:
                    self._preview[urls[index]].update(status="error", error=message)

        worker.ready.connect(ready)
        worker.failed.connect(failed)
        worker.start()

    def _start(self, urls, codecs, overrides=None):
        if not urls or (self._worker and self._worker.isRunning() and not self._queue_groups):
            return
        current = dict(self._settings)
        self._settings.update(overrides or {})
        if self._settings["preset"] not in PRESETS:
            self._settings["preset"] = current["preset"]
        try:
            opts, manual, domain = self._download_options(urls, codecs)
            selected = self._settings["preset"]
            output = self._settings["output_dir"]
        finally:
            self._settings = current
        worker = DownloadWorker(urls, opts, manual, domain, self._settings["language"])
        self._worker = worker
        self._progress = {"status": "preparing", "percent": 0}
        self._batch = [{"url": url, "title": self._preview.get(url, {}).get("title") or url, "status": "waiting"} for url in urls]
        completed = {}
        current_url = iter(urls)
        active = [next(current_url)]

        def progress(data):
            with self._lock:
                self._progress = dict(data)
                for entry in self._batch:
                    if entry["url"] == active[0] and entry["status"] != "completed":
                        entry.update(title=data.get("title") or entry["title"], status="downloading")
                        break
                if active[0] and data.get("status") == "finished":
                    completed[active[0]] = dict(data)

        def item_finished(url):
            with self._lock:
                item = completed.get(url, {})
                entry = {
                    "url": url, "title": item.get("title") or self._preview.get(url, {}).get("title") or url,
                    "service": item.get("service") or service_identity(None, url)["service"],
                    "preset": selected, "output_dir": output,
                }
                if item.get("filepath"):
                    entry["filepath"] = item["filepath"]
                if url in worker.received_by_url:
                    entry["received_bytes"] = worker.received_by_url[url]
                self._history.add_many([entry])
                self._mark_auth_valid(url, manual or opts.get("cookiefile") or opts.get("cookiesfrombrowser"))
                for job in self._batch:
                    if job["url"] == url:
                        job.update(title=entry["title"], status="completed")
                        break
                self._preview.pop(url, None)
                self._incoming.append({"action": "completed", "url": url})
                active[0] = next(current_url, "")
                self._sound("download_complete")

        def finished():
            with self._lock:
                self._history.add_received_bytes(sum(worker.received_by_url.values()))
                if self._allowed_close:
                    self._window.destroy()
                elif self._queue_groups:
                    group, settings = self._queue_groups.pop(0)
                    self._worker = None
                    self._start(group, {}, settings)

        def result(status, event, message=""):
            with self._lock:
                self._progress.update(status=status)
                if status != "completed":
                    for entry in self._batch:
                        if entry["status"] != "completed":
                            entry["status"] = status
                    if status == "cancelled":
                        self._queue_groups.clear()
                if message:
                    self._message_changed(message)
                if event:
                    self._sound(event)

        worker.log.connect(self._log)
        worker.progress.connect(progress)
        worker.postprocess.connect(lambda message: self._message_changed(message))
        worker.item_finished.connect(item_finished)
        worker.finished_ok.connect(lambda: result("completed", "queue_complete" if len(urls) > 1 else ""))
        worker.failed.connect(lambda message: result("error", "error", message))
        worker.cancelled.connect(lambda: result("cancelled", "cancelled"))
        worker.finished.connect(finished)
        worker.start()

    def _sound(self, event, force=False):
        s = self._settings
        checked = s.get("sound_events") or {}
        if not force and (not s["sound_enabled"] or not checked.get(event, True)):
            return
        theme = s["sound_theme"]
        paths = dict(s.get("sound_custom") or {})
        volume = s["sound_volume"] / 100

        def prepare():
            # Resolve custom files without loading a cached copy of the old default pack.
            path = resolve_sound_path("system", event, paths)
            if path is None and theme == "gentle":
                path = Path(__file__).resolve().parents[1] / "assets" / "sounds" / "events" / _EVENT_AUDIO[event]
            if path is None:
                if theme == "system":
                    play_system_sound(event)
                return
            try:
                mime = mimetypes.guess_type(path.name)[0] or "audio/wav"
                if path.stat().st_size > 12 * 1024 * 1024:
                    return
                data = base64.b64encode(path.read_bytes()).decode("ascii")
                with self._lock:
                    self._serial += 1
                    self._events.append({"id": self._serial, "audio": f"data:{mime};base64,{data}", "volume": volume})
            except OSError:
                pass

        threading.Thread(target=prepare, daemon=True).start()

    def _receive_browser(self):
        now = time.monotonic()
        if now - self._bridge_poll < 1.2:
            return
        self._bridge_poll = now
        browser_bridge.touch_app_heartbeat()
        if self._settings["clipboard_monitor"]:
            current = read_clipboard()
            if current and current != self._clipboard:
                self._clipboard = current
                for url in re.findall(r"https?://[^\s<>]+", current):
                    self._incoming.append({"action": "clipboard", "url": url})
        for request in browser_bridge.consume_browser_requests():
            url = request.get("url")
            if not url:
                continue
            self._bridge_auth_domains.update(request.get("cookie_domains") or [])
            if request.get("action") == "queue":
                self._later.add_many([{"url": url, "title": request.get("title") or url,
                                       "preset": self._settings["preset"]}])
            else:
                self._incoming.append({"action": "open", "url": url})
            self._sound("notification")

    def snapshot(self, audio_after=0):
        with self._lock:
            try:
                self._receive_browser()
            except OSError:
                pass
            language = self._settings["language"]
            cards = []
            for card in self._preview.values():
                tiny = {k: card[k] for k in ("url", "title", "status", "service", "duration", "thumbnail",
                                             "error", "codecs", "audio_languages", "subtitle_languages") if k in card}
                if card.get("status") == "ready":
                    preset = self._settings["preset"]
                    audio = self._settings["audio_language"]
                    key = (preset, audio)
                    if card.get("_size_key") != key:
                        codecs = [] if preset.startswith("audio_") else card["codecs"]
                        card["_sizes"] = {
                            codec: estimate_selected_media_size(card, preset, audio, video_codec=codec)
                            for codec in ["", *codecs]
                        }
                        card["_size_key"] = key
                    tiny["sizes"] = card["_sizes"]
                cards.append(tiny)
            state = {
                "version": self._version, "settings": {key: self._settings[key] for key in DEFAULTS},
                "presets": [{"key": key, "label": item.label(language)} for key, item in PRESETS.items()],
                "searchServices": [{"key": key, "label": item.label(language)} for key, item in SEARCH_SERVICES.items()],
                "themes": [{"key": key, "label": item["display_name_en" if language == "en" else "display_name"]}
                           for key, item in THEME_TOKENS.items()],
                "browsers": list(BROWSERS), "codecs": {key: item[0] for key, item in VIDEO_CODECS.items()},
                "soundEvents": list(SOUND_EVENTS), "preview": cards, "search": self._search,
                "queue": self._later.load(), "batch": list(self._batch), "history": self._history.load(), "received": self._history.received_bytes(),
                "logs": list(self._logs), "packages": self._packages, "message": self._message,
                "progress": self._progress, "busy": self._worker is not None and self._worker.isRunning(),
                "previewBusy": self._preview_worker is not None and self._preview_worker.isRunning(),
                "searchBusy": self._search_worker is not None and self._search_worker.isRunning(),
                "packageBusy": bool(self._package_worker and self._package_worker.isRunning()),
                "closeConfirmation": self._close_confirmation,
                "update": self._update.version if self._update else "", "updateReady": self._stage is not None,
                "incoming": list(self._incoming),
                "sounds": [value for value in self._events if value["id"] > audio_after],
            }
            self._incoming.clear()
            self._close_confirmation = False
            return state

    def dispatch(self, action, payload=None):
        if not isinstance(action, str) or action not in ACTIONS:
            return {"error": "Unknown operation"}
        data = payload if isinstance(payload, dict) else {}
        try:
            # Dialogs must not hold the state lock while the user is choosing a file.
            if action in {"choose_folder", "choose_file"}:
                import webview
                kind = webview.FileDialog.FOLDER if action == "choose_folder" else webview.FileDialog.OPEN
                result = self._window.create_file_dialog(kind, allow_multiple=False)
                return {"path": result[0] if result else ""}
            if action == "window_close":
                if not self._window:
                    return {"error": "Window is unavailable."}
                with self._lock:
                    self._allowed_close = True
                    if self._worker and self._worker.isRunning():
                        self._worker.cancel()
                        return {"ok": True}
                self._window.destroy()
                return {"ok": True}
            with self._lock:
                return self._dispatch(action, data)
        except Exception as exc:
            self._message_changed(str(exc))
            return {"error": str(exc)}

    def _dispatch(self, action, data):
        if action == "ready":
            if not self._ready:
                self._ready = True
                self._sync_native_caption()
                ready_file = os.environ.get("LEON_READY_FILE")
                if ready_file:
                    Path(ready_file).write_text("ready", encoding="utf-8")
                self._start_prerequisites()
        elif action == "clipboard_read":
            return {"text": read_clipboard()}
        if action == "clipboard_write":
            value = str(data.get("text") or "")[:100_000]
            return {"ok": write_clipboard(value)}
        if action == "save":
            self._save(data)
        elif action in {"preview", "download", "queue_add"}:
            urls = links(data.get("urls", ""))
            if not urls:
                return {"error": "Enter a link first."}
            if action == "preview":
                self._preview_urls(urls)
            elif action == "download":
                if self._worker and self._worker.isRunning():
                    return {"error": "A download is already running."}
                codecs = {url: codec for url, codec in data.get("codecs", {}).items()
                          if url in urls and codec in VIDEO_CODECS}
                self._start(urls, codecs)
            else:
                self._later.add_many([{
                    "url": url, "title": self._preview.get(url, {}).get("title") or url,
                    "service": self._preview.get(url, {}).get("service"),
                    "duration": self._preview.get(url, {}).get("duration"),
                    **{key: self._settings[key] for key in ("preset", "output_dir", "audio_language", "organize_service")},
                } for url in urls])
        elif action == "remove":
            self._preview.pop(str(data.get("url")), None)
        elif action == "cancel":
            self._queue_groups.clear()
            if self._worker:
                self._worker.cancel()
        elif action == "queue_remove":
            self._later.remove_indexes(data.get("indexes", []))
        elif action == "queue_quality":
            preset = data.get("preset")
            if preset in PRESETS:
                self._later.update_index(int(data["index"]), {"preset": preset, "preset_label": PRESETS[preset].label(self._settings["language"])})
        elif action == "queue_clear":
            self._later.clear()
        elif action == "queue_run":
            if self._worker and self._worker.isRunning():
                return {"error": "A download is already running."}
            groups = {}
            entries = self._later.load()
            indexes = set(data.get("indexes", []))
            for index, entry in enumerate(entries):
                if not indexes or index in indexes:
                    choices = tuple(entry.get(key) if entry.get(key) is not None and entry.get(key) != "" else self._settings[key]
                                    for key in ("preset", "output_dir", "audio_language", "organize_service"))
                    groups.setdefault(choices, []).append(entry["url"])
            self._queue_groups = [(group, dict(zip(("preset", "output_dir", "audio_language", "organize_service"), choices)))
                                  for choices, group in groups.items()]
            if self._queue_groups:
                group, settings = self._queue_groups.pop(0)
                self._start(group, {}, settings)
        elif action == "auth_clear":
            domains = domains_for_urls(links(data.get("urls", "")))
            if domains:
                for domain in domains:
                    self._auth_store.remove(domain)
            else:
                self._auth_store.clear()
        elif action == "history_clear":
            self._history.clear()
        elif action in {"open_folder", "history_folder"}:
            path = self._settings["output_dir"]
            if action == "history_folder":
                path = self._history.load()[int(data["index"])].get("output_dir") or path
            folder = Path(path).expanduser().resolve()
            if not folder.is_dir():
                return {"error": "Folder does not exist."}
            if os.name == "nt":
                os.startfile(folder)
            else:
                webbrowser.open(folder.as_uri())
        elif action == "search":
            if self._search_worker and self._search_worker.isRunning():
                return {"error": "Search is already running."}
            opts, manual, domain = self._auth([])
            worker = SearchWorker(data.get("service"), data.get("query"), data.get("limit", 10),
                                  opts, manual, domain, self._settings["language"])
            self._search_worker = worker
            worker.ready.connect(lambda rows: setattr(self, "_search", rows))
            worker.failed.connect(self._message_changed)
            worker.start()
        elif action == "packages":
            self._refresh_packages()
        elif action == "package":
            if self._package_worker and self._package_worker.isRunning():
                return {"error": "A package action is already running."}
            key = data.get("key")
            if key not in PACKAGE_KEYS:
                return {"error": "Unknown package"}
            worker = PackageActionWorker(("update_" if data.get("installed") else "install_") + key)
            self._package_worker = worker
            worker.log.connect(self._log)
            worker.finished_action.connect(lambda _ok, message: self._message_changed(message))
            worker.finished.connect(self._refresh_packages)
            worker.start()
        elif action == "bridge_install":
            browser_bridge.install_browser_bridge()
        elif action == "bridge_uninstall":
            browser_bridge.uninstall_browser_bridge()
        elif action == "bridge":
            return {"bridge": browser_bridge.bridge_status(), "token": browser_bridge.pairing_token()}
        elif action == "sound_test":
            event = data.get("event")
            if event in SOUND_EVENTS:
                self._sound(event, force=True)
        elif action == "update_check":
            worker = UpdateCheckWorker()
            self._update_worker = worker
            worker.checked.connect(self._update_checked)
            worker.start()
        elif action == "update_download" and self._update and compare_versions(self._update.version, self._version) > 0:
            worker = UpdateDownloadWorker(self._update)
            self._update_worker = worker
            worker.staged.connect(self._update_staged)
            worker.start()
        elif action == "update_apply" and self._stage:
            launch_applier(self._stage)
            self._allowed_close = True
            self._window.destroy()
        return {"ok": True}

    def _refresh_packages(self):
        if self._package_status_worker and self._package_status_worker.isRunning():
            return
        worker = PackageStatusWorker()
        self._package_status_worker = worker
        worker.ready.connect(lambda rows: setattr(self, "_packages", rows))
        worker.failed.connect(self._message_changed)
        worker.start()

    def _update_checked(self, ok, release, error):
        with self._lock:
            self._update = release if ok and release and compare_versions(release.version, self._version) > 0 else None
            self._message_changed(error or ("Update check complete." if ok else "Update check failed."))

    def _update_staged(self, ok, message, staging):
        with self._lock:
            self._stage = staging if ok else None
            self._message_changed(message)

    def _start_prerequisites(self):
        if getattr(sys, "frozen", False):
            worker = PrerequisiteWorker()
            worker.log.connect(self._log)
            worker.start()
