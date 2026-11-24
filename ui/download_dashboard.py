"""Render the download workspace in HTML while reusing the existing application actions."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt, QTimer
from PySide6.QtWidgets import QApplication

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    QWebEngineView = None


def create_download_dashboard(window):
    app = QApplication.instance()
    if QWebEngineView is None or app is None or app.platformName() in {"offscreen", "minimal"}:
        return None
    return DownloadDashboard(window)


if QWebEngineView is not None:
    class _DashboardPage(QWebEnginePage):
        def __init__(self, view):
            super().__init__(view)
            self.view = view

        def javaScriptConsoleMessage(self, _level, message, _line, _source):
            prefix = "leondl-dashboard:"
            if not message.startswith(prefix):
                return
            try:
                action, value = json.loads(message[len(prefix):])
            except (ValueError, TypeError):
                return
            if isinstance(action, str):
                self.view.handle_action(action, value)

        def acceptNavigationRequest(self, url, _type, _main_frame):
            return url.scheme() in {"data", "about"}


    class DownloadDashboard(QWebEngineView):
        def __init__(self, window):
            super().__init__()
            self.window = window
            self.loaded = False
            self._last_state = ""
            self._thumbnails: dict[str, tuple[int, str]] = {}
            self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            page = _DashboardPage(self)
            self.setPage(page)
            for setting in ("LocalContentCanAccessRemoteUrls", "LocalContentCanAccessFileUrls"):
                page.settings().setAttribute(getattr(QWebEngineSettings.WebAttribute, setting), False)
            self.loadFinished.connect(self._loaded)
            self.timer = QTimer(self)
            self.timer.setInterval(150)
            self.timer.timeout.connect(self.refresh)
            asset = Path(__file__).resolve().parents[1] / "assets" / "download_dashboard.html"
            try:
                self.setHtml(asset.read_text(encoding="utf-8"))
            except OSError:
                pass

        def _loaded(self, ok):
            self.loaded = ok
            if ok:
                self.window._sync_dashboard_visibility()
                self.timer.start()
                self.refresh()

        def refresh(self):
            if not self.loaded or not self.isVisible():
                return
            state = json.dumps(self._state(), ensure_ascii=True)
            if state != self._last_state:
                self._last_state = state
                self.page().runJavaScript(f"showDashboard({state})")

        @staticmethod
        def _choices(combo):
            return [{"label": combo.itemText(i), "value": str(combo.itemData(i) or "")}
                    for i in range(combo.count())]

        def _thumbnail(self, card):
            image = card.image.pixmap()
            if image is None or image.isNull():
                return ""
            key = image.cacheKey()
            cached = self._thumbnails.get(card.url)
            if cached and cached[0] == key:
                return cached[1]
            data = QByteArray()
            buffer = QBuffer(data)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buffer, "PNG")
            value = "data:image/png;base64," + bytes(data.toBase64()).decode("ascii")
            self._thumbnails[card.url] = (key, value)
            return value

        def _state(self):
            w = self.window
            t = w._t
            busy = not w.start_button.isEnabled()
            preview_busy = not w.preview_button.isEnabled()
            combos = (("preset", "کیفیت / فرمت", w.preset_combo),
                      ("audio", "زبان صدای ویدئو", w.audio_language_combo),
                      ("subtitle", "زبان زیرنویس", w.subtitle_language_combo))
            options = [{"key": key, "label": t(label), "choices": self._choices(combo),
                        "value": str(combo.currentData() or ""), "disabled": not combo.isEnabled()}
                       for key, label, combo in combos]
            options.append({"key": "folder", "label": t("پوشهٔ خروجی"),
                            "value": w.output_edit.text(), "disabled": busy})
            active_urls = {card.url for card in w.preview_cards}
            self._thumbnails = {key: value for key, value in self._thumbnails.items() if key in active_urls}
            cards = [{"url": card.url, "title": card.title.toolTip() or card.title.text(),
                      "service": card.service.text(), "status": card.status.text(),
                      "meta": card.meta.text(), "audio": card.audio.text(),
                      "subtitles": card.subtitles.text(), "size": card.size.text(),
                      "thumb": self._thumbnail(card), "codecLabel": card.video_codec.accessibleName(),
                      "codecs": self._choices(card.video_codec), "codec": str(card.video_codec.currentData() or ""),
                      "codecEnabled": card.video_codec.isEnabled()}
                     for card in w.preview_cards]
            actions = {
                "links": [{"key": key, "label": label} for key, label in (
                    ("preview", w.preview_button.text()), ("paste", t("چسباندن")),
                    ("clear", t("پاک‌کردن")), ("later", w.later_button.text()))],
                "download": [{"key": key, "label": label} for key, label in (
                    ("start", w.start_button.text()), ("cancel", w.cancel_button.text()),
                    ("open_folder", w.open_folder_button.text()), ("settings", t("تنظیمات")))],
            }
            maximum = w.progress_bar.maximum()
            english = w.language == "en"
            return {
                "theme": w.theme.name, "language": w.language, "dir": "ltr" if english else "rtl",
                "labels": {"page-title": t("دانلود"), "links-title": t("لینک‌های دانلود"),
                           "options-title": "Download options" if english else "گزینه‌های دانلود",
                           "preview-title": t("پیش‌نمایش لینک‌ها"),
                           "progress-title": "Download progress" if english else "پیشرفت دانلود",
                           "queue-title": t("صف دانلود")},
                "pages": [{"key": key, "label": w.main_nav.item(index).text()}
                          for key, index in w.page_indexes.items()],
                "options": options, "links": w.urls_edit.toPlainText(), "actions": actions,
                "busy": busy, "previewBusy": preview_busy, "cards": cards,
                "removeLabel": "Remove preview and link" if english else "حذف پیش‌نمایش و لینک",
                "empty": t("هنوز پیش‌نمایشی ساخته نشده است."),
                "previewCount": w.preview_count_badge.text(), "previewSize": w.preview_size_summary.text(),
                "status": w.status_label.text(), "service": w.active_service_badge.text(),
                "detail": w.detail_label.text(), "percent": w.progress_bar.format(),
                "progress": w.progress_bar.value() * 100 / maximum if maximum else None,
                "stats": [[t("حجم"), w.size_value.text()], [t("سرعت"), w.speed_value.text()],
                          [t("زمان باقی‌مانده"), w.eta_value.text()]],
                "speedSample": getattr(w, "_dashboard_speed", 0),
                "queue": [w.queue_list.item(i).text() for i in range(w.queue_list.count())],
                "queueEmpty": "Queue is empty" if english else "صف خالی است",
            }

        def handle_action(self, action, value):
            w = self.window
            if action == "navigate" and isinstance(value, str) and value in w.page_indexes:
                w._set_main_page_by_key(value)
            elif action == "settings":
                w._set_main_page_by_key("settings")
            elif action == "cancel":
                w.cancel_button.click()
            elif action == "open_folder":
                w.open_folder_button.click()
            elif w.start_button.isEnabled():
                actions = {"preview": w.preview_button.click, "start": w.start_button.click,
                           "paste": w._paste_urls, "clear": w.urls_edit.clear,
                           "later": w.later_button.click, "folder": w._choose_output_dir}
                combos = {"preset": w.preset_combo, "audio": w.audio_language_combo,
                          "subtitle": w.subtitle_language_combo}
                if action in actions:
                    actions[action]()
                elif action == "links" and isinstance(value, str):
                    if value != w.urls_edit.toPlainText():
                        w.urls_edit.setPlainText(value)
                elif action in combos and isinstance(value, str):
                    combo = combos[action]
                    for index in range(combo.count()):
                        if str(combo.itemData(index) or "") == value:
                            combo.setCurrentIndex(index)
                            break
                elif action == "remove" and isinstance(value, str):
                    if any(card.url == value for card in w.preview_cards):
                        w._remove_completed_download_input(value)
                elif action == "codec" and isinstance(value, list) and len(value) == 2:
                    for card in w.preview_cards:
                        if card.url == value[0] and card.video_codec.isEnabled():
                            index = card.video_codec.findData(value[1])
                            if index >= 0:
                                card.video_codec.setCurrentIndex(index)
                            break
            self.refresh()
