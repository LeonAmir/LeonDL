from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from typing import Any
from urllib.request import Request, urlopen

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QProcess, QPropertyAnimation, QSize, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QActionGroup, QCloseEvent, QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QPixmap, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QProgressBar,
    QStackedWidget,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.auth_store import AuthProfileStore, AuthStoreError, domains_for_urls, service_domain
from core.browser_bridge import (
    BrowserBridgeError,
    EXTENSION_ID,
    bridge_status,
    clear_app_heartbeat,
    consume_browser_requests,
    install_browser_bridge,
    installed_extension_dir,
    pairing_token,
    touch_app_heartbeat,
    uninstall_browser_bridge,
)
from core.history_store import HistoryStore
from core.later_store import LaterStore
from core.package_manager import PackageActionWorker, PackageStatusWorker
from core.updater import (
    ReleaseInfo,
    UpdateCheckWorker,
    UpdateDownloadWorker,
    compare_versions,
    discard_staged_update,
    launch_applier,
    read_current_version,
)
from core.optional_engines import (
    apkeep_available,
    is_app_store_url,
    is_spotify_url,
    spotdl_available,
)
from core.search import SEARCH_SERVICES, SearchWorker
from core.sound_events import (
    DEFAULT_SOUND_THEME,
    DEFAULT_VOLUME,
    SOUND_EVENTS,
    SOUND_THEMES,
    SoundEventPlayer,
    normalize_sound_theme,
)
from core.downloader import (
    BROWSERS,
    PRESETS,
    DownloadWorker,
    audio_language_name,
    subtitle_language_name,
    InvalidCookieText,
    PreviewWorker,
    cookie_text_to_netscape,
    ejs_package_available,
    human_bytes,
    human_seconds,
    estimate_selected_media_size,
    normalize_cookie_domain,
    service_identity,
    url_domain,
    javascript_runtime_options,
    resolve_javascript_runtime,
    yt_dlp,
)
from ui.i18n import LANGUAGES, tr, translate_known
from ui.native_blur import disable_native_blur, enable_native_blur
from ui.theme import THEMES, YOUTUBE, Theme, build_message_box_stylesheet, build_stylesheet, theme_from_name
from ui.widgets import (
    AuroraSurface,
    EmptyStateGraphic,
    GlassCard,
    QuickStatPill,
    ResponsiveLabel,
    SpeedWaveWidget,
    TitleBar,
    Toast,
    make_line_icon,
)

APP_NAME = "LeonDL"
APP_VERSION = "2.6.3"

AUTH_CHOICES = {
    "none": ("بدون کوکی", "No cookies"),
    "browser": ("خواندن مستقیم از مرورگر", "Read directly from browser"),
    "extension": ("کوکی دریافت‌شده از افزونه Chrome", "Cookies received from Chrome extension"),
    "file": ("انتخاب فایل cookies.txt", "Choose cookies.txt file"),
    "manual": ("ورود دستی اطلاعات کوکی", "Paste cookie data manually"),
}

RUNTIME_CHOICES = {
    "auto": ("خودکار (Deno پیشنهادی)", "Automatic (Deno recommended)"),
    "deno": ("Deno", "Deno"),
    "node": ("Node.js", "Node.js"),
    "quickjs": ("QuickJS", "QuickJS"),
}

SOUND_EVENT_CHOICES = {
    "download_complete": ("پایان دانلود", "Download complete"),
    "queue_complete": ("پایان کل صف", "Queue complete"),
    "error": ("خطا", "Error"),
    "warning": ("هشدار", "Warning"),
    "cancelled": ("لغو دانلود", "Download cancelled"),
    "notification": ("اعلان افزونه و رویدادها", "Extension and app notification"),
}

SOUND_THEME_CHOICES = {
    "gentle": ("ملایم و دلنشین (CC0)", "Gentle & pleasant (CC0)"),
    "system": ("صدای سیستم (قدیمی)", "System sounds (legacy)"),
}


def fa_digits(value: object) -> str:
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
CONFIG_DIR = Path.home() / ".yt_dlp_liquid"
CONFIG_FILE = CONFIG_DIR / "settings.json"


class ThumbnailLoader(QThread):
    loaded = Signal(QByteArray)
    failed = Signal()

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url

    def run(self) -> None:
        try:
            parsed = urlparse(self.url)
            referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else "https://www.youtube.com/"
            request = Request(
                self.url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "Referer": referer,
                },
            )
            with urlopen(request, timeout=18) as response:
                data = response.read(8 * 1024 * 1024)
            self.loaded.emit(QByteArray(data))
        except Exception:
            self.failed.emit()


def soft_wrap_text(value: object, chunk: int = 38) -> str:
    """Insert invisible break opportunities into long URL/error tokens."""
    text = str(value or "")
    result: list[str] = []
    token_length = 0
    break_chars = set("/\\?&=:_-.#%")
    for char in text:
        result.append(char)
        if char.isspace():
            token_length = 0
            continue
        token_length += 1
        if char in break_chars or token_length >= chunk:
            result.append("​")
            token_length = 0
    return "".join(result)


class PreviewItemCard(QFrame):
    """Compact, wrapping preview row used by the batch preview list."""

    def __init__(self, index: int, url: str, language: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self.url = url
        self.language = "en" if language == "en" else "fa"
        self.setProperty("previewItem", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(0)
        self.setMinimumHeight(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 11, 11, 11)
        layout.setSpacing(8)

        self.image = QLabel(tr(self.language, "پیش‌نمایش"))
        self.image.setObjectName("previewThumb")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(150, 86)
        self.image.setToolTip(url)

        body = QVBoxLayout()
        body.setSpacing(5)
        body.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.index_badge = QLabel(f"#{index + 1}")
        self.index_badge.setObjectName("previewIndexBadge")
        self.index_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.service = QLabel(tr(self.language, "سرویس نامشخص"))
        self.service.setObjectName("serviceBadgeMuted")
        self.service.setMaximumWidth(150)
        self.service.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.status = QLabel(tr(self.language, "در انتظار بررسی"))
        self.status.setObjectName("previewStatus")
        self.status.setProperty("previewState", "pending")
        self.status.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        top.addWidget(self.index_badge)
        top.addWidget(self.service)
        top.addStretch(1)
        top.addWidget(self.status)

        self.title = ResponsiveLabel(soft_wrap_text(url))
        self.title.setObjectName("previewItemTitle")
        self.title.setToolTip(url)
        self.title.setMaximumHeight(54)
        self.meta = ResponsiveLabel(tr(self.language, "در انتظار دریافت اطلاعات لینک…"))
        self.meta.setObjectName("previewItemMeta")
        self.meta.setProperty("muted", True)
        self.meta.setMaximumHeight(50)
        self.meta.setToolTip(url)
        self.audio = ResponsiveLabel("")
        self.audio.setObjectName("previewItemAudio")
        self.audio.setProperty("muted", True)
        self.audio.setMaximumHeight(48)
        self.audio.hide()
        self.subtitles = ResponsiveLabel("")
        self.subtitles.setObjectName("previewItemSubtitles")
        self.subtitles.setProperty("muted", True)
        self.subtitles.setMaximumHeight(52)
        self.subtitles.hide()
        self.size = ResponsiveLabel("")
        self.size.setObjectName("previewItemSize")
        self.size.setProperty("sizeConfidence", "unknown")
        self.size.setMaximumHeight(48)
        self.size.hide()

        body.addLayout(top)
        body.addWidget(self.title)
        body.addWidget(self.meta)
        body.addWidget(self.audio)
        body.addWidget(self.subtitles)
        body.addWidget(self.size)
        layout.addWidget(self.image, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body, 1)

    def set_state(self, state: str, text: str) -> None:
        self.status.setProperty("previewState", state)
        self.status.setText(text)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.update()


class SearchResultCard(QFrame):
    download_requested = Signal(str)
    add_requested = Signal(str)
    later_requested = Signal(str)

    def __init__(self, result: dict[str, Any], language: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = dict(result)
        self.language = "en" if language == "en" else "fa"
        self.url = str(result.get("url") or "")
        self.setObjectName("searchResultCard")
        self.setProperty("searchResult", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumHeight(148)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(11, 11, 11, 11)
        layout.setSpacing(8)

        self.select_check = QCheckBox()
        self.select_check.setChecked(False)
        self.select_check.setToolTip("Select" if self.language == "en" else "انتخاب")
        layout.addWidget(self.select_check, 0, Qt.AlignmentFlag.AlignTop)

        self.image = QLabel("♪" if result.get("service_key") == "soundcloud" else "▶")
        self.image.setObjectName("searchThumb")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(156, 88)
        layout.addWidget(self.image, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(6)
        title = ResponsiveLabel(soft_wrap_text(result.get("title") or ("Untitled" if self.language == "en" else "بدون عنوان")))
        title.setObjectName("searchResultTitle")
        title.setToolTip(str(result.get("title") or ""))
        title.setMaximumHeight(52)
        meta_bits = [str(result.get("uploader") or "—")]
        duration = human_seconds(result.get("duration"))
        if duration and duration != "—":
            meta_bits.append(duration)
        entry_type = str(result.get("entry_type") or "").strip()
        if entry_type and entry_type not in {"url", "video"}:
            meta_bits.append(entry_type)
        meta = ResponsiveLabel("  •  ".join(meta_bits))
        meta.setObjectName("muted")
        service = QLabel(str(result.get("service") or ""))
        service.setObjectName("serviceBadgeMuted")
        service.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        body.addWidget(title)
        body.addWidget(meta)
        body.addWidget(service, 0, Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight)
        layout.addLayout(body, 1)

        actions = QVBoxLayout()
        actions.setSpacing(7)
        download_button = QPushButton("Download" if self.language == "en" else "دانلود")
        download_button.setProperty("primary", True)
        download_button.clicked.connect(lambda: self.download_requested.emit(self.url))
        add_button = QPushButton("Add to download" if self.language == "en" else "افزودن به دانلودها")
        add_button.clicked.connect(lambda: self.add_requested.emit(self.url))
        later_button = QPushButton("Queue" if self.language == "en" else "صف")
        later_button.clicked.connect(lambda: self.later_requested.emit(self.url))
        actions.addWidget(download_button)
        actions.addWidget(add_button)
        actions.addWidget(later_button)
        actions.addStretch(1)
        layout.addLayout(actions)

    def is_selected(self) -> bool:
        return self.select_check.isChecked()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1380, 900)
        self.setMinimumSize(1060, 720)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.language = self._read_initial_language()
        QApplication.instance().setLayoutDirection(self._layout_direction())
        self.setLayoutDirection(self._layout_direction())

        self.theme: Theme = YOUTUBE
        self.worker: DownloadWorker | None = None
        self.preview_worker: PreviewWorker | None = None
        self.thumbnail_worker: ThumbnailLoader | None = None
        self.thumbnail_workers: list[ThumbnailLoader] = []
        self.preview_cards: list[PreviewItemCard] = []
        self.preview_results: list[dict[str, Any]] = []
        self.preview_success_count = 0
        self.preview_failure_count = 0
        self.preview_generation = 0
        self.detected_audio_languages: dict[str, dict[str, Any]] = {}
        self.detected_subtitle_languages: dict[str, dict[str, Any]] = {}
        self.queue_items: list[QListWidgetItem] = []
        self.current_queue_index = -1
        self.queue_metadata_worker: PreviewWorker | None = None
        self.queue_metadata_generation = 0
        self._initialized_pages: set[str] = {"download"}
        self._last_output_dir = str(Path.home() / "Downloads")
        self._intro_played = False
        self._intro_animation: QPropertyAnimation | None = None
        self._close_when_worker_stops = False
        self._download_cancel_requested = False
        self._forced_close_scheduled = False
        self.last_error_text = ""
        self._window_state_transition = False
        self._pseudo_maximized = False
        self._restore_geometry = None
        self.auth_store = AuthProfileStore(CONFIG_DIR)
        self.history_store = HistoryStore(CONFIG_DIR)
        self.later_store = LaterStore(CONFIG_DIR)
        self.search_worker: SearchWorker | None = None
        self.search_results: list[dict[str, Any]] = []
        self.search_cards: list[SearchResultCard] = []
        self.search_thumbnail_workers: list[ThumbnailLoader] = []
        self.later_metadata_workers: list[PreviewWorker] = []
        self._later_metadata_active_keys: set[tuple[str, str, str]] = set()
        self._later_metadata_cache: dict[str, dict[str, Any]] = {}
        self.package_status_worker: PackageStatusWorker | None = None
        self.package_action_worker: PackageActionWorker | None = None
        self.update_check_worker: UpdateCheckWorker | None = None
        self.update_download_worker: UpdateDownloadWorker | None = None
        self.latest_release: ReleaseInfo | None = None
        self.pending_update_staging: Path | None = None
        self._update_toast_shown = False
        self._download_history_buffer: dict[str, dict[str, Any]] = {}
        self._active_auth_domains: list[str] = []
        self._active_auth_method = "none"
        self._active_auth_auto_used = False
        self._active_auth_pending = False
        self._auth_override_requested = False
        self._browser_preview_pending = False
        self._browser_auth_validation_domains: set[str] = set()
        self.sound_player = SoundEventPlayer(self)
        self._download_batch_total = 0
        self._download_completed_sound_count = 0

        # Window-state work is intentionally deferred. Mutating a splitter,
        # Acrylic state, and a translucent native window synchronously inside
        # resizeEvent can crash Qt/DWM on some Windows graphics drivers.
        self._responsive_layout_timer = QTimer(self)
        self._responsive_layout_timer.setSingleShot(True)
        self._responsive_layout_timer.timeout.connect(self._apply_responsive_layout)
        self._native_blur_timer = QTimer(self)
        self._native_blur_timer.setSingleShot(True)
        self._native_blur_timer.timeout.connect(self._enable_blur_if_safe)
        self._window_state_timer = QTimer(self)
        self._window_state_timer.setSingleShot(True)
        self._window_state_timer.timeout.connect(self._finish_window_state_transition)

        self._build_ui()
        self._install_wheel_scroll_guard()
        self._load_settings()
        self._auth_override_requested = False
        self._set_busy(False)
        QTimer.singleShot(650, self._refresh_saved_auth_status)

        self.browser_bridge_poll_timer = QTimer(self)
        self.browser_bridge_poll_timer.setInterval(700)
        self.browser_bridge_poll_timer.timeout.connect(self._poll_browser_bridge_requests)
        self.browser_bridge_poll_timer.start()
        self.browser_bridge_heartbeat_timer = QTimer(self)
        self.browser_bridge_heartbeat_timer.setInterval(2000)
        self.browser_bridge_heartbeat_timer.timeout.connect(touch_app_heartbeat)
        self.browser_bridge_heartbeat_timer.start()
        QTimer.singleShot(0, touch_app_heartbeat)
        QTimer.singleShot(120, self._poll_browser_bridge_requests)
        if getattr(sys, "frozen", False):
            QTimer.singleShot(4500, self._silent_update_check)

        if yt_dlp is None:
            QTimer.singleShot(350, self._show_missing_dependency)

    @staticmethod
    def _read_initial_language() -> str:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "fa"
        return "en" if str(data.get("language", "fa")).lower() == "en" else "fa"

    def _layout_direction(self) -> Qt.LayoutDirection:
        return Qt.LayoutDirection.LeftToRight if self.language == "en" else Qt.LayoutDirection.RightToLeft

    def _t(self, text: str) -> str:
        return tr(self.language, text)

    def _digits(self, value: object) -> str:
        return str(value) if self.language == "en" else fa_digits(value)

    def _localized_error(self, message: str) -> str:
        clean = str(message or "").replace("\x00", "").strip()
        if not clean:
            clean = (
                "An unknown error occurred. Open the Log page for details."
                if self.language == "en"
                else "یک خطای نامشخص رخ داد. برای جزئیات صفحه گزارش را باز کنید."
            )
        return self._t(clean) if self.language == "en" else clean

    def _choice_label(self, choices: dict[str, tuple[str, str]], key: str) -> str:
        fa, en = choices[key]
        return en if self.language == "en" else fa

    @staticmethod
    def _combo_data(combo: QComboBox, default: str = "") -> str:
        value = combo.currentData()
        return str(value) if value is not None else default

    def _main_page_index(self) -> int:
        return self.main_pages.currentIndex() if hasattr(self, "main_pages") else 0

    def _set_main_page(self, index: int) -> None:
        if not hasattr(self, "main_pages"):
            return
        index = max(0, min(self.main_pages.count() - 1, int(index)))
        self.main_pages.setCurrentIndex(index)
        self._sync_main_nav(index)

    def _sync_main_nav(self, index: int) -> None:
        if not hasattr(self, "main_nav"):
            return
        if self.main_nav.currentRow() == index:
            return
        self.main_nav.blockSignals(True)
        self.main_nav.setCurrentRow(index)
        self.main_nav.blockSignals(False)

    def _set_main_page_by_key(self, key: str) -> None:
        index = getattr(self, "page_indexes", {}).get(str(key), 0)
        self._set_main_page(index)

    def _on_main_page_changed(self, index: int) -> None:
        """Run expensive page-specific checks only when the page is first opened."""
        self._sync_main_nav(index)
        item = self.main_nav.item(index) if hasattr(self, "main_nav") else None
        key = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        if not key or key in self._initialized_pages:
            return
        self._initialized_pages.add(key)
        if key == "later":
            self._refresh_later_table()
            QTimer.singleShot(80, self._refresh_missing_later_metadata)
        elif key == "history":
            self._refresh_history_table()
        elif key == "packages":
            self._refresh_package_status()
        elif key == "browser":
            self._refresh_browser_bridge_status()

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        root_layout = QVBoxLayout(root)
        self.root_layout = root_layout
        root_layout.setContentsMargins(9, 9, 9, 9)
        self.setCentralWidget(root)

        self.surface = AuroraSurface()
        self.surface.setObjectName("windowSurface")
        surface_layout = QVBoxLayout(self.surface)
        surface_layout.setContentsMargins(14, 6, 14, 14)
        surface_layout.setSpacing(9)
        root_layout.addWidget(self.surface)

        self.title_bar = TitleBar(self, self.language)
        self.title_bar.theme_requested.connect(self._show_theme_menu)
        self.title_bar.language_requested.connect(self._show_language_menu)
        surface_layout.addWidget(self.title_bar)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(9)

        nav_card = GlassCard()
        nav_card.setObjectName("sideNavCard")
        nav_card.setMinimumWidth(202)
        nav_card.setMaximumWidth(232)
        nav_card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(11, 12, 11, 11)
        nav_layout.setSpacing(8)
        nav_title = QLabel(self._t("بخش‌های برنامه"))
        nav_title.setObjectName("sideNavTitle")
        nav_layout.addWidget(nav_title)
        self.main_nav = QListWidget()
        self.main_nav.setObjectName("sideNavList")
        self.main_nav.setFrameShape(QFrame.Shape.NoFrame)
        self.main_nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.main_nav.setIconSize(QSize(18, 18))
        self.main_nav.setSpacing(2)
        self.main_nav.setUniformItemSizes(False)
        self.main_nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nav_layout.addWidget(self.main_nav, 1)

        self.main_pages = QStackedWidget()

        download_page = QWidget()
        download_layout = QVBoxLayout(download_page)
        download_layout.setContentsMargins(0, 0, 0, 0)
        download_layout.setSpacing(9)
        download_layout.addWidget(self._build_command_bar())

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setHandleWidth(10)
        self.main_splitter.addWidget(self._build_status_column())
        self.main_splitter.addWidget(self._build_links_column())
        self.main_splitter.setStretchFactor(0, 5)
        self.main_splitter.setStretchFactor(1, 6)
        self.main_splitter.setSizes([590, 700])
        download_layout.addWidget(self.main_splitter, 1)

        pages = [
            ("download", self._t("دانلود"), make_line_icon("download", self.theme.text, accent=self.theme.accent), download_page),
            ("search", self._t("جست‌وجو"), make_line_icon("search", self.theme.text, accent=self.theme.accent), self._build_search_page()),
            ("later", self._t("صف"), make_line_icon("later", self.theme.text, accent=self.theme.accent), self._build_later_page()),
            ("history", self._t("تاریخچه"), make_line_icon("history", self.theme.text, accent=self.theme.accent), self._build_history_page()),
            ("log", self._t("گزارش"), make_line_icon("log", self.theme.text, accent=self.theme.accent), self._build_log_page()),
            ("settings", self._t("تنظیمات"), make_line_icon("settings", self.theme.text, accent=self.theme.accent), self._build_settings_page()),
            ("browser", self._t("افزونه Chrome"), make_line_icon("link", self.theme.text, accent=self.theme.accent), self._build_browser_bridge_page()),
            ("packages", self._t("مدیریت پکیج‌ها"), make_line_icon("package", self.theme.text, accent=self.theme.accent), self._build_packages_page()),
        ]
        self.page_indexes = {}
        for index, (key, label, icon, widget) in enumerate(pages):
            self.page_indexes[key] = index
            item = QListWidgetItem(icon, label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.main_nav.addItem(item)
            self.main_pages.addWidget(widget)

        self.main_nav.currentRowChanged.connect(self.main_pages.setCurrentIndex)
        self.main_pages.currentChanged.connect(self._on_main_page_changed)
        self.main_nav.setCurrentRow(0)

        content_row.addWidget(nav_card)
        content_row.addWidget(self.main_pages, 1)
        surface_layout.addLayout(content_row, 1)

        self.toast = Toast(self.surface)
        self._refresh_action_icons()
        QTimer.singleShot(0, self._update_quick_stats)

    def _build_command_bar(self) -> QWidget:
        """Compact, fixed-height command deck that never scrolls away."""
        card = GlassCard(hoverable=False)
        card.setObjectName("commandBar")
        card.setMinimumHeight(70)
        card.setMaximumHeight(90)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(8)

        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.hero_links_stat = QuickStatPill(self._t("لینک‌های دانلود"), self._digits(0))
        self.hero_output_stat = QuickStatPill(self._t("پوشهٔ ذخیره"), "Downloads")
        for stat in (self.hero_links_stat, self.hero_output_stat):
            stat.setMinimumWidth(82)
            stat.setMaximumHeight(54)

        quality_picker = QFrame()
        quality_picker.setObjectName("quickPresetPicker")
        quality_picker.setMinimumWidth(145)
        quality_picker.setMaximumWidth(230)
        quality_picker.setMaximumHeight(58)
        quality_picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        quality_layout = QVBoxLayout(quality_picker)
        quality_layout.setContentsMargins(10, 5, 10, 6)
        quality_layout.setSpacing(2)
        quality_label = QLabel(self._t("کیفیت / فرمت"))
        quality_label.setObjectName("quickStatTitle")
        self.hero_preset_combo = QComboBox()
        self.hero_preset_combo.setObjectName("heroPresetCombo")
        for key, preset in PRESETS.items():
            self.hero_preset_combo.addItem(preset.label(self.language), key)
        self._compact_combo(self.hero_preset_combo, 13)
        self.hero_preset_combo.currentIndexChanged.connect(self._hero_preset_changed)
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.hero_preset_combo)

        stats.addWidget(self.hero_links_stat)
        stats.addWidget(quality_picker, 2)
        stats.addWidget(self.hero_output_stat)
        layout.addLayout(stats, 1)

        self.preview_button = QPushButton(self._t("پیش‌نمایش همهٔ لینک‌ها"))
        self.preview_button.clicked.connect(self._preview_all_urls)
        self.preview_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_button.setProperty("commandAction", True)

        self.start_button = QPushButton(self._t("شروع دانلود"))
        self.start_button.setProperty("primary", True)
        self.start_button.setProperty("commandPrimary", True)
        self.start_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_button.clicked.connect(self._start_download)

        self.later_button = QPushButton(self._t("صف"))
        self.later_button.setProperty("commandAction", True)
        self.later_button.clicked.connect(self._add_current_to_later)

        self.cancel_button = QPushButton(self._t("لغو"))
        self.cancel_button.setProperty("danger", True)
        self.cancel_button.setProperty("commandAction", True)
        self.cancel_button.clicked.connect(self._cancel_download)

        self.open_folder_button = QPushButton(self._t("بازکردن پوشه"))
        self.open_folder_button.clicked.connect(self._open_output_folder)
        self.open_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_folder_button.setProperty("commandAction", True)

        for button in (self.preview_button, self.start_button, self.later_button, self.cancel_button, self.open_folder_button):
            button.setMinimumHeight(38)

        layout.addWidget(self.preview_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.later_button)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.open_folder_button)
        return card

    def _build_links_column(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("controlsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        host = QWidget()
        host.setMinimumWidth(0)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(9)

        links_card = GlassCard()
        links_card.setObjectName("sectionCard")
        links_layout = QVBoxLayout(links_card)
        links_layout.setContentsMargins(14, 12, 14, 12)
        links_layout.setSpacing(7)
        links_layout.addWidget(self._title(self._t("لینک‌های دانلود")))
        links_layout.addWidget(self._muted(self._t("هر لینک در یک خط؛ لینک‌ها را می‌توانی مستقیماً داخل پنجره رها کنی.")))
        self.urls_edit = QPlainTextEdit()
        self.urls_edit.setPlaceholderText(
            "https://www.youtube.com/watch?v=...\n"
            "https://www.instagram.com/reel/...\n"
            "https://www.tiktok.com/@user/video/..."
        )
        self.urls_edit.setMinimumHeight(190)
        self.urls_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        url_text_option = self.urls_edit.document().defaultTextOption()
        url_text_option.setAlignment(Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight)
        url_text_option.setTextDirection(Qt.LayoutDirection.LeftToRight)
        self.urls_edit.document().setDefaultTextOption(url_text_option)
        self.urls_edit.textChanged.connect(self._update_quick_stats)
        self.urls_edit.textChanged.connect(self._refresh_saved_auth_status)
        links_layout.addWidget(self.urls_edit)

        links_actions = QHBoxLayout()
        links_actions.setSpacing(6)
        paste_button = QPushButton(self._t("چسباندن"))
        paste_button.clicked.connect(self._paste_urls)
        clear_button = QPushButton(self._t("پاک‌کردن"))
        clear_button.clicked.connect(self.urls_edit.clear)
        self.preview_inline_button = QPushButton(self._t("پیش‌نمایش همهٔ لینک‌ها"))
        self.preview_inline_button.setProperty("accentAction", True)
        self.preview_inline_button.clicked.connect(self._preview_all_urls)
        links_actions.addWidget(clear_button)
        links_actions.addWidget(paste_button)
        links_actions.addStretch(1)
        links_actions.addWidget(self.preview_inline_button)
        links_layout.addLayout(links_actions)
        layout.addWidget(links_card)

        summary_card = GlassCard()
        summary_card.setObjectName("sectionCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        summary_layout.setSpacing(8)
        summary_layout.addWidget(self._title(self._t("تنظیمات فعال")))
        summary_layout.addWidget(self._muted(self._t("کیفیت، محل ذخیره، کوکی‌ها و ظاهر برنامه از تب تنظیمات مدیریت می‌شوند.")))
        open_settings = QPushButton(self._t("بازکردن تنظیمات"))
        open_settings.setProperty("primary", True)
        open_settings.clicked.connect(lambda: self._set_main_page_by_key("settings"))
        summary_layout.addWidget(open_settings, 0, Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight)
        layout.addWidget(summary_card)
        layout.addStretch(1)
        scroll.setWidget(host)
        return scroll

    def _new_settings_scroll(self) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(5, 7, 5, 7)
        layout.setSpacing(9)
        scroll.setWidget(host)
        return scroll, host, layout

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")
        self.settings_tabs.addTab(self._build_general_settings_tab(), self._t("دانلود عمومی"))
        self.settings_tabs.addTab(self._build_storage_settings_tab(), self._t("محل ذخیره"))
        self.settings_tabs.addTab(self._build_cookie_settings_tab(), self._t("کوکی و ورود"))
        self.settings_tabs.addTab(self._build_appearance_settings_tab(), self._t("زبان و ظاهر"))
        self.settings_tabs.addTab(self._build_update_settings_tab(), self._t("بروزرسانی"))
        layout.addWidget(self.settings_tabs)
        return page

    def _build_update_settings_tab(self) -> QWidget:
        scroll, _host, layout = self._new_settings_scroll()
        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 13, 15, 13)
        card_layout.setSpacing(8)
        card_layout.addWidget(self._title(self._t("بروزرسانی از GitHub")))
        card_layout.addWidget(
            self._muted(
                self._t(
                    "بروزرسانی فقط برای نسخهٔ EXE در دسترس است؛ برنامه هنگام شروع به‌صورت بی‌صدا آخرین نسخه را بررسی می‌کند و دانلود از ریلیز رسمی GitHub انجام می‌شود."
                )
            )
        )

        current = read_current_version()
        self.update_status_label = ResponsiveLabel(
            self._t("نسخه فعلی") + f": {current}\n" + self._t("آخرین نسخه") + ": —"
        )
        self.update_status_label.setObjectName("muted")
        self.update_status_label.setWordWrap(True)
        card_layout.addWidget(self.update_status_label)

        self.update_progress = QProgressBar()
        self.update_progress.setRange(0, 100)
        self.update_progress.setValue(0)
        self.update_progress.setTextVisible(True)
        self.update_progress.setVisible(False)
        self.update_progress.setObjectName("updateProgress")
        card_layout.addWidget(self.update_progress)

        self.update_check_button = QPushButton(self._t("بررسی بروزرسانی"))
        self.update_check_button.clicked.connect(lambda: self._run_update_check(manual=True))
        self.update_install_button = QPushButton(self._t("دانلود و نصب"))
        self.update_install_button.setEnabled(False)
        self.update_install_button.clicked.connect(self._run_update_download)
        buttons_row = QHBoxLayout()
        buttons_row.setSpacing(10)
        buttons_row.addWidget(self.update_check_button)
        buttons_row.addWidget(self.update_install_button)
        card_layout.addLayout(buttons_row)

        if not getattr(sys, "frozen", False):
            card_layout.addWidget(
                self._muted(
                    self._t("در حالت اجرا از سورس فقط بررسی ممکن است؛ برای به‌روزرسانی از git pull استفاده کن.")
                )
            )

        layout.addWidget(card)
        return scroll

    def _silent_update_check(self) -> None:
        if self.latest_release is None:
            self._run_update_check(manual=False)

    def _run_update_check(self, manual: bool) -> None:
        if self.update_check_worker and self.update_check_worker.isRunning():
            return
        if self.update_download_worker and self.update_download_worker.isRunning():
            return
        self.latest_release = None
        self._update_status(self._t("در حال بررسی…"))
        self.update_check_button.setEnabled(False)
        worker = UpdateCheckWorker()
        worker.checked.connect(lambda ok, release, error: self._update_check_finished(ok, release, error, manual))
        self.update_check_worker = worker
        worker.start()

    def _update_check_finished(self, ok: bool, release, error: str, manual: bool) -> None:
        self.update_check_worker = None
        self.update_check_button.setEnabled(True)
        current = read_current_version()
        if ok and release is not None:
            self.latest_release = release
            newer = compare_versions(release.version, current) > 0
            if newer:
                self._update_status(self._t("نسخه جدید موجود است") + f" — v{release.version}")
                self.update_install_button.setEnabled(True)
                self.update_install_button.setText(self._t("دانلود و نصب") + f" v{release.version}")
                if not manual and not self._update_toast_shown:
                    self._update_toast_shown = True
                    self.toast.show_message(
                        self._t("نسخه جدید موجود است") + f" v{release.version} — " + self._t("تنظیمات › بروزرسانی")
                    )
            else:
                self.latest_release = None
                self.update_install_button.setEnabled(False)
                self.update_install_button.setText(self._t("دانلود و نصب"))
                self._update_status(self._t("برنامه بروز است") + f" — v{current}")
        else:
            self.update_install_button.setEnabled(False)
            self.update_install_button.setText(self._t("دانلود و نصب"))
            self._update_status(self._t("بررسی ناموفق؛ اتصال خود را بررسی کن") + (f"\n{error}" if error else ""))

    def _run_update_download(self) -> None:
        if self.update_download_worker and self.update_download_worker.isRunning():
            return
        if self.latest_release is None:
            return
        if not getattr(sys, "frozen", False):
            self.toast.show_message(self._t("در حالت سورس، آپدیت با git pull انجام می‌شود"))
            return
        self.update_check_button.setEnabled(False)
        self.update_install_button.setEnabled(False)
        self.update_progress.setVisible(True)
        self.update_progress.setValue(0)
        self._update_status(self._t("در حال دانلود…"))
        worker = UpdateDownloadWorker(self.latest_release)
        worker.progress.connect(self._update_download_progress)
        worker.staged.connect(self._update_download_finished)
        self.update_download_worker = worker
        worker.start()

    def _update_download_progress(self, received: int, total: int) -> None:
        percent = min(100, received * 100 // total) if total else 0
        self.update_progress.setValue(percent)
        self._update_status(self._t("در حال دانلود") + f"  {percent}٪")

    def _update_download_finished(self, ok: bool, message: str, staging) -> None:
        self.update_download_worker = None
        if not ok:
            self.update_progress.setVisible(False)
            self.update_check_button.setEnabled(True)
            self.update_install_button.setEnabled(True)
            self.toast.show_message(self._t("دانلود ناموفق بود"))
            self._update_status(message)
            return
        self.pending_update_staging = staging
        answer = QMessageBox.question(
            self,
            self._t("بروزرسانی"),
            self._t("دانلود کامل شد؛ خروج و اعمال آپدیت؟"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            if staging is not None:
                discard_staged_update(staging)
            self.pending_update_staging = None
            self.update_progress.setVisible(False)
            self.update_install_button.setEnabled(True)
            self._update_status(self._t("دانلود لغو شد"))
            return
        try:
            launch_applier(staging)
        except Exception as exc:
            self.update_progress.setVisible(False)
            self.update_install_button.setEnabled(True)
            self.toast.show_message(self._t("اعمال آپدیت ناموفق بود") + f": {exc}")
            return
        self.toast.show_message(self._t("در حال اعمال آپدیت… برنامه پس از خروج جایگزین می‌شود"))
        QTimer.singleShot(600, self.close)

    def _update_status(self, text: str) -> None:
        if hasattr(self, "update_status_label"):
            self.update_status_label.setText(text)

    def _build_general_settings_tab(self) -> QWidget:
        scroll, _host, layout = self._new_settings_scroll()
        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 13, 15, 13)
        card_layout.setSpacing(8)
        card_layout.addWidget(self._title(self._t("تنظیمات عمومی دانلود")))
        card_layout.addWidget(self._muted(self._t("فرمت خروجی، زیرنویس، زبان صدا و پردازش فایل را از اینجا تعیین کن.")))

        self.preset_combo = QComboBox()
        for key, preset in PRESETS.items():
            self.preset_combo.addItem(preset.label(self.language), key)
        self._compact_combo(self.preset_combo, 24)
        self.preset_combo.currentIndexChanged.connect(self._recalculate_preview_sizes)
        self.preset_combo.currentIndexChanged.connect(self._sync_hero_preset)
        self.preset_combo.currentIndexChanged.connect(self._update_quick_stats)
        card_layout.addWidget(self._field_widget(self._t("کیفیت / فرمت"), self.preset_combo))

        self.playlist_check = QCheckBox(self._t("دانلود پلی‌لیست"))
        self.playlist_check.setChecked(True)
        self.metadata_check = QCheckBox(self._t("ثبت متادیتا"))
        self.metadata_check.setChecked(True)
        self.thumbnail_check = QCheckBox(self._t("الصاق تصویر بندانگشتی"))
        self.subtitle_check = QCheckBox(self._t("دریافت زیرنویس"))
        self.subtitle_check.toggled.connect(self._toggle_subtitle_controls)
        self.auto_subtitle_check = QCheckBox(self._t("زیرنویس خودکار"))
        self.auto_subtitle_check.setChecked(True)
        self.mark_watched_check = QCheckBox(self._t("علامت‌گذاری ویدئوهای YouTube به‌عنوان دیده‌شده"))
        self.mark_watched_check.setChecked(False)
        self.mark_watched_check.setToolTip(self._t("در پیش‌نمایش اصلی و دانلود از yt-dlp درخواست می‌شود و به کوکی حساب واردشده نیاز دارد؛ YouTube ممکن است نتیجه را فوری یا قابل‌اعتماد ثبت نکند."))
        checks = QGridLayout()
        checks.setHorizontalSpacing(18)
        checks.setVerticalSpacing(10)
        checks.addWidget(self.playlist_check, 0, 0)
        checks.addWidget(self.metadata_check, 0, 1)
        checks.addWidget(self.thumbnail_check, 1, 0)
        checks.addWidget(self.subtitle_check, 1, 1)
        checks.addWidget(self.auto_subtitle_check, 2, 0)
        checks.addWidget(self.mark_watched_check, 2, 1)
        card_layout.addLayout(checks)
        mark_watched_note = self._muted(self._t("فقط برای YouTube است؛ این درخواست هنگام پیش‌نمایش اصلی و دانلود ارسال می‌شود، اما ثبت در تاریخچهٔ YouTube تضمین‌شده نیست."))
        mark_watched_note.setWordWrap(True)
        card_layout.addWidget(mark_watched_note)

        self.audio_language_combo = QComboBox()
        self._compact_combo(self.audio_language_combo, 26)
        self._reset_audio_language_combo()
        self.audio_language_combo.currentIndexChanged.connect(self._recalculate_preview_sizes)
        self.subtitle_language_combo = QComboBox()
        self._compact_combo(self.subtitle_language_combo, 26)
        self._reset_subtitle_language_combo()
        self.subtitle_language_combo.currentIndexChanged.connect(self._on_subtitle_language_changed)
        self.fragments_spin = QSpinBox()
        self.fragments_spin.setRange(1, 16)
        self.fragments_spin.setValue(4)
        advanced = QGridLayout()
        advanced.setHorizontalSpacing(16)
        advanced.setVerticalSpacing(12)
        advanced.addWidget(self._field_widget(self._t("زبان صدای ویدئو"), self.audio_language_combo), 0, 0, 1, 2)
        advanced.addWidget(self._field_widget(self._t("زبان زیرنویس"), self.subtitle_language_combo), 1, 0)
        advanced.addWidget(self._field_widget(self._t("دانلود هم‌زمان قطعه‌ها"), self.fragments_spin), 1, 1)
        advanced.setColumnStretch(0, 1)
        advanced.setColumnStretch(1, 1)
        card_layout.addLayout(advanced)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _build_storage_settings_tab(self) -> QWidget:
        scroll, _host, layout = self._new_settings_scroll()
        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 13, 15, 13)
        card_layout.setSpacing(8)
        card_layout.addWidget(self._title(self._t("محل ذخیرهٔ دانلودها")))
        card_layout.addWidget(self._muted(self._t("پوشهٔ مادر و شیوهٔ دسته‌بندی فایل‌ها را مشخص کن.")))
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(str(Path.home() / "Downloads"))
        self.output_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.output_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.output_edit.textChanged.connect(self._update_quick_stats)
        choose_button = QPushButton(self._t("انتخاب پوشه"))
        choose_button.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(choose_button)
        card_layout.addWidget(self._muted(self._t("پوشهٔ ذخیره")))
        card_layout.addLayout(output_row)
        self.organize_service_check = QCheckBox(self._t("مرتب‌سازی خودکار بر اساس سرویس"))
        self.organize_service_check.setChecked(True)
        card_layout.addWidget(self.organize_service_check)
        card_layout.addWidget(self._muted(self._t("فایل‌ها داخل پوشهٔ مادر و سپس پوشهٔ سرویس ذخیره می‌شوند.")))
        open_button = QPushButton(self._t("بازکردن پوشه"))
        open_button.clicked.connect(self._open_output_folder)
        card_layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _build_cookie_settings_tab(self) -> QWidget:
        scroll, _host, layout = self._new_settings_scroll()
        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 13, 15, 13)
        card_layout.setSpacing(9)
        card_layout.addWidget(self._title(self._t("کوکی و احراز هویت")))
        card_layout.addWidget(self._muted(self._t("آخرین روش موفق هر سایت می‌تواند تا زمان معتبر بودن نشست به‌صورت خودکار استفاده شود.")))

        self.auth_combo = QComboBox()
        for key in AUTH_CHOICES:
            self.auth_combo.addItem(self._choice_label(AUTH_CHOICES, key), key)
        self._compact_combo(self.auth_combo, 24)
        self.auth_combo.currentIndexChanged.connect(self._toggle_auth_controls)
        self.auth_combo.activated.connect(self._request_auth_override)
        card_layout.addWidget(self._field_widget(self._t("روش احراز هویت"), self.auth_combo))

        self.auth_stack = QStackedWidget()
        no_cookie_page = QWidget()
        no_cookie_layout = QVBoxLayout(no_cookie_page)
        no_cookie_layout.setContentsMargins(0, 6, 0, 6)
        no_cookie_layout.addWidget(self._muted(self._t("برای لینک‌های عمومی استفاده می‌شود؛ در صورت خطای ربات، یکی از روش‌های دیگر را انتخاب کن.")))
        self.auth_stack.addWidget(no_cookie_page)

        browser_page = QWidget()
        browser_layout = QGridLayout(browser_page)
        browser_layout.setContentsMargins(0, 6, 0, 6)
        browser_layout.setHorizontalSpacing(14)
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(BROWSERS.keys())
        self.browser_combo.activated.connect(self._request_auth_override)
        self._compact_combo(self.browser_combo, 16)
        self.browser_profile_edit = QLineEdit()
        self.browser_profile_edit.setPlaceholderText(self._t("Default یا Profile 1"))
        self.browser_profile_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.browser_profile_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.browser_profile_edit.textEdited.connect(self._request_auth_override)
        browser_layout.addWidget(self._field_widget(self._t("مرورگر"), self.browser_combo), 0, 0)
        browser_layout.addWidget(self._field_widget(self._t("پروفایل مرورگر (اختیاری)"), self.browser_profile_edit), 0, 1)
        self.auth_stack.addWidget(browser_page)

        extension_page = QWidget()
        extension_layout = QVBoxLayout(extension_page)
        extension_layout.setContentsMargins(0, 6, 0, 6)
        extension_layout.setSpacing(8)
        extension_note = self._muted(self._t("این منبع از آخرین کوکی‌ای استفاده می‌کند که افزونه Chrome برای دامنهٔ لینک فعلی فرستاده است. در Popup افزونه باید Send site cookies فعال باشد."))
        extension_note.setWordWrap(True)
        extension_layout.addWidget(extension_note)
        self.extension_cookie_status = QLabel(self._t("برای بررسی این منبع، ابتدا لینک همان سایت را وارد کن."))
        self.extension_cookie_status.setObjectName("authProfileStatus")
        self.extension_cookie_status.setWordWrap(True)
        extension_layout.addWidget(self.extension_cookie_status)
        extension_actions = QHBoxLayout()
        refresh_extension_cookie_button = QPushButton(self._t("بررسی مجدد وضعیت کوکی افزونه"))
        refresh_extension_cookie_button.clicked.connect(self._refresh_saved_auth_status)
        open_extension_page_button = QPushButton(self._t("بازکردن صفحهٔ افزونه Chrome"))
        open_extension_page_button.clicked.connect(
            lambda: self._set_main_page(self.page_indexes.get("browser", 0)) if hasattr(self, "page_indexes") else None
        )
        extension_actions.addWidget(refresh_extension_cookie_button)
        extension_actions.addWidget(open_extension_page_button)
        extension_actions.addStretch(1)
        extension_layout.addLayout(extension_actions)
        self.auth_stack.addWidget(extension_page)

        file_page = QWidget()
        file_layout = QVBoxLayout(file_page)
        file_layout.setContentsMargins(0, 6, 0, 6)
        self.cookie_file_edit = QLineEdit()
        self.cookie_file_edit.setPlaceholderText(self._t("مسیر فایل cookies.txt با قالب Netscape"))
        self.cookie_file_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.cookie_file_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.cookie_file_edit.textEdited.connect(self._request_auth_override)
        file_row = QHBoxLayout()
        file_row.addWidget(self.cookie_file_edit, 1)
        cookie_file_button = QPushButton(self._t("انتخاب فایل"))
        cookie_file_button.clicked.connect(self._choose_cookie_file)
        file_row.addWidget(cookie_file_button)
        file_layout.addLayout(file_row)
        self.auth_stack.addWidget(file_page)

        manual_page = QWidget()
        manual_layout = QVBoxLayout(manual_page)
        manual_layout.setContentsMargins(0, 6, 0, 6)
        manual_layout.setSpacing(8)
        self.cookie_domain_edit = QLineEdit()
        self.cookie_domain_edit.setPlaceholderText(self._t("برای Cookie خام؛ مانند instagram.com"))
        self.cookie_domain_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.cookie_domain_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.cookie_domain_edit.textEdited.connect(self._request_auth_override)
        manual_layout.addWidget(self._field_widget(self._t("دامنهٔ کوکی دستی"), self.cookie_domain_edit))
        self.manual_cookie_edit = QPlainTextEdit()
        self.manual_cookie_edit.setObjectName("cookieText")
        self.manual_cookie_edit.setMinimumHeight(145)
        self.manual_cookie_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.manual_cookie_edit.textChanged.connect(self._request_auth_override)
        self.manual_cookie_edit.setPlaceholderText("Cookie: sessionid=...; csrftoken=...\n\n" + self._t("یا محتوای فایل Netscape / خروجی JSON کوکی‌ها"))
        manual_layout.addWidget(self.manual_cookie_edit)
        actions = QHBoxLayout()
        paste_cookie_button = QPushButton(self._t("چسباندن از کلیپ‌بورد"))
        paste_cookie_button.clicked.connect(self._paste_cookie_text)
        validate_cookie_button = QPushButton(self._t("بررسی قالب"))
        validate_cookie_button.clicked.connect(self._validate_manual_cookie)
        clear_cookie_button = QPushButton(self._t("پاک‌کردن"))
        clear_cookie_button.clicked.connect(self.manual_cookie_edit.clear)
        actions.addWidget(clear_cookie_button)
        actions.addWidget(validate_cookie_button)
        actions.addWidget(paste_cookie_button)
        actions.addStretch(1)
        manual_layout.addLayout(actions)
        self.auth_stack.addWidget(manual_page)
        card_layout.addWidget(self.auth_stack)

        memory_row = QHBoxLayout()
        self.remember_auth_check = QCheckBox(self._t("احراز هویت انتخاب‌شده را به خاطر بسپار"))
        self.remember_auth_check.setChecked(True)
        self.remember_auth_check.toggled.connect(self._refresh_saved_auth_status)
        self.clear_saved_auth_button = QPushButton(self._t("حذف احراز هویت ذخیره‌شده"))
        self.clear_saved_auth_button.clicked.connect(self._clear_saved_auth_for_current_domain)
        memory_row.addWidget(self.remember_auth_check)
        memory_row.addStretch(1)
        memory_row.addWidget(self.clear_saved_auth_button)
        card_layout.addLayout(memory_row)
        self.auth_profile_status = QLabel(self._t("هنوز روش موفقی برای این سایت ذخیره نشده است."))
        self.auth_profile_status.setObjectName("authProfileStatus")
        self.auth_profile_status.setWordWrap(True)
        self.auth_profile_status.setProperty("authProfileState", "idle")
        card_layout.addWidget(self.auth_profile_status)
        layout.addWidget(card)
        layout.addStretch(1)
        return scroll

    def _build_appearance_settings_tab(self) -> QWidget:
        scroll, _host, layout = self._new_settings_scroll()
        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 13, 15, 13)
        card_layout.setSpacing(10)
        card_layout.addWidget(self._title(self._t("زبان و ظاهر برنامه")))
        self.settings_language_combo = QComboBox()
        for key, label in LANGUAGES.items():
            self.settings_language_combo.addItem(label, key)
        self._set_combo_data(self.settings_language_combo, self.language)
        self.settings_language_combo.activated.connect(lambda _i: self._set_language(self._combo_data(self.settings_language_combo, self.language)))
        self.settings_theme_combo = QComboBox()
        for theme in THEMES.values():
            self.settings_theme_combo.addItem(theme.label(self.language), theme.name)
        self._set_combo_data(self.settings_theme_combo, self.theme.name)
        self.settings_theme_combo.activated.connect(lambda _i: self._set_theme(self._combo_data(self.settings_theme_combo, self.theme.name)))
        card_layout.addWidget(self._field_widget(self._t("زبان"), self.settings_language_combo))
        card_layout.addWidget(self._field_widget(self._t("تم"), self.settings_theme_combo))
        card_layout.addWidget(self._muted(self._t("تغییر زبان رابط را بازسازی می‌کند؛ دانلود فعال هنگام تغییر زبان متوقف نمی‌شود و تغییر مجاز نیست.")))
        layout.addWidget(card)

        sound_card = GlassCard()
        sound_card.setObjectName("sectionCard")
        sound_layout = QVBoxLayout(sound_card)
        sound_layout.setContentsMargins(15, 13, 15, 13)
        sound_layout.setSpacing(10)
        sound_layout.addWidget(self._title(self._t("صداهای برنامه")))
        sound_layout.addWidget(self._muted(self._t("بستهٔ پیش‌فرض Leon از صداهای ملایم CC0 موجود در Wikimedia Commons استفاده می‌کند؛ فایل‌ها در پس‌زمینه یک‌بار دانلود و برای دفعات بعد محلی Cache می‌شوند. برای هر رویداد هم می‌توانی فایل صوتی دلخواه خودت را انتخاب کنی.")))

        self.sound_enabled_check = QCheckBox(self._t("فعال‌بودن صداهای برنامه"))
        self.sound_enabled_check.setChecked(True)
        sound_layout.addWidget(self.sound_enabled_check)

        top_grid = QGridLayout()
        top_grid.setHorizontalSpacing(12)
        top_grid.setVerticalSpacing(8)
        self.sound_theme_combo = QComboBox()
        for key, labels in SOUND_THEME_CHOICES.items():
            self.sound_theme_combo.addItem(labels[1] if self.language == "en" else labels[0], key)
        self._set_combo_data(self.sound_theme_combo, DEFAULT_SOUND_THEME)
        top_grid.addWidget(QLabel(self._t("بستهٔ صدا")), 0, 0)
        top_grid.addWidget(self.sound_theme_combo, 0, 1)

        self.sound_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.sound_volume_slider.setRange(0, 100)
        self.sound_volume_slider.setValue(DEFAULT_VOLUME)
        self.sound_volume_value = QLabel(f"{DEFAULT_VOLUME}%")
        volume_row = QHBoxLayout()
        volume_row.setContentsMargins(0, 0, 0, 0)
        volume_row.addWidget(self.sound_volume_slider, 1)
        volume_row.addWidget(self.sound_volume_value)
        volume_host = QWidget()
        volume_host.setLayout(volume_row)
        top_grid.addWidget(QLabel(self._t("بلندی صدا")), 1, 0)
        top_grid.addWidget(volume_host, 1, 1)
        sound_layout.addLayout(top_grid)

        self.sound_event_checks: dict[str, QCheckBox] = {}
        self.sound_custom_edits: dict[str, QLineEdit] = {}
        event_grid = QGridLayout()
        event_grid.setHorizontalSpacing(8)
        event_grid.setVerticalSpacing(7)
        for row, (event_key, labels) in enumerate(SOUND_EVENT_CHOICES.items()):
            check = QCheckBox(labels[1] if self.language == "en" else labels[0])
            check.setChecked(True)
            edit = QLineEdit()
            edit.setPlaceholderText(self._t("صدای پیش‌فرض ملایم یا فایل سفارشی"))
            browse = QPushButton(self._t("انتخاب…"))
            browse.setMaximumWidth(92)
            browse.clicked.connect(lambda _checked=False, key=event_key: self._choose_custom_sound(key))
            test = QPushButton(self._t("تست"))
            test.setMaximumWidth(64)
            test.clicked.connect(lambda _checked=False, key=event_key: self._play_app_sound(key, force=True))
            event_grid.addWidget(check, row, 0)
            event_grid.addWidget(edit, row, 1)
            event_grid.addWidget(browse, row, 2)
            event_grid.addWidget(test, row, 3)
            self.sound_event_checks[event_key] = check
            self.sound_custom_edits[event_key] = edit
        sound_layout.addLayout(event_grid)

        reset_custom = QPushButton(self._t("پاک‌کردن صداهای سفارشی"))
        reset_custom.clicked.connect(self._clear_custom_sounds)
        sound_layout.addWidget(reset_custom, 0, Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight)

        self.sound_enabled_check.toggled.connect(self._sync_sound_controls)
        self.sound_theme_combo.currentIndexChanged.connect(self._configure_sound_player)
        self.sound_volume_slider.valueChanged.connect(self._sound_volume_changed)
        for edit in self.sound_custom_edits.values():
            edit.editingFinished.connect(self._configure_sound_player)
        layout.addWidget(sound_card)
        self._sync_sound_controls(self.sound_enabled_check.isChecked())
        layout.addStretch(1)
        return scroll

    def _build_search_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(9)
        controls = GlassCard()
        controls.setObjectName("sectionCard")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setSpacing(8)
        controls_layout.addWidget(self._title(self._t("جست‌وجوی مستقیم رسانه")))
        controls_layout.addWidget(self._muted(self._t("سرویس را انتخاب کن، نام ویدئو، آهنگ یا کانال را بنویس و نتیجه را مستقیم به دانلود اضافه کن.")))
        row = QHBoxLayout()
        self.search_service_combo = QComboBox()
        for service in SEARCH_SERVICES.values():
            self.search_service_combo.addItem(service.label(self.language), service.key)
        self.search_query_edit = QLineEdit()
        self.search_query_edit.setPlaceholderText(self._t("نام ویدئو، آهنگ، سازنده یا کانال"))
        self.search_query_edit.returnPressed.connect(self._start_search)
        self.search_limit_spin = QSpinBox()
        self.search_limit_spin.setRange(3, 30)
        self.search_limit_spin.setValue(10)
        self.search_button = QPushButton(self._t("جست‌وجو"))
        self.search_button.setProperty("primary", True)
        self.search_button.clicked.connect(self._start_search)
        row.addWidget(self.search_service_combo)
        row.addWidget(self.search_query_edit, 1)
        row.addWidget(self.search_limit_spin)
        row.addWidget(self.search_button)
        controls_layout.addLayout(row)
        self.search_status_label = ResponsiveLabel(self._t("برای شروع یک عبارت جست‌وجو وارد کن."))
        self.search_status_label.setObjectName("muted")
        controls_layout.addWidget(self.search_status_label)
        layout.addWidget(controls)

        results_card = GlassCard()
        results_card.setObjectName("sectionCard")
        results_layout = QVBoxLayout(results_card)
        results_layout.setContentsMargins(13, 11, 13, 11)
        header = QHBoxLayout()
        header.addWidget(self._title(self._t("نتایج جست‌وجو")))
        header.addStretch(1)
        select_all = QPushButton(self._t("انتخاب همه"))
        select_all.clicked.connect(lambda: self._select_all_search_results(True))
        clear_selection = QPushButton(self._t("لغو انتخاب"))
        clear_selection.clicked.connect(lambda: self._select_all_search_results(False))
        later_selected = QPushButton(self._t("افزودن انتخاب‌شده‌ها به صف"))
        later_selected.clicked.connect(self._later_selected_search_results)
        download_selected = QPushButton(self._t("دانلود انتخاب‌شده‌ها"))
        download_selected.setProperty("primary", True)
        download_selected.clicked.connect(self._download_selected_search_results)
        header.addWidget(clear_selection)
        header.addWidget(select_all)
        header.addWidget(later_selected)
        header.addWidget(download_selected)
        results_layout.addLayout(header)
        self.search_results_scroll = QScrollArea()
        self.search_results_scroll.setWidgetResizable(True)
        self.search_results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.search_results_host = QWidget()
        self.search_results_layout = QVBoxLayout(self.search_results_host)
        self.search_results_layout.setContentsMargins(2, 2, 5, 2)
        self.search_results_layout.setSpacing(7)
        self.search_results_empty = ResponsiveLabel(self._t("هنوز نتیجه‌ای وجود ندارد."))
        self.search_results_empty.setObjectName("muted")
        self.search_results_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.search_results_layout.addWidget(self.search_results_empty)
        self.search_results_layout.addStretch(1)
        self.search_results_scroll.setWidget(self.search_results_host)
        results_layout.addWidget(self.search_results_scroll, 1)
        layout.addWidget(results_card, 1)
        return page

    def _build_later_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(9)

        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(13, 11, 13, 11)
        card_layout.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(self._title(self._t("صف")))
        header.addStretch(1)
        refresh = QPushButton(self._t("تازه‌سازی"))
        refresh.clicked.connect(self._refresh_later_metadata)
        header.addWidget(refresh)
        card_layout.addLayout(header)
        card_layout.addWidget(self._muted(self._t("لینک‌ها را مستقیم به صف اضافه کن؛ کیفیت و محل ذخیرهٔ فعلی همراه هر مورد نگهداری می‌شود.")))

        queue_input = QFrame()
        queue_input.setObjectName("queueInputPanel")
        queue_input_layout = QVBoxLayout(queue_input)
        queue_input_layout.setContentsMargins(10, 9, 10, 9)
        queue_input_layout.setSpacing(6)
        queue_input_layout.addWidget(self._muted(self._t("لینک‌های صف؛ هر لینک در یک خط")))
        self.queue_urls_edit = QPlainTextEdit()
        self.queue_urls_edit.setPlaceholderText(
            "https://www.youtube.com/watch?v=...\n"
            "https://open.spotify.com/track/..."
        )
        self.queue_urls_edit.setMinimumHeight(86)
        self.queue_urls_edit.setMaximumHeight(140)
        self.queue_urls_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        queue_input_layout.addWidget(self.queue_urls_edit)
        queue_input_actions = QHBoxLayout()
        queue_paste = QPushButton(self._t("چسباندن"))
        queue_paste.clicked.connect(self._paste_queue_urls)
        queue_clear = QPushButton(self._t("پاک‌کردن"))
        queue_clear.clicked.connect(self.queue_urls_edit.clear)
        queue_add = QPushButton(self._t("افزودن به صف"))
        queue_add.setProperty("primary", True)
        queue_add.clicked.connect(self._add_queue_page_urls)
        queue_input_actions.addWidget(queue_clear)
        queue_input_actions.addWidget(queue_paste)
        queue_input_actions.addStretch(1)
        queue_input_actions.addWidget(queue_add)
        queue_input_layout.addLayout(queue_input_actions)
        card_layout.addWidget(queue_input)

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        add_current = QPushButton(self._t("افزودن لینک‌های صفحه دانلود"))
        add_current.clicked.connect(self._add_current_to_later)
        load_selected = QPushButton(self._t("انتقال به دانلود"))
        load_selected.clicked.connect(self._load_later_selection)
        download_selected = QPushButton(self._t("دانلود انتخاب‌شده‌ها"))
        download_selected.setProperty("primary", True)
        download_selected.clicked.connect(self._download_later_selection)
        remove_selected = QPushButton(self._t("حذف انتخاب‌شده‌ها"))
        remove_selected.setProperty("danger", True)
        remove_selected.clicked.connect(self._remove_later_selection)
        clear_all = QPushButton(self._t("پاک‌کردن همه"))
        clear_all.clicked.connect(self._clear_later)
        actions.addWidget(add_current, 0, 0)
        actions.addWidget(load_selected, 0, 1)
        actions.addWidget(download_selected, 0, 2)
        actions.addWidget(remove_selected, 1, 0)
        actions.addWidget(clear_all, 1, 1)
        actions.setColumnStretch(2, 1)
        card_layout.addLayout(actions)

        self.later_table = QTableWidget(0, 7)
        self.later_table.setHorizontalHeaderLabels([
            self._t("زمان افزودن"),
            self._t("عنوان / لینک"),
            self._t("مدت رسانه"),
            self._t("حجم"),
            self._t("سرویس"),
            self._t("کیفیت / فرمت"),
            self._t("پوشهٔ ذخیره"),
        ])
        self.later_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.later_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.later_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.later_table.setAlternatingRowColors(True)
        self.later_table.verticalHeader().setVisible(False)
        later_header = self.later_table.horizontalHeader()
        later_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        later_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        later_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        later_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        later_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        later_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        later_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.later_table.doubleClicked.connect(lambda _index: self._load_later_selection())
        card_layout.addWidget(self.later_table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_log_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(9)

        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(13, 11, 13, 11)
        card_layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(self._title(self._t("گزارش زنده")))
        header.addStretch(1)
        self.copy_log_button = QPushButton(self._t("کپی گزارش"))
        self.copy_log_button.clicked.connect(self._copy_log)
        self.clear_log_button = QPushButton(self._t("پاک‌کردن گزارش"))
        self.clear_log_button.clicked.connect(lambda: self.log_view.setPlainText(""))
        header.addWidget(self.copy_log_button)
        header.addWidget(self.clear_log_button)
        card_layout.addLayout(header)
        card_layout.addWidget(self._muted(self._t("گزارش اجرای برنامه، جست‌وجو، نصب ابزارها و جزئیات دانلود در این بخش نگهداری می‌شود.")))
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.log_view.setMinimumHeight(420)
        card_layout.addWidget(self.log_view, 1)
        layout.addWidget(card, 1)
        return page

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(9)
        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(13, 11, 13, 11)
        header = QHBoxLayout()
        header.addWidget(self._title(self._t("تاریخچهٔ دانلودها")))
        header.addStretch(1)
        refresh = QPushButton(self._t("تازه‌سازی"))
        refresh.clicked.connect(self._refresh_history_table)
        redownload = QPushButton(self._t("دانلود دوباره"))
        redownload.clicked.connect(self._redownload_history_selection)
        open_folder = QPushButton(self._t("بازکردن پوشه"))
        open_folder.clicked.connect(self._open_history_folder)
        copy_url = QPushButton(self._t("کپی لینک"))
        copy_url.clicked.connect(self._copy_history_url)
        clear = QPushButton(self._t("پاک‌کردن تاریخچه"))
        clear.setProperty("danger", True)
        clear.clicked.connect(self._clear_history)
        for button in (refresh, redownload, open_folder, copy_url, clear):
            header.addWidget(button)
        card_layout.addLayout(header)
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels([
            self._t("زمان"), self._t("عنوان"), self._t("سرویس"), self._t("فرمت"), self._t("پوشه"),
        ])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.verticalHeader().setVisible(False)
        header_view = self.history_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.history_table.doubleClicked.connect(self._redownload_history_selection)
        card_layout.addWidget(self.history_table, 1)
        layout.addWidget(card, 1)
        return page

    def _build_browser_bridge_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(9)

        card = GlassCard()
        card.setObjectName("sectionCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 14, 15, 14)
        card_layout.setSpacing(10)

        header = QHBoxLayout()
        header.addWidget(self._title(self._t("افزونه Chrome و اتصال مرورگر")))
        header.addStretch(1)
        refresh = QPushButton(self._t("تازه‌سازی"))
        refresh.clicked.connect(self._refresh_browser_bridge_status)
        header.addWidget(refresh)
        card_layout.addLayout(header)
        card_layout.addWidget(self._muted(self._t("صفحه یا لینک رسانه را مستقیماً از Chrome به دانلود یا صف Leon بفرست. ارسال کوکی اختیاری است و فقط برای دامنهٔ همان صفحه انجام می‌شود.")))

        status_panel = QFrame()
        status_panel.setObjectName("queueInputPanel")
        status_layout = QGridLayout(status_panel)
        status_layout.setContentsMargins(12, 11, 12, 11)
        status_layout.setHorizontalSpacing(10)
        status_layout.setVerticalSpacing(8)
        status_layout.addWidget(QLabel(self._t("وضعیت اتصال")), 0, 0)
        self.browser_bridge_status_label = ResponsiveLabel(self._t("در حال بررسی…"))
        self.browser_bridge_status_label.setObjectName("runtimeStatus")
        status_layout.addWidget(self.browser_bridge_status_label, 0, 1)
        status_layout.addWidget(QLabel(self._t("شناسه افزونه")), 1, 0)
        self.browser_extension_id_edit = QLineEdit(EXTENSION_ID)
        self.browser_extension_id_edit.setReadOnly(True)
        self.browser_extension_id_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        status_layout.addWidget(self.browser_extension_id_edit, 1, 1)
        status_layout.addWidget(QLabel(self._t("پوشه افزونه")), 2, 0)
        self.browser_extension_path_edit = QLineEdit(str(installed_extension_dir()))
        self.browser_extension_path_edit.setReadOnly(True)
        self.browser_extension_path_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        status_layout.addWidget(self.browser_extension_path_edit, 2, 1)
        status_layout.addWidget(QLabel(self._t("کد اتصال")), 3, 0)
        self.browser_pairing_edit = QLineEdit()
        self.browser_pairing_edit.setReadOnly(True)
        self.browser_pairing_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.browser_pairing_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        status_layout.addWidget(self.browser_pairing_edit, 3, 1)
        card_layout.addWidget(status_panel)

        actions = QGridLayout()
        actions.setHorizontalSpacing(8)
        actions.setVerticalSpacing(8)
        install_button = QPushButton(self._t("نصب / تعمیر اتصال"))
        install_button.setProperty("primary", True)
        install_button.clicked.connect(self._install_browser_bridge)
        open_extensions = QPushButton(self._t("بازکردن افزونه‌های Chrome"))
        open_extensions.clicked.connect(self._open_chrome_extensions)
        open_folder = QPushButton(self._t("بازکردن پوشه افزونه"))
        open_folder.clicked.connect(self._open_browser_extension_folder)
        copy_path = QPushButton(self._t("کپی مسیر افزونه"))
        copy_path.clicked.connect(self._copy_browser_extension_path)
        copy_code = QPushButton(self._t("کپی کد اتصال"))
        copy_code.clicked.connect(self._copy_browser_pairing_code)
        uninstall_button = QPushButton(self._t("حذف اتصال بومی"))
        uninstall_button.setProperty("danger", True)
        uninstall_button.clicked.connect(self._uninstall_browser_bridge)
        actions.addWidget(install_button, 0, 0)
        actions.addWidget(open_extensions, 0, 1)
        actions.addWidget(open_folder, 0, 2)
        actions.addWidget(copy_path, 1, 0)
        actions.addWidget(copy_code, 1, 1)
        actions.addWidget(uninstall_button, 1, 2)
        card_layout.addLayout(actions)

        guide = ResponsiveLabel(self._t("راهنما: ۱) نصب / تعمیر اتصال را بزن. ۲) در chrome://extensions حالت Developer mode را فعال کن. ۳) Load unpacked را بزن و پوشه افزونه را انتخاب کن. ۴) کد اتصال را یک‌بار داخل پنجره افزونه وارد کن."))
        guide.setObjectName("muted")
        guide.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(guide)

        privacy = ResponsiveLabel(self._t("امنیت: Chrome فقط با شناسه ثابت افزونه و کد اتصال محلی پذیرفته می‌شود. کوکی‌ها داخل Inbox ذخیره نمی‌شوند و در Windows با DPAPI حساب فعلی رمزگذاری می‌شوند."))
        privacy.setObjectName("muted")
        privacy.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        card_layout.addWidget(privacy)

        layout.addWidget(card)
        layout.addStretch(1)
        QTimer.singleShot(0, self._refresh_browser_bridge_status)
        return page

    def _refresh_browser_bridge_status(self) -> None:
        if not hasattr(self, "browser_bridge_status_label"):
            return
        status = bridge_status()
        self.browser_extension_path_edit.setText(str(status.get("extension_path") or installed_extension_dir()))
        try:
            self.browser_pairing_edit.setText(pairing_token())
        except OSError:
            self.browser_pairing_edit.clear()
        if not status.get("supported"):
            text = self._t("نصب خودکار اتصال فعلاً فقط در Windows پشتیبانی می‌شود.")
            state = "warning"
        elif status.get("registered") and status.get("extension_ready") and status.get("pairing_ready"):
            text = self._t("اتصال بومی آماده است؛ افزونه را در Chrome بارگذاری و Pair کن.")
            state = "ready"
        elif status.get("registered"):
            text = self._t("اتصال ثبت شده اما فایل‌های افزونه یا کد اتصال ناقص است؛ Repair را اجرا کن.")
            state = "warning"
        else:
            text = self._t("اتصال Chrome نصب نشده است.")
            state = "missing"
        self.browser_bridge_status_label.setText(text)
        self.browser_bridge_status_label.setProperty("runtimeState", state)
        self.browser_bridge_status_label.style().unpolish(self.browser_bridge_status_label)
        self.browser_bridge_status_label.style().polish(self.browser_bridge_status_label)

    def _install_browser_bridge(self) -> None:
        try:
            install_browser_bridge()
        except BrowserBridgeError as exc:
            QMessageBox.warning(self, self._t("افزونه Chrome"), self._localized_error(str(exc)))
            return
        self._refresh_browser_bridge_status()
        self.toast.show_message(self._t("اتصال Chrome آماده شد؛ حالا افزونه را با Load unpacked بارگذاری کن."), duration_ms=4200)

    def _uninstall_browser_bridge(self) -> None:
        uninstall_browser_bridge(remove_pairing=False)
        self._refresh_browser_bridge_status()
        self.toast.show_message(self._t("ثبت اتصال بومی Chrome حذف شد."))

    def _copy_browser_extension_path(self) -> None:
        QApplication.clipboard().setText(str(installed_extension_dir()))
        self.toast.show_message(self._t("مسیر افزونه کپی شد"))

    def _copy_browser_pairing_code(self) -> None:
        try:
            code = pairing_token()
        except OSError:
            self.toast.show_message(self._t("کد اتصال در دسترس نیست"))
            return
        QApplication.clipboard().setText(code)
        self.toast.show_message(self._t("کد اتصال کپی شد"))

    def _open_browser_extension_folder(self) -> None:
        path = installed_extension_dir()
        if not path.is_dir():
            self.toast.show_message(self._t("ابتدا اتصال Chrome را نصب کن"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_chrome_extensions(self) -> None:
        candidates = [
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                try:
                    subprocess.Popen([candidate, "chrome://extensions/"], close_fds=True)
                    return
                except OSError:
                    continue
        self.toast.show_message(self._t("Chrome پیدا نشد؛ chrome://extensions را دستی باز کن."), duration_ms=3600)

    def _poll_browser_bridge_requests(self) -> None:
        requests = consume_browser_requests()
        if not requests:
            return
        # The Native Messaging host writes authentication profiles from a
        # separate process. Reload before resolving the just-received domains.
        self.auth_store.refresh(force=True)
        self._play_app_sound("notification")
        preview_needed = False
        last_action = ""
        for request in requests:
            url = str(request.get("url") or "").strip()
            title = str(request.get("title") or "").strip()
            action = str(request.get("action") or "open")
            cookie_count = int(request.get("cookie_count") or 0)
            cookie_domains = {
                service_domain(str(domain or ""))
                for domain in list(request.get("cookie_domains") or [])
                if service_domain(str(domain or ""))
            }
            self._browser_auth_validation_domains.update(cookie_domains)
            if not url:
                continue
            last_action = action
            if action == "queue":
                result_map = {url: {"title": title or url, "service": ""}}
                self._add_urls_to_later([url], result_map=result_map)
            else:
                current = [line.strip() for line in self.urls_edit.toPlainText().splitlines() if line.strip()]
                if url not in current:
                    current.append(url)
                    self.urls_edit.setPlainText("\n".join(current))
                preview_needed = True
            note = f"Browser bridge: {url}"
            if cookie_count:
                note += f" ({cookie_count} cookies stored securely)"
            self._append_log(note)

        if last_action == "queue" and "later" in self.page_indexes:
            self.main_pages.setCurrentIndex(self.page_indexes["later"])
            self._refresh_later_table()
        elif preview_needed and "download" in self.page_indexes:
            self.main_pages.setCurrentIndex(self.page_indexes["download"])
            if not self._browser_preview_pending:
                self._browser_preview_pending = True
                QTimer.singleShot(180, self._preview_browser_links)
        self.show()
        self.raise_()
        self.activateWindow()
        self._refresh_saved_auth_status()

    def _preview_browser_links(self) -> None:
        self._browser_preview_pending = False
        if self._urls() and not (self.preview_worker and self.preview_worker.isRunning()):
            self._preview_all_urls()

    def _build_packages_page(self) -> QWidget:
        page = QWidget()
        outer_layout = QVBoxLayout(page)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("packagesScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer_layout.addWidget(scroll)

        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(9)
        scroll.setWidget(host)

        runtime_card = GlassCard()
        runtime_card.setObjectName("sectionCard")
        runtime_layout = QVBoxLayout(runtime_card)
        runtime_layout.setContentsMargins(14, 12, 14, 12)
        runtime_layout.setSpacing(8)
        runtime_layout.addWidget(self._title(self._t("موتور JavaScript")))
        runtime_layout.addWidget(self._muted(self._t("YouTube و بعضی سرویس‌ها برای استخراج کامل به Deno یا موتور سازگار نیاز دارند.")))
        runtime_grid = QGridLayout()
        self.runtime_combo = QComboBox()
        for key in RUNTIME_CHOICES:
            self.runtime_combo.addItem(self._choice_label(RUNTIME_CHOICES, key), key)
        self._compact_combo(self.runtime_combo, 20)
        self.runtime_combo.currentIndexChanged.connect(self._detect_runtime)
        self.runtime_path_edit = QLineEdit()
        self.runtime_path_edit.setPlaceholderText(self._t("مسیر deno.exe؛ در حالت خودکار خالی بگذار"))
        self.runtime_path_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.runtime_path_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.runtime_path_edit.editingFinished.connect(self._detect_runtime)
        runtime_grid.addWidget(self._field_widget(self._t("موتور"), self.runtime_combo), 0, 0)
        runtime_grid.addWidget(self._field_widget(self._t("مسیر اجرایی اختیاری"), self.runtime_path_edit), 0, 1)
        runtime_layout.addLayout(runtime_grid)
        runtime_actions = QHBoxLayout()
        choose_runtime = QPushButton(self._t("انتخاب فایل"))
        choose_runtime.clicked.connect(self._choose_runtime_file)
        check_runtime = QPushButton(self._t("بررسی موتور"))
        check_runtime.clicked.connect(self._detect_runtime)
        runtime_actions.addWidget(choose_runtime)
        runtime_actions.addWidget(check_runtime)
        runtime_actions.addStretch(1)
        runtime_layout.addLayout(runtime_actions)
        self.runtime_status = ResponsiveLabel(self._t("در حال بررسی موتور JavaScript…"))
        self.runtime_status.setObjectName("runtimeStatus")
        runtime_layout.addWidget(self.runtime_status)
        layout.addWidget(runtime_card)

        packages_card = GlassCard()
        packages_card.setObjectName("sectionCard")
        packages_layout = QVBoxLayout(packages_card)
        packages_layout.setContentsMargins(13, 11, 13, 11)
        packages_layout.setSpacing(8)

        package_header = QHBoxLayout()
        package_header.addWidget(self._title(self._t("پکیج‌ها و ابزارها")))
        package_header.addStretch(1)
        self.package_refresh_button = QPushButton(self._t("بررسی کامل سیستم"))
        self.package_refresh_button.clicked.connect(self._refresh_package_status)
        package_header.addWidget(self.package_refresh_button)
        packages_layout.addLayout(package_header)
        packages_layout.addWidget(self._muted(self._t("ابتدا محیط Python، مسیرهای سیستم، ابزارهای محلی و WinGet کامل بررسی می‌شوند؛ سپس برای هر مورد فقط نصب یا به‌روزرسانی مناسب نمایش داده می‌شود.")))

        self.package_table = QTableWidget(0, 6)
        self.package_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.package_table.setMinimumHeight(230)
        self.package_table.setAlternatingRowColors(True)
        self.package_table.setHorizontalHeaderLabels([
            self._t("ابزار"),
            self._t("کاربرد"),
            self._t("وضعیت"),
            self._t("نسخه"),
            self._t("مسیر"),
            self._t("عملیات"),
        ])
        self.package_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.package_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.package_table.verticalHeader().setVisible(False)
        self.package_table.verticalHeader().setDefaultSectionSize(42)
        self.package_table.verticalHeader().setMinimumSectionSize(38)
        self.package_table.setWordWrap(True)
        package_table_header = self.package_table.horizontalHeader()
        package_table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        package_table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        package_table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        package_table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        package_table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        package_table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        packages_layout.addWidget(self.package_table, 1)

        spotify_header = QHBoxLayout()
        spotify_header.addWidget(self._title(self._t("دسترسی Spotify")))
        spotify_header.addStretch(1)
        packages_layout.addLayout(spotify_header)

        self.spotify_official_api_check = QCheckBox(self._t("استفاده از API رسمی Spotify برای متادیتا"))
        packages_layout.addWidget(self.spotify_official_api_check)

        spotify_grid = QGridLayout()
        spotify_grid.setHorizontalSpacing(10)
        self.spotify_client_id_edit = QLineEdit()
        self.spotify_client_id_edit.setPlaceholderText("Spotify Client ID")
        self.spotify_client_id_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.spotify_client_secret_edit = QLineEdit()
        self.spotify_client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.spotify_client_secret_edit.setPlaceholderText(self._t("Client Secret فقط برای همین اجرا"))
        self.spotify_client_secret_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.spotify_proxy_edit = QLineEdit()
        self.spotify_proxy_edit.setPlaceholderText("http://127.0.0.1:8080")
        self.spotify_proxy_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        spotify_grid.addWidget(self._field_widget(self._t("Spotify Client ID"), self.spotify_client_id_edit), 0, 0)
        spotify_grid.addWidget(self._field_widget(self._t("Spotify Client Secret"), self.spotify_client_secret_edit), 0, 1)
        spotify_grid.addWidget(self._field_widget(self._t("پروکسی Spotify و YouTube (اختیاری)"), self.spotify_proxy_edit), 1, 0, 1, 2)
        packages_layout.addLayout(spotify_grid)
        packages_layout.addWidget(self._muted(self._t("spotDL اطلاعات را از Spotify می‌گیرد و فایل صوتی متناظر را از YouTube پیدا می‌کند. اگر Spotify، YouTube یا YouTube Music در شبکه شما محدود است، یک پروکسی HTTP(S) وارد کنید. در خطای YouTube Music، برنامه خودکار یک‌بار با YouTube معمولی تلاش می‌کند. Client Secret ذخیره نمی‌شود.")))

        google_header = QHBoxLayout()
        google_header.addWidget(self._title(self._t("دسترسی Google Play")))
        google_header.addStretch(1)
        packages_layout.addLayout(google_header)
        google_grid = QGridLayout()
        google_grid.setHorizontalSpacing(10)
        self.google_play_email_edit = QLineEdit()
        self.google_play_email_edit.setPlaceholderText("account@example.com")
        self.google_play_email_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.google_play_aas_token_edit = QLineEdit()
        self.google_play_aas_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.google_play_aas_token_edit.setPlaceholderText(self._t("توکن AAS فقط برای همین اجرا"))
        self.google_play_aas_token_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        google_grid.addWidget(self._field_widget(self._t("ایمیل Google Play"), self.google_play_email_edit), 0, 0)
        google_grid.addWidget(self._field_widget(self._t("توکن AAS Google Play"), self.google_play_aas_token_edit), 0, 1)
        packages_layout.addLayout(google_grid)
        packages_layout.addWidget(self._muted(self._t("این اطلاعات فقط برای apkeep و دانلود از Google Play استفاده می‌شوند؛ توکن AAS در تنظیمات ذخیره نمی‌شود.")))

        self.package_log = QPlainTextEdit()
        self.package_log.setReadOnly(True)
        self.package_log.setMaximumHeight(130)
        self.package_log.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        packages_layout.addWidget(self.package_log)
        layout.addWidget(packages_card, 1)
        layout.addStretch(1)
        return page


    def _build_status_column(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("statusScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        host = QWidget()
        host.setMinimumWidth(0)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(host)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(9)

        preview_card = GlassCard()
        preview_card.setObjectName("previewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(13, 12, 13, 12)
        preview_layout.setSpacing(8)

        preview_header = QHBoxLayout()
        preview_header.setSpacing(8)
        self.preview_section_title = ResponsiveLabel(self._t("پیش‌نمایش لینک‌ها"))
        self.preview_section_title.setObjectName("sectionTitle")
        self.preview_count_badge = QLabel(f"{self._digits(0)} / {self._digits(0)}")
        self.preview_count_badge.setObjectName("previewCountBadge")
        self.preview_count_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        preview_header.addWidget(self.preview_section_title, 1)
        preview_header.addWidget(self.preview_count_badge)
        preview_layout.addLayout(preview_header)
        self.preview_size_summary = ResponsiveLabel(self._t("حجم کل انتخاب‌شده: —"))
        self.preview_size_summary.setObjectName("previewSizeSummary")
        self.preview_size_summary.setProperty("muted", True)
        self.preview_size_summary.setToolTip(self._t("حجم بر اساس کیفیت، زبان صدا و فرمت فعلی محاسبه می‌شود."))
        preview_layout.addWidget(self.preview_size_summary)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setObjectName("previewListScroll")
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preview_scroll.setMinimumHeight(205)
        self.preview_scroll.setMaximumHeight(360)

        self.preview_host = QWidget()
        self.preview_host.setMinimumWidth(0)
        self.preview_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.preview_list_layout = QVBoxLayout(self.preview_host)
        self.preview_list_layout.setContentsMargins(2, 2, 5, 2)
        self.preview_list_layout.setSpacing(7)
        self.preview_empty_panel = QFrame()
        self.preview_empty_panel.setObjectName("previewEmptyPanel")
        empty_layout = QVBoxLayout(self.preview_empty_panel)
        empty_layout.setContentsMargins(14, 14, 14, 14)
        empty_layout.setSpacing(7)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty_graphic = EmptyStateGraphic()
        self.preview_empty_label = ResponsiveLabel(self._t("هنوز پیش‌نمایشی ساخته نشده است."))
        self.preview_empty_label.setObjectName("previewEmpty")
        self.preview_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = ResponsiveLabel(self._t("هر لینک در یک خط؛ لینک‌ها را می‌توانی مستقیماً داخل پنجره رها کنی."))
        empty_hint.setObjectName("muted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.preview_empty_graphic, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.preview_empty_label)
        empty_layout.addWidget(empty_hint)
        self.preview_empty_panel.setMinimumHeight(158)
        self.preview_list_layout.addWidget(self.preview_empty_panel)
        self.preview_list_layout.addStretch(1)
        self.preview_scroll.setWidget(self.preview_host)
        preview_layout.addWidget(self.preview_scroll)
        layout.addWidget(preview_card)

        status_card = GlassCard(strong=True)
        status_card.setObjectName("statusCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(14, 12, 14, 12)
        status_layout.setSpacing(8)
        status_header = QHBoxLayout()
        status_header.setSpacing(8)
        self.status_label = ResponsiveLabel(self._t("آماده"))
        self.status_label.setObjectName("statusTitle")
        self.active_service_badge = QLabel(self._t("سرویس نامشخص"))
        self.active_service_badge.setObjectName("serviceBadgeMuted")
        self.active_service_badge.setMaximumWidth(170)
        self.active_service_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        status_header.addWidget(self.status_label, 1)
        status_header.addWidget(self.active_service_badge)
        status_layout.addLayout(status_header)
        self.detail_label = ResponsiveLabel(self._t("لینک‌ها را وارد کنید و دانلود را آغاز کنید."))
        self.detail_label.setObjectName("muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"{self._digits(0)}%")
        status_layout.addWidget(self.detail_label)
        status_layout.addWidget(self.progress_bar)

        stats = QHBoxLayout()
        stats.setSpacing(6)
        self.size_value = self._stat(stats, self._t("حجم"), "—")
        self.speed_value = self._stat(stats, self._t("سرعت"), "—")
        self.eta_value = self._stat(stats, self._t("زمان باقی‌مانده"), "—")
        status_layout.addLayout(stats)
        self.speed_wave = SpeedWaveWidget()
        self.speed_wave.set_caption(self._t("سرعت دانلود"))
        self.speed_wave.setToolTip(self._t("نمودار لحظه‌ای سرعت دانلود"))
        status_layout.addWidget(self.speed_wave)
        layout.addWidget(status_card)

        queue_card = GlassCard()
        queue_card.setObjectName("sectionCard")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(13, 11, 13, 11)
        queue_header = QHBoxLayout()
        queue_header.addWidget(self._title(self._t("صف دانلود")))
        queue_header.addStretch(1)
        self.queue_count = QLabel(f"{self._digits(0)} {self._t('مورد')}")
        self.queue_count.setObjectName("accent")
        queue_header.addWidget(self.queue_count)
        queue_layout.addLayout(queue_header)
        queue_layout.addWidget(self._muted(self._t("عنوان و لینک هر مورد در این بخش نمایش داده می‌شود.")))
        self.queue_list = QListWidget()
        self.queue_list.setMinimumHeight(124)
        self.queue_list.setWordWrap(True)
        self.queue_list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.queue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_list.setSpacing(3)
        queue_layout.addWidget(self.queue_list)
        layout.addWidget(queue_card)

        scroll.setWidget(host)
        return scroll

    @staticmethod
    def _title(text: str) -> ResponsiveLabel:
        label = ResponsiveLabel(text)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _muted(text: str) -> ResponsiveLabel:
        label = ResponsiveLabel(text)
        label.setObjectName("muted")
        return label

    def _field_widget(self, title: str, control: QWidget) -> QWidget:
        field = QWidget()
        field.setMinimumWidth(0)
        field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(5)
        label = self._muted(title)
        label.setProperty("fieldLabel", True)
        field_layout.addWidget(label)
        field_layout.addWidget(control)
        return field

    @staticmethod
    def _compact_combo(combo: QComboBox, minimum_characters: int = 16) -> None:
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(minimum_characters)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        combo.setToolTip(combo.currentText())
        combo.currentTextChanged.connect(combo.setToolTip)

    def _hero_preset_changed(self, *_args: object) -> None:
        if not hasattr(self, "preset_combo"):
            return
        selected = self._combo_data(self.hero_preset_combo, "auto")
        if self._combo_data(self.preset_combo, "auto") == selected:
            return
        self._set_combo_data(self.preset_combo, selected)

    def _sync_hero_preset(self, *_args: object) -> None:
        if not hasattr(self, "hero_preset_combo") or not hasattr(self, "preset_combo"):
            return
        selected = self._combo_data(self.preset_combo, "auto")
        if self._combo_data(self.hero_preset_combo, "auto") == selected:
            return
        self.hero_preset_combo.blockSignals(True)
        try:
            self._set_combo_data(self.hero_preset_combo, selected)
        finally:
            self.hero_preset_combo.blockSignals(False)

    def _update_quick_stats(self, *_args) -> None:
        if not hasattr(self, "hero_links_stat"):
            return
        link_count = len(self._urls()) if hasattr(self, "urls_edit") else 0
        count_text = f"{self._digits(link_count)} {self._t('مورد')}"
        self.hero_links_stat.set_value(count_text)

        if hasattr(self, "preset_combo"):
            self._sync_hero_preset()

        if hasattr(self, "output_edit"):
            raw_path = self.output_edit.text().strip()
            display = Path(raw_path).name if raw_path else "—"
            if not display and raw_path:
                display = raw_path
            self.hero_output_stat.set_value(display or "—", raw_path)

    def _refresh_action_icons(self) -> None:
        if not hasattr(self, "preview_button"):
            return
        self.preview_button.setIcon(make_line_icon("preview", self.theme.text, accent=self.theme.accent, size=22))
        if hasattr(self, "preview_inline_button"):
            self.preview_inline_button.setIcon(make_line_icon("preview", self.theme.text, accent=self.theme.accent, size=20))
        self.open_folder_button.setIcon(make_line_icon("folder", self.theme.text, accent=self.theme.accent, size=22))
        self.start_button.setIcon(make_line_icon("download", self.theme.accent_text, accent=self.theme.accent, size=22))
        if hasattr(self, "later_button"):
            self.later_button.setIcon(make_line_icon("later", self.theme.text, accent=self.theme.accent, size=20))
        self.cancel_button.setIcon(make_line_icon("close", self.theme.danger, accent=self.theme.danger, size=20))
        if hasattr(self, "copy_log_button"):
            self.copy_log_button.setIcon(make_line_icon("copy", self.theme.text, accent=self.theme.accent, size=20))
        if hasattr(self, "clear_log_button"):
            self.clear_log_button.setIcon(make_line_icon("trash", self.theme.text, accent=self.theme.danger, size=20))

    def _stat(self, parent: QHBoxLayout, title: str, value: str) -> ResponsiveLabel:
        box = QFrame()
        box.setProperty("glassStrong", True)
        box.setMinimumHeight(72)
        box.setMinimumWidth(0)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.setSpacing(5)
        dot = QLabel("●")
        dot.setObjectName("accent")
        dot.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        title_label = ResponsiveLabel(title)
        title_label.setObjectName("statTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addStretch(1)
        header.addWidget(dot)
        header.addWidget(title_label)
        header.addStretch(1)
        value_label = ResponsiveLabel(value)
        value_label.setObjectName("statValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(header)
        layout.addWidget(value_label)
        parent.addWidget(box, 1)
        return value_label

    def _apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(build_stylesheet(self.theme))
        self.title_bar.set_theme(self.theme, self.language)
        if hasattr(self.surface, "set_theme"):
            self.surface.set_theme(self.theme)
        if getattr(self, "preview_empty_graphic", None) is not None:
            self.preview_empty_graphic.set_theme(self.theme)
        if getattr(self, "speed_wave", None) is not None:
            self.speed_wave.set_theme(self.theme)
        self._refresh_action_icons()
        self.surface.style().unpolish(self.surface)
        self.surface.style().polish(self.surface)
        self._refresh_queue_colors()
        if self.isVisible():
            self._schedule_native_blur(80)

    def _show_theme_menu(self) -> None:
        menu = QMenu(self)
        menu.setLayoutDirection(self._layout_direction())
        group = QActionGroup(menu)
        group.setExclusive(True)

        for name, theme in THEMES.items():
            action = menu.addAction(theme.label(self.language))
            action.setIcon(make_line_icon("sparkles", theme.accent, accent=theme.accent_hover, size=20))
            action.setCheckable(True)
            action.setChecked(name == self.theme.name)
            action.setData(name)
            group.addAction(action)

        selected = menu.exec(
            self.title_bar.theme_button.mapToGlobal(
                self.title_bar.theme_button.rect().bottomLeft()
            )
        )
        if selected is not None:
            self._set_theme(str(selected.data()))

    def _show_language_menu(self) -> None:
        menu = QMenu(self)
        menu.setLayoutDirection(self._layout_direction())
        group = QActionGroup(menu)
        group.setExclusive(True)
        for key, label in LANGUAGES.items():
            action = menu.addAction(label)
            action.setIcon(make_line_icon("language", self.theme.text, accent=self.theme.accent, size=20))
            action.setCheckable(True)
            action.setChecked(key == self.language)
            action.setData(key)
            group.addAction(action)
        selected = menu.exec(
            self.title_bar.language_button.mapToGlobal(
                self.title_bar.language_button.rect().bottomLeft()
            )
        )
        if selected is not None:
            self._set_language(str(selected.data()))

    def _capture_preview_state(self) -> list[dict[str, Any]]:
        captured: list[dict[str, Any]] = []
        for index, result in enumerate(self.preview_results):
            saved = {
                "state": str(result.get("state") or "pending"),
                "url": str(result.get("url") or ""),
                "info": dict(result.get("info") or {}),
                "error": str(result.get("error") or ""),
                "pixmap": None,
            }
            if 0 <= index < len(self.preview_cards):
                pixmap = self.preview_cards[index].image.pixmap()
                if pixmap is not None and not pixmap.isNull():
                    saved["pixmap"] = pixmap.copy()
            captured.append(saved)
        return captured

    def _capture_ui_state(self) -> dict[str, Any]:
        return {
            "urls": self.urls_edit.toPlainText(),
            "queue_input": self.queue_urls_edit.toPlainText() if hasattr(self, "queue_urls_edit") else "",
            "output": self.output_edit.text(),
            "preset": self._combo_data(self.preset_combo, "auto"),
            "auth": self._combo_data(self.auth_combo, "none"),
            "browser": self.browser_combo.currentText(),
            "browser_profile": self.browser_profile_edit.text(),
            "cookie_file": self.cookie_file_edit.text(),
            "cookie_domain": self.cookie_domain_edit.text(),
            "manual_cookie": self.manual_cookie_edit.toPlainText(),
            "remember_auth": self.remember_auth_check.isChecked(),
            "organize_service": self.organize_service_check.isChecked(),
            "playlist": self.playlist_check.isChecked(),
            "metadata": self.metadata_check.isChecked(),
            "thumbnail": self.thumbnail_check.isChecked(),
            "subtitles": self.subtitle_check.isChecked(),
            "auto_subtitles": self.auto_subtitle_check.isChecked(),
            "mark_watched": self.mark_watched_check.isChecked(),
            "sound_enabled": self.sound_enabled_check.isChecked() if hasattr(self, "sound_enabled_check") else True,
            "sound_theme": self._combo_data(self.sound_theme_combo, DEFAULT_SOUND_THEME) if hasattr(self, "sound_theme_combo") else DEFAULT_SOUND_THEME,
            "sound_volume": self.sound_volume_slider.value() if hasattr(self, "sound_volume_slider") else DEFAULT_VOLUME,
            "sound_events": {key: control.isChecked() for key, control in getattr(self, "sound_event_checks", {}).items()},
            "sound_custom": self._sound_custom_paths(),
            "subtitle_language": self._selected_subtitle_language(),
            "audio_language": self._selected_audio_language(),
            "detected_audio_languages": dict(self.detected_audio_languages),
            "detected_subtitle_languages": dict(self.detected_subtitle_languages),
            "fragments": self.fragments_spin.value(),
            "runtime": self._combo_data(self.runtime_combo, "auto"),
            "runtime_path": self.runtime_path_edit.text(),
            "previews": self._capture_preview_state(),
            "status": self.status_label.text(),
            "active_service": self.active_service_badge.text(),
            "detail": self.detail_label.text(),
            "progress_min": self.progress_bar.minimum(),
            "progress_max": self.progress_bar.maximum(),
            "progress_value": self.progress_bar.value(),
            "progress_format": self.progress_bar.format(),
            "size": self.size_value.text(),
            "speed": self.speed_value.text(),
            "eta": self.eta_value.text(),
            "queue": [
                (
                    self.queue_list.item(i).text(),
                    self.queue_list.item(i).toolTip(),
                    self.queue_list.item(i).data(Qt.ItemDataRole.UserRole),
                    self.queue_list.item(i).data(Qt.ItemDataRole.UserRole + 1),
                    self.queue_list.item(i).data(Qt.ItemDataRole.UserRole + 2),
                    self.queue_list.item(i).data(Qt.ItemDataRole.UserRole + 3),
                )
                for i in range(self.queue_list.count())
            ],
            "queue_index": self.current_queue_index,
            "log": self.log_view.toPlainText(),
            "main_tab": self._main_page_index(),
            "settings_tab": self.settings_tabs.currentIndex() if hasattr(self, "settings_tabs") else 0,
            "search_query": self.search_query_edit.text() if hasattr(self, "search_query_edit") else "",
            "search_service": self._combo_data(self.search_service_combo, "youtube") if hasattr(self, "search_service_combo") else "youtube",
            "search_limit": self.search_limit_spin.value() if hasattr(self, "search_limit_spin") else 10,
            "search_results": [dict(item) for item in self.search_results],
            "package_log": self.package_log.toPlainText() if hasattr(self, "package_log") else "",
            "spotify_use_official_api": self.spotify_official_api_check.isChecked() if hasattr(self, "spotify_official_api_check") else False,
            "spotify_client_id": self.spotify_client_id_edit.text() if hasattr(self, "spotify_client_id_edit") else "",
            "spotify_client_secret": self.spotify_client_secret_edit.text() if hasattr(self, "spotify_client_secret_edit") else "",
            "spotify_proxy": self.spotify_proxy_edit.text() if hasattr(self, "spotify_proxy_edit") else "",
            "google_play_email": self.google_play_email_edit.text() if hasattr(self, "google_play_email_edit") else "",
            "google_play_aas_token": self.google_play_aas_token_edit.text() if hasattr(self, "google_play_aas_token_edit") else "",
        }

    def _restore_preview_state(self, previews: list[dict[str, Any]]) -> None:
        if not previews:
            self.preview_count_badge.setText(f"{self._digits(0)} / {self._digits(0)}")
            return
        urls = [str(item.get("url") or "") for item in previews]
        self._prepare_preview_cards(urls)
        self.preview_success_count = 0
        self.preview_failure_count = 0
        for index, saved in enumerate(previews):
            if not 0 <= index < len(self.preview_cards):
                continue
            state_name = str(saved.get("state") or "pending")
            info = dict(saved.get("info") or {})
            error = str(saved.get("error") or "")
            card = self.preview_cards[index]
            if state_name == "ready":
                service = str(info.get("service") or self._t("سرویس نامشخص"))
                title = str(info.get("title") or self._t("بدون عنوان"))
                uploader = str(info.get("uploader") or "—")
                duration = human_seconds(info.get("duration"))
                card.service.setText(service)
                card.service.setToolTip(str(info.get("domain") or service))
                card.title.setText(soft_wrap_text(title))
                card.title.setToolTip(title)
                card.meta.setText(soft_wrap_text(f"{uploader}  •  {duration}"))
                card.meta.setToolTip(str(info.get("webpage_url") or card.url))
                self._render_card_audio_languages(card, list(info.get("audio_languages") or []))
                self._merge_detected_audio_languages(list(info.get("audio_languages") or []), refresh=False)
                self._render_card_subtitle_languages(card, list(info.get("subtitle_languages") or []))
                self._merge_detected_subtitle_languages(list(info.get("subtitle_languages") or []), refresh=False)
                card.set_state("ready", self._t("آماده"))
                self.preview_success_count += 1
            elif state_name == "error":
                service = service_identity(None, card.url).get("service") or self._t("سرویس نامشخص")
                card.service.setText(str(service))
                card.title.setText(soft_wrap_text(card.url))
                card.meta.setText(soft_wrap_text(error))
                card.meta.setToolTip(error)
                card.set_state("error", self._t("خطا"))
                self.preview_failure_count += 1
            elif state_name == "checking":
                card.set_state("checking", self._t("در حال بررسی"))
                card.meta.setText(self._t("در حال دریافت اطلاعات…"))
            else:
                card.set_state("pending", self._t("در انتظار بررسی"))
            pixmap = saved.get("pixmap")
            if isinstance(pixmap, QPixmap) and not pixmap.isNull():
                card.image.setPixmap(pixmap)
            self.preview_results[index] = {
                "state": state_name,
                "url": card.url,
                "info": info,
                "error": error,
            }
        self._update_preview_counter()
        if hasattr(self, "audio_language_combo"):
            self._refresh_audio_language_combo(self._selected_audio_language())
        if hasattr(self, "subtitle_language_combo"):
            self._refresh_subtitle_language_combo(self._selected_subtitle_language())
        self._recalculate_preview_sizes()

    def _restore_ui_state(self, state: dict[str, Any]) -> None:
        self.urls_edit.setPlainText(str(state.get("urls", "")))
        if hasattr(self, "queue_urls_edit"):
            self.queue_urls_edit.setPlainText(str(state.get("queue_input", "")))
        self.output_edit.setText(str(state.get("output", self.output_edit.text())))
        self._set_combo_data(self.preset_combo, str(state.get("preset", "auto")))
        self._set_combo_data(self.auth_combo, str(state.get("auth", "none")))
        self._set_combo(self.browser_combo, str(state.get("browser", "Chrome")))
        self.browser_profile_edit.setText(str(state.get("browser_profile", "")))
        self.cookie_file_edit.setText(str(state.get("cookie_file", "")))
        self.cookie_domain_edit.setText(str(state.get("cookie_domain", "")))
        self.manual_cookie_edit.setPlainText(str(state.get("manual_cookie", "")))
        self.remember_auth_check.setChecked(bool(state.get("remember_auth", True)))
        self.organize_service_check.setChecked(bool(state.get("organize_service", True)))
        self.playlist_check.setChecked(bool(state.get("playlist", True)))
        self.metadata_check.setChecked(bool(state.get("metadata", True)))
        self.thumbnail_check.setChecked(bool(state.get("thumbnail", False)))
        self.subtitle_check.setChecked(bool(state.get("subtitles", False)))
        self.auto_subtitle_check.setChecked(bool(state.get("auto_subtitles", True)))
        self.mark_watched_check.setChecked(bool(state.get("mark_watched", False)))
        if hasattr(self, "sound_enabled_check"):
            self.sound_enabled_check.setChecked(bool(state.get("sound_enabled", True)))
            self._set_combo_data(self.sound_theme_combo, normalize_sound_theme(str(state.get("sound_theme", DEFAULT_SOUND_THEME))))
            self.sound_volume_slider.setValue(max(0, min(100, int(state.get("sound_volume", DEFAULT_VOLUME)))))
            event_state = state.get("sound_events") if isinstance(state.get("sound_events"), dict) else {}
            legacy = {
                "download_complete": bool(state.get("sound_success", True)),
                "error": bool(state.get("sound_error", True)),
                "cancelled": bool(state.get("sound_cancelled", True)),
            }
            for key, control in self.sound_event_checks.items():
                control.setChecked(bool(event_state.get(key, legacy.get(key, True))))
            custom_state = state.get("sound_custom") if isinstance(state.get("sound_custom"), dict) else {}
            for key, edit in self.sound_custom_edits.items():
                edit.setText(str(custom_state.get(key) or ""))
            self._sync_sound_controls(self.sound_enabled_check.isChecked())
        self.detected_audio_languages = dict(state.get("detected_audio_languages") or {})
        self.detected_subtitle_languages = dict(state.get("detected_subtitle_languages") or {})
        self._refresh_audio_language_combo(str(state.get("audio_language", "")))
        legacy_subtitle = str(state.get("subtitle_language") or "")
        if not legacy_subtitle:
            legacy_subtitle = next((item.strip() for item in str(state.get("subtitle_langs", "")).split(",") if item.strip()), "all")
        self._refresh_subtitle_language_combo(legacy_subtitle)
        self.fragments_spin.setValue(int(state.get("fragments", 4)))
        self._set_combo_data(self.runtime_combo, str(state.get("runtime", "auto")))
        self.runtime_path_edit.setText(str(state.get("runtime_path", "")))
        self._restore_preview_state(list(state.get("previews", [])))
        self.status_label.setText(translate_known(self.language, str(state.get("status", self.status_label.text()))))
        self.active_service_badge.setText(translate_known(self.language, str(state.get("active_service", self.active_service_badge.text()))))
        self.detail_label.setText(translate_known(self.language, str(state.get("detail", self.detail_label.text()))))
        self.progress_bar.setRange(int(state.get("progress_min", 0)), int(state.get("progress_max", 1000)))
        self.progress_bar.setValue(int(state.get("progress_value", 0)))
        self.progress_bar.setFormat(str(state.get("progress_format", f"{self._digits(0)}%")))
        self.size_value.setText(str(state.get("size", "—")))
        self.speed_value.setText(str(state.get("speed", "—")))
        self.eta_value.setText(translate_known(self.language, str(state.get("eta", "—"))))
        self.queue_items.clear()
        for saved_item in state.get("queue", []):
            values = list(saved_item) if isinstance(saved_item, (list, tuple)) else [saved_item]
            item_text = values[0] if values else ""
            tooltip = values[1] if len(values) > 1 else ""
            user_data = values[2] if len(values) > 2 else ""
            service_data = values[3] if len(values) > 3 else ""
            title_data = values[4] if len(values) > 4 else str(item_text)
            status_data = values[5] if len(values) > 5 else "○"
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, user_data)
            item.setData(Qt.ItemDataRole.UserRole + 1, service_data)
            item.setData(Qt.ItemDataRole.UserRole + 2, title_data)
            item.setData(Qt.ItemDataRole.UserRole + 3, status_data)
            item.setTextAlignment((Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter)
            item.setForeground(QColor(self.theme.text))
            self._render_queue_item(item)
            if tooltip:
                item.setToolTip(str(tooltip))
            self.queue_list.addItem(item)
            self.queue_items.append(item)
        self.current_queue_index = int(state.get("queue_index", -1))
        count = self.queue_list.count()
        self.queue_count.setText(f"{self._digits(count)} {self._t('مورد')}")
        self.log_view.setPlainText(str(state.get("log", "")))
        if hasattr(self, "search_query_edit"):
            self.search_query_edit.setText(str(state.get("search_query", "")))
            self._set_combo_data(self.search_service_combo, str(state.get("search_service", "youtube")))
            self.search_limit_spin.setValue(int(state.get("search_limit", 10)))
            saved_search_results = list(state.get("search_results") or [])
            if saved_search_results:
                self._render_search_results(saved_search_results)
        if hasattr(self, "package_log"):
            self.package_log.setPlainText(str(state.get("package_log", "")))
        if hasattr(self, "spotify_official_api_check"):
            self.spotify_official_api_check.setChecked(bool(state.get("spotify_use_official_api", False)))
        if hasattr(self, "spotify_client_id_edit"):
            self.spotify_client_id_edit.setText(str(state.get("spotify_client_id", "")))
        if hasattr(self, "spotify_client_secret_edit"):
            self.spotify_client_secret_edit.setText(str(state.get("spotify_client_secret", "")))
        if hasattr(self, "spotify_proxy_edit"):
            self.spotify_proxy_edit.setText(str(state.get("spotify_proxy", "")))
        if hasattr(self, "google_play_email_edit"):
            self.google_play_email_edit.setText(str(state.get("google_play_email", "")))
        if hasattr(self, "google_play_aas_token_edit"):
            self.google_play_aas_token_edit.setText(str(state.get("google_play_aas_token", "")))
        if hasattr(self, "settings_tabs"):
            self.settings_tabs.setCurrentIndex(max(0, min(self.settings_tabs.count() - 1, int(state.get("settings_tab", 0)))))
        if hasattr(self, "main_pages"):
            self._set_main_page(int(state.get("main_tab", 0)))
        self._toggle_subtitle_controls(self.subtitle_check.isChecked())
        self._toggle_auth_controls(self.auth_combo.currentIndex())

    def _set_language(self, language: str) -> None:
        language = "en" if language == "en" else "fa"
        if language == self.language:
            return
        if (
            (self.worker and self.worker.isRunning())
            or (self.preview_worker and self.preview_worker.isRunning())
            or (self.search_worker and self.search_worker.isRunning())
            or (self.package_action_worker and self.package_action_worker.isRunning())
            or (self.update_check_worker and self.update_check_worker.isRunning())
            or (self.update_download_worker and self.update_download_worker.isRunning())
            or any(worker.isRunning() for worker in self.thumbnail_workers)
            or any(worker.isRunning() for worker in self.search_thumbnail_workers)
            or any(worker.isRunning() for worker in self.later_metadata_workers)
            or (self.queue_metadata_worker and self.queue_metadata_worker.isRunning())
        ):
            self.toast.show_message(self._t("نمی‌توان زبان را هنگام دانلود تغییر داد"))
            return
        state = self._capture_ui_state()
        self.language = language
        QApplication.instance().setLayoutDirection(self._layout_direction())
        self.setLayoutDirection(self._layout_direction())
        old_widget = self.takeCentralWidget()
        self.queue_items = []
        self._initialized_pages = {"download"}
        self._build_ui()
        self._install_wheel_scroll_guard()
        self._restore_ui_state(state)
        self._apply_theme()
        self._set_busy(False)
        if old_widget is not None:
            old_widget.deleteLater()
        self._save_settings()
        self.toast.show_message("English language enabled" if language == "en" else "زبان فارسی فعال شد")

    def _set_theme(self, name: str) -> None:
        selected = theme_from_name(name)
        if selected.name == self.theme.name:
            return
        self.theme = selected
        if hasattr(self, "settings_theme_combo"):
            self._set_combo_data(self.settings_theme_combo, self.theme.name)
        self._apply_theme()
        if self.language == "en":
            self.toast.show_message(f"{self.theme.label(self.language)} theme enabled")
        else:
            self.toast.show_message(f"تم {self.theme.label(self.language)} فعال شد")

    def _urls(self) -> list[str]:
        values = []
        for line in self.urls_edit.toPlainText().splitlines():
            value = line.strip()
            if value and value not in values:
                values.append(value)
        return values

    def _paste_urls(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            self.toast.show_message(self._t("کلیپ‌بورد خالی است"))
            return
        existing = self.urls_edit.toPlainText().strip()
        self.urls_edit.setPlainText(f"{existing}\n{text}".strip())

    def _append_urls(self, urls: list[str], *, replace: bool = False) -> None:
        cleaned: list[str] = []
        for value in urls:
            url = str(value or "").strip()
            if url and url not in cleaned:
                cleaned.append(url)
        if not cleaned:
            return
        existing = [] if replace else self._urls()
        for url in cleaned:
            if url not in existing:
                existing.append(url)
        self.urls_edit.setPlainText("\n".join(existing))

    def _later_entry(
        self,
        url: str,
        *,
        title: str = "",
        service: str = "",
        duration: object = None,
    ) -> dict[str, Any]:
        identity = service_identity(None, url)
        return {
            "url": url,
            "title": title or url,
            "service": service or identity.get("service") or "Other",
            "domain": identity.get("domain") or url_domain(url),
            "preset": self._combo_data(self.preset_combo, "auto"),
            "preset_label": self.preset_combo.currentText(),
            "audio_language": self._selected_audio_language(),
            "output_dir": self.output_edit.text().strip(),
            "organize_service": self.organize_service_check.isChecked(),
            "duration": duration,
            "size_bytes": None,
            "size_confidence": "unknown",
            "metadata_status": "loading",
        }

    def _add_urls_to_later(self, urls: list[str], *, result_map: dict[str, dict[str, Any]] | None = None) -> int:
        result_map = result_map or {}
        entries: list[dict[str, Any]] = []
        for raw_url in urls:
            url = str(raw_url or "").strip()
            if not url:
                continue
            result = result_map.get(url, {})
            entries.append(self._later_entry(
                url,
                title=str(result.get("title") or ""),
                service=str(result.get("service") or ""),
                duration=result.get("duration"),
            ))
        added = self.later_store.add_many(entries)
        self._refresh_later_table()
        self._start_later_metadata_fetch(entries)
        if added:
            self.toast.show_message(
                f"{added} item(s) added to Queue" if self.language == "en"
                else f"{self._digits(added)} مورد به صف اضافه شد"
            )
        else:
            self.toast.show_message(self._t("این لینک‌ها از قبل در صف هستند"))
        return added

    def _paste_queue_urls(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            self.toast.show_message(self._t("کلیپ‌بورد خالی است"))
            return
        existing = self.queue_urls_edit.toPlainText().strip()
        self.queue_urls_edit.setPlainText(f"{existing}\n{text}".strip())

    def _add_queue_page_urls(self) -> None:
        urls = [line.strip() for line in self.queue_urls_edit.toPlainText().splitlines() if line.strip()]
        if not urls:
            self.toast.show_message(self._t("حداقل یک لینک وارد کنید"))
            return
        if self._add_urls_to_later(urls):
            self.queue_urls_edit.clear()

    def _add_current_to_later(self) -> None:
        urls = self._urls()
        if not urls:
            self.toast.show_message(self._t("حداقل یک لینک وارد کنید"))
            return
        self._add_urls_to_later(urls)

    def _later_duration_text(self, entry: dict[str, Any]) -> str:
        duration = entry.get("duration")
        if duration not in (None, "", 0, 0.0):
            return human_seconds(duration)
        if str(entry.get("metadata_status") or "") == "loading":
            return self._t("در حال دریافت اطلاعات…")
        return "—"

    def _later_size_text(self, entry: dict[str, Any]) -> str:
        size = entry.get("size_bytes")
        if size not in (None, "", 0, 0.0):
            confidence = self._size_confidence_label(str(entry.get("size_confidence") or "unknown"))
            return f"{human_bytes(size)} · {confidence}"
        status = str(entry.get("metadata_status") or "")
        if status == "recalculating":
            return self._t("در حال محاسبه حجم…")
        if status == "loading":
            return self._t("در حال دریافت اطلاعات…")
        return self._t("نامشخص")

    def _later_cached_info(self, url: str) -> dict[str, Any] | None:
        key = str(url or "").strip()
        if not key:
            return None
        cached = self._later_metadata_cache.get(key)
        if isinstance(cached, dict):
            return dict(cached)
        for result in self.preview_results:
            if str(result.get("url") or "").strip() != key:
                continue
            info = result.get("info")
            if isinstance(info, dict) and info.get("formats"):
                self._later_metadata_cache[key] = dict(info)
                return dict(info)
        return None

    def _later_preset_changed(self, source_index: int, preset_key: str) -> None:
        preset_key = str(preset_key or "").strip()
        if preset_key not in PRESETS:
            return
        entries = self.later_store.load()
        if source_index < 0 or source_index >= len(entries):
            return
        entry = dict(entries[source_index])
        old_preset = str(entry.get("preset") or "auto")
        if old_preset == preset_key:
            return

        updates = {
            "preset": preset_key,
            "preset_label": PRESETS[preset_key].label(self.language),
            "size_bytes": None,
            "size_confidence": "unknown",
            "metadata_status": "recalculating",
            "metadata_error": "",
        }
        if not self.later_store.update_index(source_index, updates):
            return
        entry.update(updates)

        info = self._later_cached_info(str(entry.get("url") or ""))
        if info is not None:
            estimate = estimate_selected_media_size(
                info,
                preset_key,
                str(entry.get("audio_language") or ""),
            )
            self.later_store.update_index(source_index, {
                "size_bytes": estimate.get("bytes"),
                "size_confidence": str(estimate.get("confidence") or "unknown"),
                "metadata_status": "ready",
            })
            self._refresh_later_table()
            return

        self._refresh_later_table()
        self._start_later_metadata_fetch([entry])

    def _refresh_later_table(self) -> None:
        if not hasattr(self, "later_table"):
            return
        entries = self.later_store.load()
        self.later_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = [
                self._format_history_time(entry.get("added_at")),
                str(entry.get("title") or entry.get("url") or "—"),
                self._later_duration_text(entry),
                self._later_size_text(entry),
                str(entry.get("service") or "—"),
                str(entry.get("preset_label") or entry.get("preset") or "—"),
                str(entry.get("output_dir") or "—"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(entry.get("url") or value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, dict(entry))
                    item.setData(Qt.ItemDataRole.UserRole + 1, row)
                self.later_table.setItem(row, column, item)

            quality_combo = QComboBox(self.later_table)
            quality_combo.setObjectName("queuePresetCombo")
            for key, preset in PRESETS.items():
                quality_combo.addItem(preset.label(self.language), key)
            self._compact_combo(quality_combo, 18)
            quality_combo.setMinimumWidth(150)
            quality_combo.setToolTip(self._t("کیفیت / فرمت"))
            quality_combo.blockSignals(True)
            try:
                self._set_combo_data(quality_combo, str(entry.get("preset") or "auto"))
            finally:
                quality_combo.blockSignals(False)
            quality_combo.currentIndexChanged.connect(
                lambda _index, combo=quality_combo, source_row=row:
                    self._later_preset_changed(source_row, str(combo.currentData() or "auto"))
            )
            self.later_table.setCellWidget(row, 5, quality_combo)
        self.later_table.resizeRowsToContents()

    def _refresh_later_metadata(self) -> None:
        self._refresh_later_table()
        self._refresh_missing_later_metadata()

    @staticmethod
    def _later_entry_key(entry: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(entry.get("url") or "").strip(),
            str(entry.get("preset") or "").strip(),
            str(entry.get("output_dir") or "").strip(),
        )

    def _refresh_missing_later_metadata(self) -> None:
        entries = [
            dict(item)
            for item in self.later_store.load()
            if str(item.get("metadata_status") or "") != "ready"
            and self._later_entry_key(item) not in self._later_metadata_active_keys
        ]
        # Older queue files have no metadata_status. Mark them as loading before
        # starting the worker so repeated refreshes do not start duplicates.
        for entry in entries:
            self.later_store.update_matching(
                str(entry.get("url") or ""),
                str(entry.get("preset") or ""),
                str(entry.get("output_dir") or ""),
                {"metadata_status": "loading"},
            )
            entry["metadata_status"] = "loading"
        if entries:
            self._refresh_later_table()
            self._start_later_metadata_fetch(entries)

    def _start_later_metadata_fetch(self, entries: list[dict[str, Any]]) -> None:
        batch: list[dict[str, Any]] = []
        for raw in entries:
            item = dict(raw)
            key = self._later_entry_key(item)
            if not key[0] or key in self._later_metadata_active_keys:
                continue
            self._later_metadata_active_keys.add(key)
            batch.append(item)
        if not batch:
            return
        urls = [str(item.get("url") or "").strip() for item in batch]
        try:
            auth_options, manual_cookie_text, manual_cookie_domain = self._collect_auth(urls)
            auth_options.update(self._collect_runtime_options(urls))
        except ValueError as exc:
            self._append_log(self._localized_error(str(exc)))
            auth_options, manual_cookie_text, manual_cookie_domain = {}, "", ""
        worker = PreviewWorker(urls, auth_options, manual_cookie_text, manual_cookie_domain, self.language)
        self.later_metadata_workers.append(worker)
        worker.ready.connect(lambda index, info, items=batch: self._later_metadata_ready(items, index, info))
        worker.failed.connect(lambda index, message, url, items=batch: self._later_metadata_failed(items, index, message, url))
        worker.finished.connect(lambda current=worker, items=batch: self._later_metadata_finished(current, items))
        worker.start()

    def _later_metadata_ready(self, batch: list[dict[str, Any]], index: int, info: dict[str, Any]) -> None:
        if not 0 <= index < len(batch):
            return
        entry = batch[index]
        url = str(entry.get("url") or "").strip()
        if url:
            self._later_metadata_cache[url] = dict(info)
        self._mark_active_auth_success([service_domain(url)])
        estimate = estimate_selected_media_size(
            info,
            str(entry.get("preset") or "auto"),
            str(entry.get("audio_language") or ""),
        )
        updates = {
            "title": str(info.get("title") or entry.get("title") or entry.get("url") or ""),
            "service": str(info.get("service") or entry.get("service") or "Other"),
            "domain": str(info.get("domain") or entry.get("domain") or ""),
            "duration": info.get("duration"),
            "size_bytes": estimate.get("bytes"),
            "size_confidence": str(estimate.get("confidence") or "unknown"),
            "metadata_status": "ready",
            "metadata_error": "",
        }
        self.later_store.update_matching(
            str(entry.get("url") or ""),
            str(entry.get("preset") or ""),
            str(entry.get("output_dir") or ""),
            updates,
        )
        self._refresh_later_table()

    def _later_metadata_failed(
        self,
        batch: list[dict[str, Any]],
        index: int,
        message: str,
        url: str,
    ) -> None:
        if not 0 <= index < len(batch):
            return
        entry = batch[index]
        self._mark_active_auth_invalid(str(message or ""), [service_domain(str(entry.get("url") or url))])
        self.later_store.update_matching(
            str(entry.get("url") or url),
            str(entry.get("preset") or ""),
            str(entry.get("output_dir") or ""),
            {"metadata_status": "failed", "metadata_error": str(message or "")},
        )
        self._refresh_later_table()

    def _later_metadata_finished(self, worker: PreviewWorker, batch: list[dict[str, Any]]) -> None:
        if worker in self.later_metadata_workers:
            self.later_metadata_workers.remove(worker)
        for entry in batch:
            self._later_metadata_active_keys.discard(self._later_entry_key(entry))
        worker.deleteLater()
        self._refresh_later_table()

    def _selected_later_entries(self) -> list[tuple[int, dict[str, Any]]]:
        if not hasattr(self, "later_table"):
            return []
        rows = sorted({index.row() for index in self.later_table.selectionModel().selectedRows()})
        entries: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            item = self.later_table.item(row, 0)
            data = item.data(Qt.ItemDataRole.UserRole) if item else None
            source_index = item.data(Qt.ItemDataRole.UserRole + 1) if item else row
            if isinstance(data, dict):
                entries.append((int(source_index), dict(data)))
        return entries

    def _load_later_selection(self) -> bool:
        selected = self._selected_later_entries()
        if not selected:
            self.toast.show_message(self._t("حداقل یک مورد را انتخاب کنید"))
            return False
        entries = [entry for _index, entry in selected]
        urls = [str(entry.get("url") or "").strip() for entry in entries]
        urls = [url for url in urls if url]
        if not urls:
            return False
        first = entries[0]
        self._append_urls(urls, replace=True)
        saved_preset = str(first.get("preset") or "")
        if saved_preset:
            self._set_combo_data(self.preset_combo, saved_preset)
        saved_output = str(first.get("output_dir") or "").strip()
        if saved_output:
            self.output_edit.setText(saved_output)
        self.organize_service_check.setChecked(bool(first.get("organize_service", True)))
        self._set_main_page_by_key("download")
        self.toast.show_message(self._t("موارد برای دانلود آماده شدند"))
        return True

    def _download_later_selection(self) -> None:
        if self._load_later_selection():
            QTimer.singleShot(100, self._start_download)

    def _remove_later_selection(self) -> None:
        selected = self._selected_later_entries()
        if not selected:
            self.toast.show_message(self._t("حداقل یک مورد را انتخاب کنید"))
            return
        self.later_store.remove_indexes(index for index, _entry in selected)
        self._refresh_later_table()
        self.toast.show_message(self._t("موارد انتخاب‌شده حذف شدند"))

    def _clear_later(self) -> None:
        if not self.later_store.load():
            return
        answer = QMessageBox.question(
            self,
            self._t("صف"),
            self._t("همهٔ موارد صف پاک شوند؟"),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.later_store.clear()
        self._refresh_later_table()

    def _start_search(self) -> None:
        if self.search_worker and self.search_worker.isRunning():
            return
        query = self.search_query_edit.text().strip()
        if not query:
            self.toast.show_message(self._t("عبارت جست‌وجو را وارد کنید"))
            return
        service_key = self._combo_data(self.search_service_combo, "youtube")
        base_url = "https://www.youtube.com/" if service_key == "youtube" else "https://soundcloud.com/"
        try:
            auth_options, manual_cookie_text, manual_cookie_domain = self._collect_auth([base_url])
            auth_options.update(self._collect_runtime_options([base_url]))
        except ValueError as exc:
            QMessageBox.warning(self, self._t("جست‌وجو"), self._localized_error(str(exc)))
            return
        self.search_button.setEnabled(False)
        self.search_status_label.setText(self._t("در حال جست‌وجو…"))
        self._clear_search_results(show_empty=False)
        self.search_worker = SearchWorker(
            service_key,
            query,
            self.search_limit_spin.value(),
            auth_options,
            manual_cookie_text,
            manual_cookie_domain,
            self.language,
        )
        self.search_worker.ready.connect(self._render_search_results)
        self.search_worker.failed.connect(self._search_failed)
        self.search_worker.finished.connect(lambda: self.search_button.setEnabled(True))
        self.search_worker.start()

    def _clear_search_results(self, *, show_empty: bool = True) -> None:
        for worker in self.search_thumbnail_workers:
            if worker.isRunning():
                worker.requestInterruption()
        self.search_thumbnail_workers.clear()
        self.search_cards.clear()
        self.search_results.clear()
        while self.search_results_layout.count():
            item = self.search_results_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if show_empty:
            self.search_results_empty = ResponsiveLabel(self._t("هنوز نتیجه‌ای وجود ندارد."))
            self.search_results_empty.setObjectName("muted")
            self.search_results_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.search_results_layout.addWidget(self.search_results_empty)
        self.search_results_layout.addStretch(1)

    def _render_search_results(self, results: list[dict[str, Any]]) -> None:
        self._mark_active_auth_success()
        self._clear_search_results(show_empty=False)
        self.search_results = [dict(item) for item in results if isinstance(item, dict)]
        if not self.search_results:
            self.search_status_label.setText(self._t("نتیجه‌ای پیدا نشد."))
            self._clear_search_results(show_empty=True)
            return
        self.search_status_label.setText(
            (f"{len(self.search_results)} results found" if self.language == "en" else f"{self._digits(len(self.search_results))} نتیجه پیدا شد")
        )
        # Remove the stretch inserted by _clear_search_results.
        if self.search_results_layout.count():
            self.search_results_layout.takeAt(self.search_results_layout.count() - 1)
        for result in self.search_results:
            card = SearchResultCard(result, self.language)
            card.download_requested.connect(lambda url, c=card: self._download_search_urls([url]))
            card.add_requested.connect(lambda url, c=card: self._add_search_urls([url]))
            card.later_requested.connect(lambda url, c=card: self._add_urls_to_later([url], result_map={url: c.result}))
            self.search_cards.append(card)
            self.search_results_layout.addWidget(card)
            thumbnail = str(result.get("thumbnail") or "").strip()
            if thumbnail:
                worker = ThumbnailLoader(thumbnail)
                worker.loaded.connect(lambda data, target=card: self._set_search_thumbnail(target, data))
                worker.finished.connect(lambda current=worker: self._search_thumbnail_finished(current))
                self.search_thumbnail_workers.append(worker)
                worker.start()
        self.search_results_layout.addStretch(1)

    def _set_search_thumbnail(self, card: SearchResultCard, data: QByteArray) -> None:
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            card.image.setPixmap(
                pixmap.scaled(
                    card.image.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def _search_thumbnail_finished(self, worker: ThumbnailLoader) -> None:
        if worker in self.search_thumbnail_workers:
            self.search_thumbnail_workers.remove(worker)
        worker.deleteLater()

    def _search_failed(self, message: str) -> None:
        self._mark_active_auth_invalid(message)
        self.search_status_label.setText(self._t("جست‌وجو ناموفق بود"))
        self._clear_search_results(show_empty=True)
        self._append_log(("Search error: " if self.language == "en" else "خطای جست‌وجو: ") + message)
        QMessageBox.warning(self, self._t("جست‌وجو"), message)

    def _select_all_search_results(self, selected: bool) -> None:
        for card in self.search_cards:
            card.select_check.setChecked(selected)

    def _selected_search_urls(self) -> list[str]:
        return [card.url for card in self.search_cards if card.is_selected() and card.url]

    def _add_search_urls(self, urls: list[str]) -> None:
        self._append_urls(urls, replace=False)
        self._set_main_page(0)
        self.toast.show_message(self._t("نتیجه‌ها به دانلودها اضافه شدند"))

    def _download_search_urls(self, urls: list[str]) -> None:
        self._append_urls(urls, replace=True)
        self._set_main_page(0)
        QTimer.singleShot(80, self._start_download)

    def _download_selected_search_results(self) -> None:
        urls = self._selected_search_urls()
        if not urls:
            self.toast.show_message(self._t("حداقل یک نتیجه را انتخاب کنید"))
            return
        self._download_search_urls(urls)

    def _later_selected_search_results(self) -> None:
        urls = self._selected_search_urls()
        if not urls:
            self.toast.show_message(self._t("حداقل یک نتیجه را انتخاب کنید"))
            return
        result_map = {str(item.get("url") or ""): item for item in self.search_results}
        self._add_urls_to_later(urls, result_map=result_map)

    def _format_history_time(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return "—"
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.strftime("%Y-%m-%d  %H:%M")
        except ValueError:
            return text

    def _refresh_history_table(self) -> None:
        if not hasattr(self, "history_table"):
            return
        entries = self.history_store.load()
        self.history_table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = [
                self._format_history_time(entry.get("downloaded_at")),
                str(entry.get("title") or entry.get("url") or "—"),
                str(entry.get("service") or "—"),
                str(entry.get("preset_label") or entry.get("preset") or "—"),
                str(entry.get("output_dir") or "—"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, dict(entry))
                self.history_table.setItem(row, column, item)
        self.history_table.resizeRowsToContents()

    def _selected_history_entries(self) -> list[dict[str, Any]]:
        rows = sorted({index.row() for index in self.history_table.selectionModel().selectedRows()})
        entries: list[dict[str, Any]] = []
        for row in rows:
            item = self.history_table.item(row, 0)
            data = item.data(Qt.ItemDataRole.UserRole) if item else None
            if isinstance(data, dict):
                entries.append(dict(data))
        return entries

    def _redownload_history_selection(self, *_args: object) -> None:
        urls = [str(item.get("url") or "").strip() for item in self._selected_history_entries()]
        urls = [url for url in urls if url]
        if not urls:
            self.toast.show_message(self._t("یک مورد از تاریخچه انتخاب کنید"))
            return
        self._append_urls(urls, replace=True)
        self._set_main_page(0)
        self.toast.show_message(self._t("لینک‌های تاریخچه برای دانلود آماده شدند"))

    def _open_history_folder(self) -> None:
        entries = self._selected_history_entries()
        if not entries:
            self.toast.show_message(self._t("یک مورد از تاریخچه انتخاب کنید"))
            return
        folder = str(entries[0].get("output_dir") or "").strip()
        if folder and Path(folder).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            self.toast.show_message(self._t("پوشهٔ ذخیره پیدا نشد"))

    def _copy_history_url(self) -> None:
        entries = self._selected_history_entries()
        urls = [str(item.get("url") or "").strip() for item in entries]
        urls = [url for url in urls if url]
        if not urls:
            self.toast.show_message(self._t("یک مورد از تاریخچه انتخاب کنید"))
            return
        QApplication.clipboard().setText("\n".join(urls))
        self.toast.show_message(self._t("لینک کپی شد"))

    def _clear_history(self) -> None:
        if not self.history_store.load():
            return
        answer = QMessageBox.question(
            self,
            self._t("پاک‌کردن تاریخچه"),
            self._t("همهٔ سوابق دانلود حذف شوند؟ فایل‌های دانلودشده حذف نمی‌شوند."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.history_store.clear()
        self._refresh_history_table()
        self.toast.show_message(self._t("تاریخچه پاک شد"))

    def _package_description(self, key: str) -> str:
        descriptions = {
            "yt_dlp": "هستهٔ اصلی دانلود و استخراج رسانه از سرویس‌های پشتیبانی‌شده",
            "yt_dlp_ejs": "اجزای JavaScript لازم برای چالش‌های جدید YouTube",
            "curl_cffi": "شبیه‌سازی مرورگر برای سازگاری بهتر با سایت‌های محدودشده",
            "gallery_dl": "دانلود عکس، GIF و گالری‌های Reddit و Instagram",
            "spotdl": "پردازش لینک‌های Spotify و یافتن فایل صوتی منطبق",
            "apkeep": "دانلود APK از APKPure، F-Droid، Google Play و AppGallery",
            "ffmpeg": "ادغام ویدئو و صدا و تبدیل فرمت فایل‌ها",
            "deno": "اجرای JavaScript موردنیاز YouTube و بعضی استخراج‌کننده‌ها",
            "pyinstaller": "ساخت نسخهٔ اجرایی Windows از سورس Python",
        }
        return self._t(descriptions.get(key, "ابزار کمکی LeonDL"))

    @staticmethod
    def _package_action_for_key(key: str, installed: bool) -> str:
        mode = "update" if installed else "install"
        return {
            "yt_dlp": f"{mode}_yt_dlp",
            "yt_dlp_ejs": f"{mode}_yt_dlp_ejs",
            "curl_cffi": f"{mode}_curl_cffi",
            "gallery_dl": f"{mode}_gallery_dl",
            "spotdl": f"{mode}_spotdl",
            "apkeep": f"{mode}_apkeep",
            "ffmpeg": f"{mode}_ffmpeg",
            "deno": f"{mode}_deno",
            "pyinstaller": f"{mode}_pyinstaller",
        }.get(key, "")

    def _package_action_available(self, key: str) -> tuple[bool, str]:
        if getattr(sys, "frozen", False) and key in {"yt_dlp", "yt_dlp_ejs", "curl_cffi", "pyinstaller"}:
            return False, self._t("در نسخهٔ EXE، این ابزار همراه نسخهٔ جدید LeonDL به‌روزرسانی می‌شود.")
        if key in {"ffmpeg", "deno", "apkeep"} and os.name != "nt":
            return False, self._t("نصب خودکار این ابزار فقط در Windows در دسترس است.")
        if os.name == "nt" and key in {"ffmpeg", "deno"} and not shutil.which("winget"):
            return False, self._t("WinGet برای نصب یا به‌روزرسانی این ابزار پیدا نشد.")
        if getattr(sys, "frozen", False) and key == "gallery_dl" and not shutil.which("winget"):
            return False, self._t("WinGet برای نصب یا به‌روزرسانی این ابزار پیدا نشد.")
        return True, ""

    def _refresh_package_status(self) -> None:
        if not hasattr(self, "package_table"):
            return
        if self.package_status_worker and self.package_status_worker.isRunning():
            return
        if hasattr(self, "package_refresh_button"):
            self.package_refresh_button.setEnabled(False)
            self.package_refresh_button.setText(self._t("در حال بررسی کامل سیستم…"))
        self.package_table.clearContents()
        self.package_table.setRowCount(1)
        checking_item = QTableWidgetItem(self._t("در حال بررسی محیط Python، PATH، ابزارهای محلی و WinGet…"))
        checking_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.package_table.setSpan(0, 0, 1, self.package_table.columnCount())
        self.package_table.setItem(0, 0, checking_item)
        self.package_status_worker = PackageStatusWorker()
        self.package_status_worker.ready.connect(self._render_package_status)
        self.package_status_worker.failed.connect(self._package_status_failed)
        self.package_status_worker.start()

    def _package_status_failed(self, message: str) -> None:
        self.package_table.clearSpans()
        self.package_table.setRowCount(0)
        self.package_log.appendPlainText(message)
        if hasattr(self, "package_refresh_button"):
            self.package_refresh_button.setEnabled(True)
            self.package_refresh_button.setText(self._t("بررسی کامل سیستم"))

    def _render_package_status(self, statuses: list[dict[str, Any]]) -> None:
        self.package_table.clearSpans()
        self.package_table.clearContents()
        self.package_table.setRowCount(len(statuses))
        if hasattr(self, "package_refresh_button"):
            self.package_refresh_button.setEnabled(True)
            self.package_refresh_button.setText(self._t("بررسی کامل سیستم"))
        self.package_action_buttons: list[QPushButton] = []
        for row, status in enumerate(statuses):
            key = str(status.get("key") or "")
            installed = bool(status.get("installed"))
            name = str(status.get("name") or key or "—")
            detail = str(status.get("detail") or "")
            source = str(status.get("source") or "")
            values = [
                name,
                self._package_description(key),
                self._t("نصب است") if installed else self._t("نصب نیست"),
                str(status.get("version") or "—"),
                str(status.get("path") or "—"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip("\n".join(part for part in (detail, source, value) if part))
                if column == 2:
                    item.setForeground(QColor(self.theme.success if installed else self.theme.danger))
                self.package_table.setItem(row, column, item)

            action = self._package_action_for_key(key, installed)
            action_button = QPushButton(self._t("به‌روزرسانی") if installed else self._t("نصب"))
            action_button.setMinimumWidth(96)
            action_button.setMinimumHeight(34)
            action_button.setProperty("packageAction", True)
            available, unavailable_reason = self._package_action_available(key)
            action_button.setEnabled(bool(action) and available)
            if unavailable_reason:
                action_button.setToolTip(unavailable_reason)
            elif action:
                action_button.setToolTip(
                    (self._t("به‌روزرسانی {tool}") if installed else self._t("نصب {tool}")).format(tool=name)
                )
                action_button.clicked.connect(
                    lambda checked=False, selected_action=action: self._run_package_action(selected_action)
                )
            self.package_table.setCellWidget(row, 5, action_button)
            self.package_action_buttons.append(action_button)

        self.package_table.resizeRowsToContents()
        for row in range(self.package_table.rowCount()):
            self.package_table.setRowHeight(row, max(self.package_table.rowHeight(row), 40))
        self._sync_package_table_height()
        self._detect_runtime()

    def _sync_package_table_height(self) -> None:
        if not hasattr(self, "package_table"):
            return
        table = self.package_table
        header_height = table.horizontalHeader().height()
        frame = table.frameWidth() * 2
        row_count = table.rowCount()
        visible_rows = min(max(row_count, 4), 8)
        rows_height = sum(table.rowHeight(row) for row in range(visible_rows))
        extra = table.horizontalScrollBar().sizeHint().height() if table.horizontalScrollBar().isVisible() else 0
        minimum = header_height + rows_height + frame + extra + 6
        table.setMinimumHeight(max(230, minimum))

    def _run_package_action(self, action: str) -> None:
        if self.package_action_worker and self.package_action_worker.isRunning():
            self.toast.show_message(self._t("یک عملیات نصب یا به‌روزرسانی در حال اجراست"))
            return
        if action in {"install_deno", "update_deno", "install_ffmpeg", "update_ffmpeg", "install_apkeep", "update_apkeep"} and os.name != "nt":
            self.toast.show_message(self._t("این نصب خودکار فقط در ویندوز در دسترس است"))
            return
        self.package_log.clear()
        for button in getattr(self, "package_action_buttons", []):
            button.setEnabled(False)
        self.package_action_worker = PackageActionWorker(action)
        self.package_action_worker.log.connect(self.package_log.appendPlainText)
        self.package_action_worker.finished_action.connect(self._package_action_finished)
        self.package_action_worker.start()

    def _package_action_finished(self, ok: bool, message: str) -> None:
        self.package_log.appendPlainText(message)
        self.toast.show_message(self._t("عملیات با موفقیت انجام شد") if ok else self._t("عملیات ناموفق بود"))
        QTimer.singleShot(300, self._refresh_package_status)


    def _choose_output_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, self._t("انتخاب پوشهٔ ذخیره"), self.output_edit.text())
        if selected:
            self.output_edit.setText(selected)

    def _choose_cookie_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self._t("انتخاب فایل cookies.txt"),
            self.cookie_file_edit.text() or str(Path.home()),
            "Cookie files (*.txt);;All files (*)",
        )
        if selected:
            self.cookie_file_edit.setText(selected)

    def _choose_runtime_file(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self._t("انتخاب موتور JavaScript"),
            self.runtime_path_edit.text() or str(Path.home()),
            "Executable files (*.exe);;All files (*)",
        )
        if selected:
            self.runtime_path_edit.setText(selected)
            self._detect_runtime()

    def _selected_runtime_key(self) -> str:
        return self._combo_data(self.runtime_combo, "auto")

    def _detect_runtime(self, *_args) -> None:
        if not hasattr(self, "runtime_status"):
            return
        runtime = resolve_javascript_runtime(
            self._selected_runtime_key(),
            self.runtime_path_edit.text().strip(),
        )
        ejs_text = self._t("بستهٔ EJS نصب است") if ejs_package_available() else self._t("EJS محلی نصب نیست؛ حالت دریافت رسمی فعال می‌شود")
        if runtime:
            display_name = {"deno": "Deno", "node": "Node.js", "quickjs": "QuickJS"}.get(runtime["name"], runtime["name"])
            self.runtime_status.setText(
                (f"✓ {display_name} detected — {runtime['version']}\n{runtime['path']}\n{ejs_text}" if self.language == "en" else f"✓ {display_name} شناسایی شد — {runtime['version']}\n{runtime['path']}\n{ejs_text}")
            )
            self.runtime_status.setProperty("runtimeOk", True)
        else:
            self.runtime_status.setText(
                ("✕ No compatible runtime found. Install Deno or choose deno.exe." if self.language == "en" else "✕ موتور سازگار پیدا نشد. روی «نصب Deno» بزن یا مسیر deno.exe را انتخاب کن.")
            )
            self.runtime_status.setProperty("runtimeOk", False)
        self.runtime_status.style().unpolish(self.runtime_status)
        self.runtime_status.style().polish(self.runtime_status)

    def _install_deno(self) -> None:
        if os.name != "nt" or not shutil.which("winget"):
            QApplication.clipboard().setText("winget install --id=DenoLand.Deno -e")
            QMessageBox.information(
                self,
                self._t("نصب Deno"),
                self._t("دستور نصب در کلیپ‌بورد کپی شد:\n\nwinget install --id=DenoLand.Deno -e\n\nپس از نصب، برنامه را کامل ببند و دوباره اجرا کن."),
            )
            return
        answer = QMessageBox.question(
            self,
            self._t("نصب Deno"),
            self._t("WinGet برای نصب Deno اجرا شود؟ پس از پایان نصب، برنامه را یک‌بار ببند و دوباره باز کن."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        started = QProcess.startDetached(
            "winget",
            [
                "install", "--id=DenoLand.Deno", "-e",
                "--accept-package-agreements", "--accept-source-agreements",
            ],
        )
        if isinstance(started, tuple):
            started = bool(started[0])
        if started:
            self.toast.show_message(self._t("نصب Deno آغاز شد؛ بعد از پایان برنامه را دوباره باز کن"))
        else:
            QMessageBox.warning(self, self._t("نصب Deno"), self._t("اجرای WinGet ناموفق بود. دستور نصب را دستی اجرا کن."))

    @staticmethod
    def _urls_need_javascript(urls: list[str]) -> bool:
        return any(any(host in url.lower() for host in ("youtube.com", "youtu.be", "youtube-nocookie.com")) for url in urls)

    def _collect_runtime_options(self, urls: list[str]) -> dict[str, Any]:
        try:
            options, runtime = javascript_runtime_options(
                self._selected_runtime_key(),
                self.runtime_path_edit.text().strip(),
                require_runtime=self._urls_need_javascript(urls),
            )
        except RuntimeError as exc:
            raise ValueError(str(exc)) from exc
        if runtime:
            self._append_log(("JavaScript runtime: " if self.language == "en" else "موتور JavaScript: ") + f"{runtime['name']} — {runtime['version']}")
        if any(is_spotify_url(url) for url in urls) and hasattr(self, "spotify_proxy_edit"):
            proxy = self.spotify_proxy_edit.text().strip()
            if proxy:
                options["_leon_spotify_proxy"] = proxy
        return options

    def _paste_cookie_text(self) -> None:
        text = QApplication.clipboard().text().strip()
        if not text:
            self.toast.show_message(self._t("کلیپ‌بورد خالی است"))
            return
        self.manual_cookie_edit.setPlainText(text)
        self.toast.show_message(self._t("اطلاعات کوکی وارد شد"))

    def _validate_manual_cookie(self) -> None:
        urls = self._urls()
        domain = normalize_cookie_domain(self.cookie_domain_edit.text(), urls[0] if urls else "")
        try:
            normalized = cookie_text_to_netscape(self.manual_cookie_edit.toPlainText(), domain)
        except InvalidCookieText as exc:
            QMessageBox.warning(self, self._t("قالب کوکی نامعتبر"), self._localized_error(str(exc)))
            return
        count = sum(
            1
            for line in normalized.splitlines()
            if line and (not line.startswith("#") or line.startswith("#HttpOnly_"))
        )
        self.toast.show_message((f"Valid cookie format; {count} cookies detected" if self.language == "en" else f"قالب کوکی معتبر است؛ {fa_digits(count)} مورد شناسایی شد"))

    def _toggle_auth_controls(self, index: int) -> None:
        if hasattr(self, "auth_stack"):
            self.auth_stack.setCurrentIndex(max(0, min(index, self.auth_stack.count() - 1)))

    def _request_auth_override(self, *_args) -> None:
        self._auth_override_requested = True
        if hasattr(self, "auth_profile_status"):
            self._set_auth_profile_status(
                self._t("روش جدید انتخاب شده است و پس از اولین موفقیت جایگزین روش قبلی می‌شود."),
                "idle",
            )

    def _set_auth_profile_status(self, text: str, state: str = "idle") -> None:
        if not hasattr(self, "auth_profile_status"):
            return
        self.auth_profile_status.setText(text)
        self.auth_profile_status.setProperty("authProfileState", state)
        self.auth_profile_status.style().unpolish(self.auth_profile_status)
        self.auth_profile_status.style().polish(self.auth_profile_status)

    def _profile_method_label(self, method: str) -> str:
        labels = {
            "browser": self._t("خواندن مستقیم از مرورگر"),
            "extension": self._t("کوکی دریافت‌شده از افزونه Chrome"),
            "file": self._t("انتخاب فایل cookies.txt"),
            "manual": self._t("ورود دستی اطلاعات کوکی"),
        }
        return labels.get(method, self._t("بدون کوکی"))

    def _refresh_saved_auth_status(self, *_args) -> None:
        if not hasattr(self, "remember_auth_check"):
            return
        # Extension cookies are written by the short-lived native-host process.
        # Always reload the profile index before painting Settings or choosing a
        # cookie source so the GUI never reports stale "not received" state.
        self.auth_store.refresh(force=True)
        urls = self._urls()
        domains = domains_for_urls(urls)

        if hasattr(self, "extension_cookie_status"):
            if len(domains) != 1:
                self.extension_cookie_status.setText(
                    self._t("برای بررسی کوکی افزونه، یک لینک از همان سایت وارد کن.")
                )
            else:
                domain = domains[0]
                extension_profile = self.auth_store.profile(domain, valid_only=False)
                if not extension_profile or str(extension_profile.get("method") or "") != "extension":
                    self.extension_cookie_status.setText(
                        self._t("هنوز کوکی افزونه‌ای برای {domain} ذخیره نشده است.").format(domain=domain)
                    )
                else:
                    secret_path = Path(str(extension_profile.get("secret_file") or "")).expanduser()
                    cookie_path = Path(str(extension_profile.get("cookie_file") or "")).expanduser()
                    payload_exists = secret_path.is_file() or cookie_path.is_file()
                    if not payload_exists:
                        self.extension_cookie_status.setText(
                            self._t("رکورد کوکی افزونه برای {domain} وجود دارد، اما فایل امن آن پیدا نشد؛ لینک را دوباره همراه Cookie ارسال کن.").format(domain=domain)
                        )
                    elif bool(extension_profile.get("valid", False)):
                        self.extension_cookie_status.setText(
                            self._t("کوکی افزونه برای {domain} آماده است و به‌صورت امن استفاده می‌شود.").format(domain=domain)
                        )
                    else:
                        self.extension_cookie_status.setText(
                            self._t("کوکی افزونه برای {domain} دریافت شده و پس از اولین پیش‌نمایش یا دانلود موفق تأیید می‌شود.").format(domain=domain)
                        )

        if not self.remember_auth_check.isChecked():
            self._set_auth_profile_status(self._t("استفادهٔ خودکار از احراز هویت ذخیره‌شده غیرفعال است."), "idle")
            return
        if len(domains) != 1:
            self._set_auth_profile_status(self._t("برای نمایش روش ذخیره‌شده، لینک یک سایت را وارد کن."), "idle")
            return
        domain = domains[0]
        profile = self.auth_store.profile(domain, valid_only=False)
        if not profile:
            self._set_auth_profile_status(self._t("هنوز روش موفقی برای این سایت ذخیره نشده است."), "idle")
            return
        profile_method = str(profile.get("method") or "none")
        method = self._profile_method_label(profile_method)
        if bool(profile.get("valid", False)):
            value = self._t("روش ذخیره‌شده برای {domain}: {method}").format(domain=domain, method=method)
            self._set_auth_profile_status(value, "ready")
        elif profile_method == "extension":
            value = self._t("کوکی افزونه برای {domain} دریافت شده و در انتظار تأیید است.").format(domain=domain)
            self._set_auth_profile_status(value, "idle")
        else:
            value = self._t("روش ذخیره‌شده برای {domain} نیاز به به‌روزرسانی دارد.").format(domain=domain)
            self._set_auth_profile_status(value, "warning")

    def _clear_saved_auth_for_current_domain(self) -> None:
        domains = domains_for_urls(self._urls())
        if domains:
            removed = False
            for domain in domains:
                removed = self.auth_store.remove(domain) or removed
            if removed:
                self.toast.show_message(self._t("احراز هویت ذخیره‌شده حذف شد"))
            else:
                self.toast.show_message(self._t("احراز هویت ذخیره‌شده‌ای برای این سایت وجود ندارد"))
        else:
            answer = QMessageBox.question(
                self,
                self._t("حذف احراز هویت ذخیره‌شده"),
                self._t("لینکی وارد نشده است. همهٔ روش‌های احراز هویت ذخیره‌شده حذف شوند؟"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.auth_store.clear()
                self.toast.show_message(self._t("همهٔ روش‌های احراز هویت ذخیره‌شده حذف شدند"))
        self._refresh_saved_auth_status()

    @staticmethod
    def _looks_like_auth_error(message: str) -> bool:
        value = (message or "").lower()
        markers = (
            "sign in", "login required", "authentication", "cookies", "cookie",
            "not a bot", "confirm you", "account required", "http error 401",
            "http error 403", "unauthorized", "forbidden", "session expired",
            "وارد حساب", "کوکی", "احراز هویت", "ربات",
        )
        return any(marker in value for marker in markers)

    def _apply_saved_profile_to_ui(self, profile: dict[str, Any]) -> None:
        method = str(profile.get("method") or "none")
        self._set_combo_data(self.auth_combo, method)
        if method == "browser":
            browser = str(profile.get("browser") or "Chrome")
            if browser in BROWSERS:
                self._set_combo(self.browser_combo, browser)
            self.browser_profile_edit.setText(str(profile.get("browser_profile") or ""))
        elif method == "extension":
            if hasattr(self, "extension_cookie_status"):
                self.extension_cookie_status.setText(self._t("کوکی افزونه برای این دامنه آماده است و به‌صورت امن استفاده می‌شود."))
        elif method == "file":
            self.cookie_file_edit.setText(str(profile.get("cookie_file") or ""))
        elif method == "manual":
            self.cookie_domain_edit.setText(str(profile.get("cookie_domain") or ""))
            previous = self.manual_cookie_edit.blockSignals(True)
            try:
                self.manual_cookie_edit.clear()
                self.manual_cookie_edit.setPlaceholderText(self._t("کوکی رمزگذاری‌شدهٔ ذخیره‌شده به‌صورت خودکار استفاده می‌شود."))
            finally:
                self.manual_cookie_edit.blockSignals(previous)
        self._toggle_auth_controls(self.auth_combo.currentIndex())

    def _auth_from_saved_profile(self, domain: str, profile: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        method = str(profile.get("method") or "none")
        if method == "browser":
            browser_label = str(profile.get("browser") or "")
            browser = BROWSERS.get(browser_label, browser_label.lower() or None)
            if not browser:
                raise AuthStoreError(self._t("مرورگر ذخیره‌شده معتبر نیست."))
            profile_name = str(profile.get("browser_profile") or "").strip() or None
            return {"cookiesfrombrowser": (browser, profile_name, None, None)}, "", ""
        if method == "extension":
            cookie_domain = str(profile.get("cookie_domain") or domain)
            if str(profile.get("secret_file") or "").strip():
                raw_text = self.auth_store.read_manual_secret(profile)
                cookie_text_to_netscape(raw_text, cookie_domain)
                return {}, raw_text, cookie_domain
            path = Path(str(profile.get("cookie_file") or "")).expanduser()
            if not path.is_file():
                raise AuthStoreError(self._t("کوکی دریافت‌شده از افزونه پیدا نشد؛ دوباره لینک را همراه Cookie از افزونه ارسال کن."))
            return {"cookiefile": str(path)}, "", ""
        if method == "file":
            path = Path(str(profile.get("cookie_file") or "")).expanduser()
            if not path.is_file():
                raise AuthStoreError(self._t("فایل کوکی ذخیره‌شده پیدا نشد."))
            return {"cookiefile": str(path)}, "", ""
        if method == "manual":
            raw_text = self.auth_store.read_manual_secret(profile)
            cookie_domain = str(profile.get("cookie_domain") or domain)
            cookie_text_to_netscape(raw_text, cookie_domain)
            return {}, raw_text, cookie_domain
        return {}, "", ""

    def _mark_active_auth_success(self, domains: list[str] | None = None) -> None:
        targets = list(dict.fromkeys([*(self._active_auth_domains or []), *((domains or []))]))
        bridge_pending = any(domain in self._browser_auth_validation_domains for domain in targets)
        remember_enabled = bool(getattr(self, "remember_auth_check", None) and self.remember_auth_check.isChecked())
        if not remember_enabled and not bridge_pending:
            return
        if not targets or self._active_auth_method == "none":
            return
        self.auth_store.mark_valid(targets)
        self._browser_auth_validation_domains.difference_update(targets)
        self._active_auth_pending = False
        self._auth_override_requested = False
        self._set_auth_profile_status(
            self._t("احراز هویت با موفقیت تأیید و برای استفاده‌های بعدی ذخیره شد."),
            "ready",
        )

    def _mark_active_auth_invalid(self, message: str, domains: list[str] | None = None) -> None:
        if not self._looks_like_auth_error(message):
            return
        targets = list(dict.fromkeys([*(self._active_auth_domains or []), *((domains or []))]))
        if not targets or self._active_auth_method == "none":
            return
        self.auth_store.mark_invalid(targets)
        self._browser_auth_validation_domains.difference_update(targets)
        self._set_auth_profile_status(
            self._t("کوکی یا نشست ذخیره‌شده معتبر نیست؛ لطفاً آن را به‌روزرسانی کن."),
            "warning",
        )

    def _collect_auth(self, urls: list[str] | None = None) -> tuple[dict[str, Any], str, str]:
        self.auth_store.refresh(force=True)
        active_urls = list(urls or self._urls())
        domains = domains_for_urls(active_urls)
        self._active_auth_domains = domains
        self._active_auth_method = "none"
        self._active_auth_auto_used = False
        self._active_auth_pending = False

        if len(domains) == 1 and domains[0] in self._browser_auth_validation_domains:
            domain = domains[0]
            profile = self.auth_store.profile(domain, valid_only=False)
            if profile:
                try:
                    result = self._auth_from_saved_profile(domain, profile)
                except (AuthStoreError, InvalidCookieText) as exc:
                    self.auth_store.mark_invalid([domain])
                    self._browser_auth_validation_domains.discard(domain)
                    self._set_auth_profile_status(self._localized_error(str(exc)), "warning")
                else:
                    self._active_auth_domains = [domain]
                    self._active_auth_method = "extension"
                    self._active_auth_auto_used = True
                    self._active_auth_pending = True
                    self._apply_saved_profile_to_ui({**profile, "method": "extension"})
                    self._set_auth_profile_status(
                        self._t("کوکی دریافت‌شده از افزونه پس از اولین پیش‌نمایش یا دانلود موفق تأیید می‌شود."),
                        "idle",
                    )
                    return result

        if self.remember_auth_check.isChecked() and not self._auth_override_requested:
            saved = self.auth_store.profile_for_urls(active_urls, valid_only=True)
            if saved:
                domain, profile = saved
                try:
                    result = self._auth_from_saved_profile(domain, profile)
                except (AuthStoreError, InvalidCookieText) as exc:
                    self.auth_store.mark_invalid([domain])
                    self._set_auth_profile_status(self._localized_error(str(exc)), "warning")
                else:
                    self._active_auth_domains = [domain]
                    self._active_auth_method = str(profile.get("method") or "none")
                    self._active_auth_auto_used = True
                    self._apply_saved_profile_to_ui(profile)
                    method = self._profile_method_label(self._active_auth_method)
                    self._set_auth_profile_status(
                        self._t("استفادهٔ خودکار از روش ذخیره‌شده برای {domain}: {method}").format(
                            domain=domain, method=method
                        ),
                        "ready",
                    )
                    return result

        source = self._combo_data(self.auth_combo, "none")
        self._active_auth_method = source
        if source == "none":
            return {}, "", ""

        if source == "browser":
            browser_label = self.browser_combo.currentText()
            browser = BROWSERS.get(browser_label)
            if not browser:
                raise ValueError(self._t("یک مرورگر معتبر انتخاب کنید."))
            profile = self.browser_profile_edit.text().strip() or None
            if self.remember_auth_check.isChecked() and domains:
                self.auth_store.remember_browser(domains, browser_label, profile)
                self._active_auth_pending = True
                self._set_auth_profile_status(self._t("روش انتخاب‌شده پس از اولین پیش‌نمایش یا دانلود موفق فعال می‌شود."), "idle")
            return {"cookiesfrombrowser": (browser, profile, None, None)}, "", ""

        if source == "extension":
            if len(domains) != 1:
                raise ValueError(self._t("برای استفاده از کوکی افزونه، لینک‌های انتخاب‌شده باید متعلق به یک سایت باشند."))
            domain = domains[0]
            profile = self.auth_store.profile(domain, valid_only=False)
            if not profile or str(profile.get("method") or "") != "extension":
                raise ValueError(self._t("هنوز کوکی‌ای برای این سایت از افزونه دریافت نشده است؛ Send site cookies را فعال و لینک را دوباره به Leon ارسال کن."))
            try:
                result = self._auth_from_saved_profile(domain, profile)
            except (AuthStoreError, InvalidCookieText) as exc:
                self.auth_store.mark_invalid([domain])
                raise ValueError(self._localized_error(str(exc))) from exc
            self._active_auth_domains = [domain]
            self._active_auth_method = "extension"
            self._active_auth_pending = not bool(profile.get("valid", False))
            if hasattr(self, "extension_cookie_status"):
                self.extension_cookie_status.setText(self._t("کوکی افزونه برای این دامنه انتخاب شد."))
            return result

        if source == "file":
            path = Path(self.cookie_file_edit.text().strip()).expanduser()
            if not path.is_file():
                raise ValueError(self._t("فایل cookies.txt انتخاب‌شده پیدا نشد."))
            if self.remember_auth_check.isChecked() and domains:
                try:
                    path = self.auth_store.remember_cookie_file(domains, path)
                except AuthStoreError as exc:
                    raise ValueError(self._localized_error(str(exc))) from exc
                self.cookie_file_edit.setText(str(path))
                self._active_auth_pending = True
                self._set_auth_profile_status(self._t("روش انتخاب‌شده پس از اولین پیش‌نمایش یا دانلود موفق فعال می‌شود."), "idle")
            return {"cookiefile": str(path)}, "", ""

        manual_text = self.manual_cookie_edit.toPlainText().strip()
        first_url = (active_urls or [""])[0]
        domain = normalize_cookie_domain(self.cookie_domain_edit.text(), first_url)
        try:
            cookie_text_to_netscape(manual_text, domain)
        except InvalidCookieText as exc:
            raise ValueError(str(exc)) from exc
        if self.remember_auth_check.isChecked() and domains:
            try:
                self.auth_store.remember_manual(domains, manual_text, domain)
            except AuthStoreError as exc:
                raise ValueError(self._localized_error(str(exc))) from exc
            self._active_auth_pending = True
            self._set_auth_profile_status(self._t("روش انتخاب‌شده پس از اولین پیش‌نمایش یا دانلود موفق فعال می‌شود."), "idle")
        return {}, manual_text, domain

    def _open_output_folder(self) -> None:
        folder = Path(self.output_edit.text()).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _clear_preview_cards(self) -> None:
        while self.preview_list_layout.count():
            item = self.preview_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.preview_cards.clear()
        self.preview_results.clear()
        self.preview_empty_panel = None
        self.preview_empty_graphic = None
        self.preview_empty_label = None
        self.preview_success_count = 0
        self.preview_failure_count = 0
        self.detected_audio_languages.clear()
        self.detected_subtitle_languages.clear()
        if hasattr(self, "preview_size_summary"):
            self.preview_size_summary.setText(self._t("حجم کل انتخاب‌شده: —"))
            self.preview_size_summary.setToolTip(self._t("حجم بر اساس کیفیت، زبان صدا و فرمت فعلی محاسبه می‌شود."))
        if hasattr(self, "audio_language_combo"):
            self._refresh_audio_language_combo(self._selected_audio_language())
        if hasattr(self, "subtitle_language_combo"):
            self._refresh_subtitle_language_combo(self._selected_subtitle_language())

    def _show_preview_empty_state(self) -> None:
        self.preview_empty_panel = QFrame()
        self.preview_empty_panel.setObjectName("previewEmptyPanel")
        empty_layout = QVBoxLayout(self.preview_empty_panel)
        empty_layout.setContentsMargins(14, 14, 14, 14)
        empty_layout.setSpacing(7)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_empty_graphic = EmptyStateGraphic()
        if getattr(self, "theme", None) is not None:
            self.preview_empty_graphic.set_theme(self.theme)
        self.preview_empty_label = ResponsiveLabel(self._t("هنوز پیش‌نمایشی ساخته نشده است."))
        self.preview_empty_label.setObjectName("previewEmpty")
        self.preview_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = ResponsiveLabel(self._t("هر لینک در یک خط؛ لینک‌ها را می‌توانی مستقیماً داخل پنجره رها کنی."))
        empty_hint.setObjectName("muted")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.preview_empty_graphic, 0, Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.preview_empty_label)
        empty_layout.addWidget(empty_hint)
        self.preview_empty_panel.setMinimumHeight(158)
        self.preview_list_layout.addWidget(self.preview_empty_panel)
        self.preview_list_layout.addStretch(1)
        self.preview_count_badge.setText(f"{self._digits(0)} / {self._digits(0)}")

    def _on_download_item_finished(self, completed_url: str) -> None:
        self._remove_completed_download_input(completed_url)
        self._download_completed_sound_count += 1
        self._play_app_sound("download_complete")

    def _remove_completed_download_input(self, completed_url: str) -> None:
        """Remove only the successfully completed input URL and its preview card."""
        target = str(completed_url or "").strip()
        if not target:
            return

        remaining_lines: list[str] = []
        removed_from_editor = False
        for line in self.urls_edit.toPlainText().splitlines():
            value = line.strip()
            if not value:
                continue
            if not removed_from_editor and value == target:
                removed_from_editor = True
                continue
            remaining_lines.append(value)
        if removed_from_editor:
            self.urls_edit.setPlainText("\n".join(remaining_lines))

        matching_indexes = [
            index for index, card in enumerate(self.preview_cards)
            if str(getattr(card, "url", "") or "").strip() == target
        ]
        if not matching_indexes:
            return

        self.preview_generation += 1
        for index in reversed(matching_indexes):
            card = self.preview_cards.pop(index)
            self.preview_list_layout.removeWidget(card)
            card.deleteLater()
            if 0 <= index < len(self.preview_results):
                self.preview_results.pop(index)

        if not self.preview_cards:
            self._clear_preview_cards()
            self._show_preview_empty_state()
            return

        for index, card in enumerate(self.preview_cards):
            card.index = index
            card.index_badge.setText(f"#{index + 1}")

        self.preview_success_count = 0
        self.preview_failure_count = 0
        self.detected_audio_languages.clear()
        self.detected_subtitle_languages.clear()
        for result in self.preview_results:
            state = str(result.get("state") or "pending")
            if state == "ready":
                self.preview_success_count += 1
                info = dict(result.get("info") or {})
                self._merge_detected_audio_languages(list(info.get("audio_languages") or []), refresh=False)
                self._merge_detected_subtitle_languages(list(info.get("subtitle_languages") or []), refresh=False)
            elif state == "error":
                self.preview_failure_count += 1
        self._refresh_audio_language_combo(self._selected_audio_language())
        self._refresh_subtitle_language_combo(self._selected_subtitle_language())
        self._update_preview_counter()
        self._recalculate_preview_sizes()

    def _prepare_preview_cards(self, urls: list[str]) -> None:
        self.preview_generation += 1
        self._clear_preview_cards()
        for index, url in enumerate(urls):
            card = PreviewItemCard(index, url, self.language, self.preview_host)
            self.preview_cards.append(card)
            self.preview_results.append({"state": "pending", "url": url, "info": {}, "error": ""})
            self.preview_list_layout.addWidget(card)
        self.preview_list_layout.addStretch(1)
        total = len(urls)
        self.preview_count_badge.setText(f"{self._digits(0)} / {self._digits(total)}")

    def _apply_mark_watched_to_main_preview(
        self,
        urls: list[str],
        auth_options: dict[str, Any],
        manual_cookie_text: str,
    ) -> None:
        if not self.mark_watched_check.isChecked():
            return
        youtube_urls = [
            url for url in urls
            if url_domain(url) in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
        ]
        if not youtube_urls:
            return
        has_account_auth = bool(
            auth_options.get("cookiefile")
            or auth_options.get("cookiesfrombrowser")
            or manual_cookie_text.strip()
        )
        if not has_account_auth:
            self._append_log(self._t("پیش‌نمایش YouTube بدون کوکی حساب انجام شد؛ درخواست Mark watched ارسال نشد."))
            return
        auth_options["mark_watched"] = True
        self._append_log(self._t("درخواست Mark watched همراه کوکی حساب برای پیش‌نمایش YouTube فعال شد."))

    def _preview_all_urls(self) -> None:
        urls = self._urls()
        if not urls:
            self.toast.show_message(self._t("ابتدا یک لینک وارد کنید"))
            return
        if self.preview_worker and self.preview_worker.isRunning():
            return
        try:
            auth_options, manual_cookie_text, manual_cookie_domain = self._collect_auth(urls)
            auth_options.update(self._collect_runtime_options(urls))
            self._apply_mark_watched_to_main_preview(urls, auth_options, manual_cookie_text)
        except ValueError as exc:
            QMessageBox.warning(self, self._t("آماده‌سازی دانلود"), self._localized_error(str(exc)))
            return

        self._prepare_preview_cards(urls)
        self.preview_button.setEnabled(False)
        self.preview_button.setText(self._t("در حال بررسی…"))
        if hasattr(self, "preview_inline_button"):
            self.preview_inline_button.setEnabled(False)
            self.preview_inline_button.setText(self._t("در حال بررسی…"))
        self.preview_worker = PreviewWorker(urls, auth_options, manual_cookie_text, manual_cookie_domain, self.language)
        self.preview_worker.item_started.connect(self._preview_item_started)
        self.preview_worker.ready.connect(self._render_preview)
        self.preview_worker.failed.connect(self._preview_failed)
        self.preview_worker.finished.connect(self._preview_done)
        self.preview_worker.start()

    def _preview_item_started(self, index: int, total: int, url: str) -> None:
        if not 0 <= index < len(self.preview_cards):
            return
        card = self.preview_cards[index]
        card.set_state("checking", self._t("در حال بررسی"))
        card.meta.setText(self._t("در حال دریافت اطلاعات…"))
        card.meta.setToolTip(url)
        self.preview_scroll.ensureWidgetVisible(card, 0, 14)
        self.preview_count_badge.setText(f"{self._digits(index)} / {self._digits(total)}")

    def _render_preview(self, index: int, info: dict[str, Any]) -> None:
        if not 0 <= index < len(self.preview_cards):
            return
        card = self.preview_cards[index]
        service = str(info.get("service") or self._t("سرویس نامشخص"))
        domain = str(info.get("domain") or "")
        title = str(info.get("title") or self._t("بدون عنوان"))
        uploader = str(info.get("uploader") or "—")
        duration = human_seconds(info.get("duration"))

        card.service.setText(service)
        card.service.setToolTip(domain or service)
        card.title.setText(soft_wrap_text(title))
        card.title.setToolTip(title)
        card.meta.setText(soft_wrap_text(f"{uploader}  •  {duration}"))
        card.meta.setToolTip(f"{uploader}  •  {duration}\n{info.get('webpage_url') or card.url}")
        audio_languages = list(info.get("audio_languages") or [])
        self._render_card_audio_languages(card, audio_languages)
        self._merge_detected_audio_languages(audio_languages)
        subtitle_languages = list(info.get("subtitle_languages") or [])
        self._render_card_subtitle_languages(card, subtitle_languages)
        self._merge_detected_subtitle_languages(subtitle_languages)
        card.set_state("ready", self._t("آماده"))
        self.active_service_badge.setText(service)
        self.active_service_badge.setToolTip(domain or service)

        self.preview_success_count += 1
        self._mark_active_auth_success([service_domain(domain or card.url)])
        self.preview_results[index] = {"state": "ready", "url": card.url, "info": dict(info), "error": ""}
        self._update_preview_counter()
        self._recalculate_preview_sizes()

        thumbnail = str(info.get("thumbnail") or "")
        if thumbnail:
            worker = ThumbnailLoader(thumbnail)
            generation = self.preview_generation
            self.thumbnail_workers.append(worker)
            worker.loaded.connect(
                lambda data, item_index=index, batch_generation=generation:
                self._set_preview_thumbnail(item_index, data, batch_generation)
            )
            worker.finished.connect(lambda active_worker=worker: self._thumbnail_worker_finished(active_worker))
            worker.start()

    def _set_preview_thumbnail(self, index: int, data: QByteArray, generation: int) -> None:
        if generation != self.preview_generation or not 0 <= index < len(self.preview_cards):
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        image = self.preview_cards[index].image
        scaled = pixmap.scaled(
            image.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        image.setPixmap(scaled)

    def _thumbnail_worker_finished(self, worker: ThumbnailLoader) -> None:
        if worker in self.thumbnail_workers:
            self.thumbnail_workers.remove(worker)
        worker.deleteLater()

    def _preview_failed(self, index: int, message: str, url: str) -> None:
        if not 0 <= index < len(self.preview_cards):
            return
        card = self.preview_cards[index]
        service = service_identity(None, url).get("service") or self._t("سرویس نامشخص")
        card.service.setText(str(service))
        card.service.setToolTip(url_domain(url) or str(service))
        card.title.setText(soft_wrap_text(url))
        card.title.setToolTip(url)
        card.meta.setText(soft_wrap_text(message))
        card.meta.setToolTip(message)
        card.audio.clear()
        card.audio.hide()
        card.subtitles.clear()
        card.subtitles.hide()
        card.size.clear()
        card.size.hide()
        card.set_state("error", self._t("خطا"))
        self.preview_failure_count += 1
        self._mark_active_auth_invalid(message, [service_domain(url)])
        self.preview_results[index] = {"state": "error", "url": url, "info": {}, "error": message}
        self._update_preview_counter()

    def _update_preview_counter(self) -> None:
        done = self.preview_success_count + self.preview_failure_count
        total = len(self.preview_cards)
        self.preview_count_badge.setText(f"{self._digits(done)} / {self._digits(total)}")

    def _preview_done(self) -> None:
        self._refresh_subtitle_language_combo(self._selected_subtitle_language())
        self.preview_button.setEnabled(True)
        self.preview_button.setText(self._t("پیش‌نمایش همهٔ لینک‌ها"))
        if hasattr(self, "preview_inline_button"):
            self.preview_inline_button.setEnabled(True)
            self.preview_inline_button.setText(self._t("پیش‌نمایش همهٔ لینک‌ها"))
        self._update_preview_counter()
        total = len(self.preview_cards)
        if self.preview_failure_count:
            if self.language == "en":
                message = f"Previewed {self.preview_success_count} of {total} links; {self.preview_failure_count} failed"
            else:
                message = f"پیش‌نمایش {fa_digits(self.preview_success_count)} از {fa_digits(total)} لینک آماده شد؛ {fa_digits(self.preview_failure_count)} مورد ناموفق بود"
        else:
            message = (
                f"All {total} link previews are ready"
                if self.language == "en"
                else f"پیش‌نمایش هر {fa_digits(total)} لینک آماده شد"
            )
        self.toast.show_message(message)

    def _build_options(self, auth_options: dict[str, Any] | None = None) -> dict[str, Any]:
        preset = PRESETS[self._combo_data(self.preset_combo, "auto")]
        output_dir = Path(self.output_edit.text()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        filename_template = "%(title).180B [%(id)s].%(ext)s"
        if self.organize_service_check.isChecked():
            # webpage_url_domain is available to output templates for supported
            # extractors; yt-dlp creates missing path components automatically.
            output_template = output_dir / "%(webpage_url_domain|Other)s" / filename_template
        else:
            output_template = output_dir / filename_template

        options: dict[str, Any] = {
            "format": preset.format_selector,
            "outtmpl": str(output_template),
            "noplaylist": not self.playlist_check.isChecked(),
            "continuedl": True,
            "part": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": self.fragments_spin.value(),
            "windowsfilenames": os.name == "nt",
            "ignoreerrors": False,
            "_leon_output_root": str(output_dir),
            "_leon_optional_gallery_fallback": True,
            "_leon_google_play_email": self.google_play_email_edit.text().strip() if hasattr(self, "google_play_email_edit") else "",
            "_leon_google_play_aas_token": self.google_play_aas_token_edit.text().strip() if hasattr(self, "google_play_aas_token_edit") else "",
            "_leon_spotify_format": "m4a" if preset.key == "audio_m4a" else "mp3",
            "_leon_spotify_use_official_api": self.spotify_official_api_check.isChecked() if hasattr(self, "spotify_official_api_check") else False,
            "_leon_spotify_client_id": self.spotify_client_id_edit.text().strip() if hasattr(self, "spotify_client_id_edit") else "",
            "_leon_spotify_client_secret": self.spotify_client_secret_edit.text().strip() if hasattr(self, "spotify_client_secret_edit") else "",
            "_leon_spotify_proxy": self.spotify_proxy_edit.text().strip() if hasattr(self, "spotify_proxy_edit") else "",
        }
        selected_audio_language = self._selected_audio_language()
        if selected_audio_language:
            options["_leon_audio_language"] = selected_audio_language
        if preset.merge_output_format:
            options["merge_output_format"] = preset.merge_output_format
        if preset.format_sort:
            options["format_sort"] = list(preset.format_sort)

        postprocessors: list[dict[str, Any]] = []
        if preset.audio_codec:
            processor: dict[str, Any] = {"key": "FFmpegExtractAudio", "preferredcodec": preset.audio_codec}
            if preset.audio_codec == "mp3":
                processor["preferredquality"] = "0"
            postprocessors.append(processor)
        if self.metadata_check.isChecked():
            postprocessors.append({"key": "FFmpegMetadata"})
        if self.thumbnail_check.isChecked():
            options["writethumbnail"] = True
            postprocessors.append({"key": "EmbedThumbnail"})
        if self.mark_watched_check.isChecked():
            options["mark_watched"] = True

        if self.subtitle_check.isChecked():
            selected_subtitle = self._selected_subtitle_language()
            options["writesubtitles"] = True
            options["writeautomaticsub"] = self.auto_subtitle_check.isChecked()
            options["subtitleslangs"] = ["all"] if selected_subtitle in {"", "all"} else [selected_subtitle]
            if not preset.audio_codec and preset.key != "audio_original":
                options["embedsubtitles"] = True

        if auth_options:
            options.update(auth_options)
        if postprocessors:
            options["postprocessors"] = postprocessors
        return options

    def _start_download(self) -> None:
        if yt_dlp is None:
            self._show_missing_dependency()
            return
        urls = self._urls()
        if not urls:
            self.toast.show_message(self._t("حداقل یک لینک وارد کنید"))
            return
        missing_optional: list[str] = []
        if any(is_spotify_url(url) for url in urls) and not spotdl_available():
            missing_optional.append("spotDL")
        if any(is_app_store_url(url) for url in urls) and not apkeep_available():
            missing_optional.append("apkeep")
        if missing_optional:
            message = (
                self._t("برای این لینک‌ها ابتدا هستهٔ اختیاری لازم را از مدیریت پکیج‌ها نصب کنید:")
                + "\n\n"
                + "\n".join(f"• {name}" for name in missing_optional)
            )
            QMessageBox.information(self, self._t("هستهٔ اختیاری نصب نیست"), message)
            if hasattr(self, "page_indexes"):
                self._set_main_page(self.page_indexes.get("packages", 0))
            return
        spotify_urls = [url for url in urls if is_spotify_url(url)]
        if spotify_urls and hasattr(self, "spotify_official_api_check") and self.spotify_official_api_check.isChecked():
            client_id = self.spotify_client_id_edit.text().strip() if hasattr(self, "spotify_client_id_edit") else ""
            client_secret = self.spotify_client_secret_edit.text().strip() if hasattr(self, "spotify_client_secret_edit") else ""
            if not client_id or not client_secret:
                QMessageBox.warning(
                    self,
                    self._t("تنظیمات Spotify ناقص است"),
                    self._t("برای استفاده از API رسمی Spotify باید Client ID و Client Secret را در Packages & Tools وارد کنید."),
                )
                if hasattr(self, "page_indexes"):
                    self._set_main_page(self.page_indexes.get("packages", 0))
                return
        if self.worker and self.worker.isRunning():
            return
        output = self.output_edit.text().strip()
        if not output:
            self.toast.show_message(self._t("پوشهٔ ذخیره را انتخاب کنید"))
            return
        try:
            auth_options, manual_cookie_text, manual_cookie_domain = self._collect_auth(urls)
            auth_options.update(self._collect_runtime_options(urls))
        except ValueError as exc:
            QMessageBox.warning(self, self._t("آماده‌سازی دانلود"), self._localized_error(str(exc)))
            return

        if self.mark_watched_check.isChecked():
            youtube_urls = [url for url in urls if url_domain(url) in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}]
            has_account_auth = bool(auth_options.get("cookiefile") or auth_options.get("cookiesfrombrowser") or manual_cookie_text.strip())
            if youtube_urls and not has_account_auth:
                self.toast.show_message(self._t("برای ثبت دیده‌شدن در YouTube باید کوکی حساب واردشده را انتخاب کنید."), 4200)
                self._append_log(self._t("علامت‌گذاری به‌عنوان دیده‌شده بدون کوکی حساب انجام نمی‌شود."))

        if any("apkpure.com" in url.lower() or url.lower().startswith("apkpure:") for url in urls):
            self._play_app_sound("warning")
            result = QMessageBox.warning(
                self,
                self._t("هشدار منبع APKPure"),
                self._t("APKPure یک منبع شخص ثالث است. امضای فایل APK را قبل از نصب بررسی کنید. ادامه می‌دهید؟"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return

        if self._needs_ffmpeg() and not shutil.which("ffmpeg"):
            self._play_app_sound("warning")
            result = QMessageBox.warning(
                self,
                self._t("ffmpeg پیدا نشد"),
                self._t("برای ادغام یا تبدیل این خروجی، ffmpeg لازم است. دانلود ممکن است ناقص بماند. ادامه می‌دهید؟"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if result != QMessageBox.StandardButton.Yes:
                return

        self._save_settings()
        self._download_history_buffer = {
            url: {
                "url": url,
                "title": url,
                "service": service_identity(None, url).get("service") or self._t("سرویس نامشخص"),
                "output_dir": output,
                "preset": self._combo_data(self.preset_combo, "auto"),
                "preset_label": self.preset_combo.currentText(),
            }
            for url in urls
        }
        self._populate_queue(urls)
        self._download_cancel_requested = False
        self._forced_close_scheduled = False
        self._download_batch_total = len(urls)
        self._download_completed_sound_count = 0
        self._reset_progress()
        self._set_busy(True)
        self.status_label.setText(self._t("در حال آماده‌سازی"))
        self.detail_label.setText(self._t("اتصال به سرویس و بررسی فرمت‌ها…"))
        self._append_log("—" * 45)

        self.worker = DownloadWorker(urls, self._build_options(auth_options), manual_cookie_text, manual_cookie_domain, self.language)
        self.worker.log.connect(self._append_log)
        self.worker.progress.connect(self._render_progress)
        self.worker.postprocess.connect(self._render_postprocess)
        self.worker.item_finished.connect(self._on_download_item_finished)
        self.worker.finished_ok.connect(self._finish_success)
        self.worker.cancelled.connect(self._finish_cancelled)
        self.worker.failed.connect(self._finish_error)
        self.worker.finished.connect(self._download_thread_finished)
        self.worker.finished.connect(self._finish_deferred_close)
        self.worker.start()

    def _needs_ffmpeg(self) -> bool:
        preset = PRESETS[self._combo_data(self.preset_combo, "auto")]
        return bool(
            preset.audio_codec
            or preset.merge_output_format
            or self.metadata_check.isChecked()
            or self.thumbnail_check.isChecked()
            or self.subtitle_check.isChecked()
            or "+" in preset.format_selector
        )

    def _cancel_download(self) -> None:
        if self.worker and self.worker.isRunning():
            self._download_cancel_requested = True
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText(self._t("در حال لغو"))
            self.detail_label.setText(self._t("لغو در نزدیک‌ترین نقطهٔ امن انجام می‌شود…"))
            self._append_log(self._t("درخواست لغو ارسال شد."))

    def _render_progress(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        title = str(data.get("title") or self._t("فایل"))
        service = str(data.get("service") or self._t("سرویس نامشخص"))
        self.active_service_badge.setText(service)
        self.active_service_badge.setToolTip(str(data.get("domain") or service))
        self.detail_label.setText(title)
        self._advance_queue(title, service=service, finished=status == "finished")
        history_url = str(data.get("webpage_url") or "").strip()
        if status == "finished":
            entry_key = history_url or next(
                (key for key, item in self._download_history_buffer.items() if str(item.get("title") or "") in {title, key}),
                history_url or title,
            )
            entry = dict(self._download_history_buffer.get(entry_key) or {})
            history_filepath = str(data.get("filepath") or "")
            entry.update({
                "url": history_url or str(entry.get("url") or entry_key),
                "title": title,
                "service": service,
                "output_dir": str(Path(history_filepath).parent) if history_filepath else self.output_edit.text().strip(),
                "preset": self._combo_data(self.preset_combo, "auto"),
                "preset_label": self.preset_combo.currentText(),
                "filename": str(data.get("filename") or ""),
                "filepath": history_filepath,
            })
            self._download_history_buffer[entry_key] = entry
            self.status_label.setText(self._t("در حال پردازش نهایی"))
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(1000)
            self.progress_bar.setFormat(f"{self._digits(100)}%")
            return

        self.status_label.setText(self._t("در حال دانلود"))
        percent = data.get("percent")
        if percent is None:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat(self._t("در حال دریافت…"))
        else:
            self.progress_bar.setRange(0, 1000)
            self.progress_bar.setValue(int(max(0, min(100, float(percent))) * 10))
            value_text = f"{float(percent):.1f}"
            self.progress_bar.setFormat(f"{self._digits(value_text)}%")

        downloaded = human_bytes(data.get("downloaded"))
        total = human_bytes(data.get("total"))
        speed_text = str(data.get("speed_text") or "").strip()
        eta_text = str(data.get("eta_text") or "").strip()
        if not speed_text:
            speed_text = human_bytes(data.get("speed")) + "/s" if data.get("speed") else "—"
        if not eta_text:
            eta_text = human_seconds(data.get("eta"))
        self.size_value.setText(f"{downloaded} / {total}")
        self.speed_value.setText(speed_text)
        if hasattr(self, "speed_wave"):
            self.speed_wave.set_speed(data.get("speed") or 0)
        self.eta_value.setText(eta_text)

    def _render_postprocess(self, text: str) -> None:
        self.status_label.setText(self._t("پردازش نهایی"))
        self.detail_label.setText(text)

    def _finish_success(self) -> None:
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(1000)
        self.progress_bar.setFormat(f"{self._digits(100)}%")
        self.status_label.setText(self._t("دانلود کامل شد"))
        self.detail_label.setText(self._t("فایل‌ها در پوشهٔ انتخاب‌شده ذخیره شدند."))
        self.eta_value.setText(self._t("تمام شد"))
        if hasattr(self, "speed_wave"):
            self.speed_wave.set_speed(0)
        self._mark_all_queue("✓")
        self._append_log(self._t("همهٔ دانلودها با موفقیت پایان یافتند."))
        self._mark_active_auth_success()
        history_entries = list(self._download_history_buffer.values())
        completed_entries = [
            item for item in history_entries
            if str(item.get("filename") or item.get("filepath") or "").strip()
        ]
        self.history_store.add_many(completed_entries or history_entries)
        self._refresh_history_table()
        if self._download_batch_total > 1:
            self._play_app_sound("queue_complete")
        elif self._download_completed_sound_count == 0:
            # Fallback for any engine that reports only batch completion.
            self._play_app_sound("download_complete")
        self.toast.show_message(self._t("دانلود با موفقیت تمام شد"))

    def _finish_cancelled(self) -> None:
        self.status_label.setText(self._t("دانلود لغو شد"))
        self.detail_label.setText(self._t("فایل ناقص ممکن است برای ادامه در اجرای بعدی حفظ شده باشد."))
        self.eta_value.setText(self._t("لغو شد"))
        if hasattr(self, "speed_wave"):
            self.speed_wave.set_speed(0)
        self._append_log(self._t("دانلود توسط کاربر لغو شد."))
        self._play_app_sound("cancelled")
        self.toast.show_message(self._t("دانلود لغو شد"))

    def _finish_error(self, message: str) -> None:
        visible_message = self._localized_error(message)
        self.status_label.setText(self._t("خطا"))
        self.detail_label.setText(self._t("جزئیات در گزارش زنده ثبت شد."))
        self.eta_value.setText(self._t("ناموفق"))
        if hasattr(self, "speed_wave"):
            self.speed_wave.set_speed(0)
        self.last_error_text = visible_message
        self._append_log(("Error: " if self.language == "en" else "خطا: ") + visible_message)
        self._persist_error_report(visible_message)
        self._mark_active_auth_invalid(visible_message)
        self._play_app_sound("error")
        self.toast.show_message(self._t("دانلود با خطا مواجه شد"))
        self._show_error_dialog(visible_message)

    def _persist_error_report(self, message: str) -> None:
        """Append handled worker errors to the runtime log as plain text."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            log_path = CONFIG_DIR / "leon_runtime.log"
            timestamp = datetime.now().isoformat(timespec="seconds")
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n--- handled application error {timestamp} ---\n{message}\n")
        except OSError:
            pass

    def _show_error_dialog(self, message: str) -> None:
        clean_message = self._localized_error(message)
        dialog = QMessageBox(self)
        dialog.setObjectName("leonErrorMessageBox")
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle(self._t("خطای دانلود"))
        dialog.setText(soft_wrap_text(clean_message, 52))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        dialog.setStyleSheet(build_message_box_stylesheet(self.theme))
        dialog.setMinimumWidth(620)

        live_log = self.log_view.toPlainText().strip() if hasattr(self, "log_view") else ""
        if live_log and live_log != clean_message:
            dialog.setDetailedText(live_log[-12000:])

        copy_button = dialog.addButton(self._t("کپی خطا"), QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Close)

        for label in dialog.findChildren(QLabel):
            if label.text().strip():
                label.setWordWrap(True)
                label.setMinimumWidth(440)

        def copy_error() -> None:
            QApplication.clipboard().setText(clean_message)
            self.toast.show_message(self._t("متن خطا کپی شد"))

        copy_button.clicked.connect(copy_error)
        dialog.exec()

    def _copy_log(self) -> None:
        selected = self.log_view.textCursor().selectedText().replace("\u2029", "\n").strip()
        text = selected or self.log_view.toPlainText().strip()
        if not text:
            self.toast.show_message(self._t("گزارشی برای کپی وجود ندارد"))
            return
        QApplication.clipboard().setText(text)
        self.toast.show_message(self._t("متن گزارش کپی شد"))

    def _set_busy(self, busy: bool) -> None:
        self.start_button.setEnabled(not busy)
        self.preview_button.setEnabled(not busy)
        if hasattr(self, "preview_inline_button"):
            self.preview_inline_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.preset_combo.setEnabled(not busy)
        if hasattr(self, "hero_preset_combo"):
            self.hero_preset_combo.setEnabled(not busy)
        self.auth_combo.setEnabled(not busy)
        self.auth_stack.setEnabled(not busy)
        self.runtime_combo.setEnabled(not busy)
        self.runtime_path_edit.setEnabled(not busy)
        self.output_edit.setEnabled(not busy)
        self.organize_service_check.setEnabled(not busy)
        self.fragments_spin.setEnabled(not busy)
        self.mark_watched_check.setEnabled(not busy)
        self.title_bar.language_button.setEnabled(not busy)

    def _reset_progress(self) -> None:
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"{self._digits(0)}%")
        self.size_value.setText("—")
        self.speed_value.setText("—")
        if hasattr(self, "speed_wave"):
            self.speed_wave.reset()
        self.eta_value.setText("—")
        self.active_service_badge.setText(self._t("سرویس نامشخص"))
        self.current_queue_index = -1

    def _known_queue_titles(self, urls: list[str]) -> dict[str, str]:
        wanted = {str(url).strip() for url in urls if str(url).strip()}
        titles: dict[str, str] = {}

        for result in getattr(self, "preview_results", []):
            url = str(result.get("url") or "").strip()
            info = dict(result.get("info") or {})
            title = str(info.get("title") or "").strip()
            if url in wanted and title and title != url:
                titles[url] = title

        for entry in self.later_store.load():
            url = str(entry.get("url") or "").strip()
            title = str(entry.get("title") or "").strip()
            if url in wanted and title and title != url:
                titles.setdefault(url, title)

        for result in getattr(self, "search_results", []):
            url = str(result.get("url") or result.get("webpage_url") or "").strip()
            title = str(result.get("title") or "").strip()
            if url in wanted and title and title != url:
                titles.setdefault(url, title)
        return titles

    def _render_queue_item(self, item: QListWidgetItem) -> None:
        url = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        service = str(item.data(Qt.ItemDataRole.UserRole + 1) or self._t("سرویس نامشخص"))
        title = str(item.data(Qt.ItemDataRole.UserRole + 2) or self._t("در حال دریافت عنوان…"))
        prefix = str(item.data(Qt.ItemDataRole.UserRole + 3) or "○")
        item.setText(f"{prefix}  [{service}]  {title}\n{url}")
        item.setToolTip(f"{title}\n{service}\n{url}".strip())
        item.setSizeHint(QSize(0, 58))

    def _populate_queue(self, urls: list[str]) -> None:
        self.queue_metadata_generation += 1
        generation = self.queue_metadata_generation
        if self.queue_metadata_worker and self.queue_metadata_worker.isRunning():
            self.queue_metadata_worker.requestInterruption()

        self.queue_list.clear()
        self.queue_items.clear()
        known_titles = self._known_queue_titles(urls)
        missing_titles = False
        for url in urls:
            source = service_identity(None, url)
            service = source.get("service") or self._t("سرویس نامشخص")
            title = known_titles.get(url, "")
            if not title:
                title = self._t("در حال دریافت عنوان…")
                missing_titles = True
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, url)
            item.setData(Qt.ItemDataRole.UserRole + 1, service)
            item.setData(Qt.ItemDataRole.UserRole + 2, title)
            item.setData(Qt.ItemDataRole.UserRole + 3, "○")
            item.setTextAlignment((Qt.AlignmentFlag.AlignLeft if self.language == "en" else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter)
            item.setForeground(QColor(self.theme.text))
            self._render_queue_item(item)
            self.queue_list.addItem(item)
            self.queue_items.append(item)
        self.queue_count.setText(f"{self._digits(len(urls))} {self._t('مورد')}")
        if missing_titles:
            QTimer.singleShot(0, lambda batch=list(urls), token=generation: self._start_queue_metadata_lookup(batch, token))

    def _start_queue_metadata_lookup(self, urls: list[str], generation: int) -> None:
        if generation != self.queue_metadata_generation or not urls:
            return
        try:
            auth_options, manual_cookie_text, manual_cookie_domain = self._collect_auth(urls)
        except ValueError:
            auth_options, manual_cookie_text, manual_cookie_domain = {}, "", ""
        try:
            auth_options.update(self._collect_runtime_options(urls))
        except ValueError:
            # Queue titles are optional; missing Deno must not block the actual download path.
            pass
        worker = PreviewWorker(urls, auth_options, manual_cookie_text, manual_cookie_domain, self.language)
        self.queue_metadata_worker = worker
        worker.ready.connect(lambda index, info, token=generation: self._queue_metadata_ready(token, index, info))
        worker.failed.connect(lambda index, _message, _url, token=generation: self._queue_metadata_failed(token, index))
        worker.finished.connect(lambda current=worker, token=generation: self._queue_metadata_finished(current, token))
        worker.start()

    def _queue_metadata_ready(self, generation: int, index: int, info: dict[str, Any]) -> None:
        if generation != self.queue_metadata_generation or not 0 <= index < len(self.queue_items):
            return
        item = self.queue_items[index]
        title = str(info.get("title") or "").strip()
        service = str(info.get("service") or item.data(Qt.ItemDataRole.UserRole + 1) or "").strip()
        if title:
            item.setData(Qt.ItemDataRole.UserRole + 2, title)
        if service:
            item.setData(Qt.ItemDataRole.UserRole + 1, service)
        self._render_queue_item(item)

    def _queue_metadata_failed(self, generation: int, index: int) -> None:
        if generation != self.queue_metadata_generation or not 0 <= index < len(self.queue_items):
            return
        item = self.queue_items[index]
        current = str(item.data(Qt.ItemDataRole.UserRole + 2) or "")
        if current == self._t("در حال دریافت عنوان…"):
            item.setData(Qt.ItemDataRole.UserRole + 2, self._t("عنوان در دسترس نیست"))
            self._render_queue_item(item)

    def _queue_metadata_finished(self, worker: PreviewWorker, generation: int) -> None:
        if self.queue_metadata_worker is worker:
            self.queue_metadata_worker = None
        worker.deleteLater()

    def _advance_queue(self, title: str, *, service: str = "", finished: bool) -> None:
        if not self.queue_items:
            return
        if self.current_queue_index < 0:
            self.current_queue_index = 0
        index = min(self.current_queue_index, len(self.queue_items) - 1)
        item = self.queue_items[index]
        resolved_service = service or str(item.data(Qt.ItemDataRole.UserRole + 1) or self._t("سرویس نامشخص"))
        item.setData(Qt.ItemDataRole.UserRole + 1, resolved_service)
        item_url = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        current_title = str(item.data(Qt.ItemDataRole.UserRole + 2) or "").strip()
        if title and (title.strip() != item_url or current_title in {"", self._t("در حال دریافت عنوان…"), self._t("عنوان در دسترس نیست")}):
            item.setData(Qt.ItemDataRole.UserRole + 2, title)
        item.setData(Qt.ItemDataRole.UserRole + 3, "✓" if finished else "◉")
        self._render_queue_item(item)
        self.queue_list.setCurrentItem(item)
        if finished and self.current_queue_index < len(self.queue_items) - 1:
            self.current_queue_index += 1

    def _mark_all_queue(self, prefix: str) -> None:
        for item in self.queue_items:
            item.setData(Qt.ItemDataRole.UserRole + 3, prefix)
            self._render_queue_item(item)

    def _append_log(self, message: str) -> None:
        if not message:
            return
        self.log_view.appendPlainText(message.rstrip())
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def _install_wheel_scroll_guard(self) -> None:
        """Make the wheel scroll the page instead of silently changing options."""
        for widget in [*self.findChildren(QComboBox), *self.findChildren(QSpinBox)]:
            widget.installEventFilter(self)

    @staticmethod
    def _nearest_scroll_area(widget: QWidget) -> QScrollArea | None:
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return parent
            parent = parent.parentWidget()
        return None

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Wheel and isinstance(watched, (QComboBox, QSpinBox)):
            if isinstance(watched, QComboBox) and watched.view().isVisible():
                return super().eventFilter(watched, event)
            scroll = self._nearest_scroll_area(watched)
            if scroll is not None:
                bar = scroll.verticalScrollBar()
                pixel_delta = event.pixelDelta().y()
                if pixel_delta:
                    movement = pixel_delta
                else:
                    steps = event.angleDelta().y() / 120.0
                    movement = int(steps * max(36, bar.singleStep() * 3))
                bar.setValue(bar.value() - movement)
                event.accept()
                return True
            # Outside a scrolling page, still prevent accidental option changes.
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _refresh_queue_colors(self) -> None:
        if not hasattr(self, "queue_items"):
            return
        for item in self.queue_items:
            item.setForeground(QColor(self.theme.text))

    def _reset_audio_language_combo(self) -> None:
        if not hasattr(self, "audio_language_combo"):
            return
        self.audio_language_combo.clear()
        self.audio_language_combo.addItem(self._t("خودکار / صدای اصلی"), "")

    def _selected_audio_language(self) -> str:
        if not hasattr(self, "audio_language_combo"):
            return ""
        value = self.audio_language_combo.currentData()
        return str(value or "").strip()

    def _refresh_audio_language_combo(self, preferred: str = "") -> None:
        if not hasattr(self, "audio_language_combo"):
            return
        current = str(preferred or self._selected_audio_language() or "").strip()
        self.audio_language_combo.blockSignals(True)
        self._reset_audio_language_combo()
        for key, item in sorted(
            self.detected_audio_languages.items(),
            key=lambda pair: (not bool(pair[1].get("is_default")), audio_language_name(str(pair[1].get("code") or pair[0]), self.language).lower()),
        ):
            code = str(item.get("code") or key).strip()
            label = audio_language_name(code, self.language)
            if item.get("is_default"):
                label += " — " + self._t("پیش‌فرض")
            self.audio_language_combo.addItem(label, code)
        if current and self.audio_language_combo.findData(current) < 0:
            self.audio_language_combo.addItem(audio_language_name(current, self.language), current)
        index = self.audio_language_combo.findData(current) if current else 0
        self.audio_language_combo.setCurrentIndex(max(0, index))
        self.audio_language_combo.blockSignals(False)
        self._recalculate_preview_sizes()

    def _merge_detected_audio_languages(self, languages: list[dict[str, Any]], refresh: bool = True) -> None:
        changed = False
        for item in languages:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            key = code.lower()
            previous = self.detected_audio_languages.get(key)
            if previous is None or bool(item.get("is_default")) and not bool(previous.get("is_default")):
                self.detected_audio_languages[key] = dict(item)
                changed = True
        if refresh and changed:
            self._refresh_audio_language_combo()

    def _render_card_audio_languages(self, card: PreviewItemCard, languages: list[dict[str, Any]]) -> None:
        codes = [str(item.get("code") or "").strip() for item in languages]
        codes = [code for code in codes if code]
        if not codes:
            card.audio.clear()
            card.audio.hide()
            return
        labels = [audio_language_name(code, self.language) for code in codes]
        prefix = self._t("صداهای موجود")
        text = f"{prefix}: " + "، ".join(labels)
        card.audio.setText(soft_wrap_text(text, 32))
        card.audio.setToolTip(text)
        card.audio.show()

    def _reset_subtitle_language_combo(self) -> None:
        if not hasattr(self, "subtitle_language_combo"):
            return
        self.subtitle_language_combo.clear()
        self.subtitle_language_combo.addItem(self._t("همهٔ زیرنویس‌های موجود"), "all")

    def _selected_subtitle_language(self) -> str:
        if not hasattr(self, "subtitle_language_combo"):
            return "all"
        value = self.subtitle_language_combo.currentData()
        return str(value or "all").strip()

    def _subtitle_source_label(self, item: dict[str, Any]) -> str:
        manual = bool(item.get("manual"))
        automatic = bool(item.get("automatic"))
        if manual and automatic:
            return self._t("دستی و خودکار")
        if manual:
            return self._t("دستی")
        if automatic:
            return self._t("خودکار")
        return self._t("نامشخص")

    def _refresh_subtitle_language_combo(self, preferred: str = "") -> None:
        if not hasattr(self, "subtitle_language_combo"):
            return
        current = str(preferred or self._selected_subtitle_language() or "all").strip()
        self.subtitle_language_combo.blockSignals(True)
        self._reset_subtitle_language_combo()
        for key, item in sorted(
            self.detected_subtitle_languages.items(),
            key=lambda pair: (
                not bool(pair[1].get("manual")),
                subtitle_language_name(str(pair[1].get("code") or pair[0]), self.language).lower(),
            ),
        ):
            code = str(item.get("code") or key).strip()
            label = f"{subtitle_language_name(code, self.language)} — {self._subtitle_source_label(item)}"
            self.subtitle_language_combo.addItem(label, code)
        if current and self.subtitle_language_combo.findData(current) < 0 and current != "all":
            self.subtitle_language_combo.addItem(subtitle_language_name(current, self.language), current)
        index = self.subtitle_language_combo.findData(current)
        self.subtitle_language_combo.setCurrentIndex(index if index >= 0 else 0)
        self.subtitle_language_combo.blockSignals(False)

    def _merge_detected_subtitle_languages(self, languages: list[dict[str, Any]], refresh: bool = True) -> None:
        changed = False
        for item in languages:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            key = code.lower()
            previous = self.detected_subtitle_languages.get(key)
            if previous is None:
                self.detected_subtitle_languages[key] = dict(item)
                changed = True
                continue
            merged = dict(previous)
            merged["manual"] = bool(previous.get("manual")) or bool(item.get("manual"))
            merged["automatic"] = bool(previous.get("automatic")) or bool(item.get("automatic"))
            for field in ("manual_formats", "automatic_formats"):
                merged[field] = sorted(set(previous.get(field) or []) | set(item.get(field) or []))
            if merged != previous:
                self.detected_subtitle_languages[key] = merged
                changed = True
        if refresh and changed:
            self._refresh_subtitle_language_combo()

    def _render_card_subtitle_languages(self, card: PreviewItemCard, languages: list[dict[str, Any]]) -> None:
        valid = [item for item in languages if str(item.get("code") or "").strip()]
        if not valid:
            card.subtitles.clear()
            card.subtitles.hide()
            return
        labels = [
            f"{subtitle_language_name(str(item.get('code') or ''), self.language)} ({self._subtitle_source_label(item)})"
            for item in valid
        ]
        full_text = f"{self._t('زیرنویس‌های موجود')}: " + "، ".join(labels)
        visible_labels = labels[:5]
        if len(labels) > 5:
            visible_labels.append(f"+{self._digits(len(labels) - 5)}")
        visible_text = f"{self._t('زیرنویس‌های موجود')}: " + "، ".join(visible_labels)
        card.subtitles.setText(soft_wrap_text(visible_text, 32))
        card.subtitles.setToolTip(full_text)
        card.subtitles.show()

    def _on_subtitle_language_changed(self, *_args: object) -> None:
        code = self._selected_subtitle_language()
        if code in {"", "all"}:
            return
        item = self.detected_subtitle_languages.get(code.lower()) or {}
        if bool(item.get("automatic")) and not bool(item.get("manual")) and not self.auto_subtitle_check.isChecked():
            self.auto_subtitle_check.setChecked(True)
            self.toast.show_message(self._t("این زبان فقط زیرنویس خودکار دارد؛ گزینهٔ زیرنویس خودکار فعال شد."))

    def _size_confidence_label(self, confidence: str) -> str:
        labels = {
            "exact": self._t("دقیق"),
            "approximate": self._t("تقریبی"),
            "estimated": self._t("تخمینی"),
            "unknown": self._t("نامشخص"),
        }
        return labels.get(confidence, labels["unknown"])

    def _format_preview_size_text(self, estimate: dict[str, Any]) -> tuple[str, str]:
        size = estimate.get("bytes")
        confidence = str(estimate.get("confidence") or "unknown")
        if size is None:
            text = self._t("حجم دانلود: پس از شروع دانلود مشخص می‌شود")
            return text, self._t("این سرویس حجم یا بیت‌ریت کافی برای تخمین ارائه نکرده است.")
        confidence_text = self._size_confidence_label(confidence)
        prefix = self._t("حجم دانلود")
        value = human_bytes(size)
        text = f"{prefix}: {value} — {confidence_text}"
        component_lines: list[str] = []
        for component in estimate.get("components") or []:
            component_size = component.get("bytes")
            if component_size is None:
                continue
            component_type = str(component.get("type") or "")
            type_label = {
                "video": self._t("ویدئو"),
                "audio": self._t("صدا"),
                "combined": self._t("ویدئو و صدا"),
            }.get(component_type, component_type)
            component_lines.append(f"{type_label}: {human_bytes(component_size)}")
        note = self._t("حجم فایل نهایی ممکن است پس از ادغام یا تبدیل کمی متفاوت باشد.")
        tooltip = "\n".join(component_lines + [note])
        return text, tooltip

    def _recalculate_preview_sizes(self, *_args: object) -> None:
        if not hasattr(self, "preview_results") or not hasattr(self, "preview_cards"):
            return
        preset_key = self._combo_data(self.preset_combo, "auto") if hasattr(self, "preset_combo") else "auto"
        audio_language = self._selected_audio_language()
        known_total = 0
        known_count = 0
        unknown_count = 0
        worst_confidence = "exact"
        confidence_order = {"exact": 0, "approximate": 1, "estimated": 2, "unknown": 3}

        for index, result in enumerate(self.preview_results):
            if not 0 <= index < len(self.preview_cards):
                continue
            card = self.preview_cards[index]
            if str(result.get("state") or "") != "ready":
                card.size.clear()
                card.size.hide()
                continue
            info = dict(result.get("info") or {})
            estimate = estimate_selected_media_size(info, preset_key, audio_language)
            result["size_estimate"] = estimate
            text, tooltip = self._format_preview_size_text(estimate)
            confidence = str(estimate.get("confidence") or "unknown")
            card.size.setProperty("sizeConfidence", confidence)
            card.size.setText(soft_wrap_text(text, 32))
            card.size.setToolTip(tooltip)
            card.size.style().unpolish(card.size)
            card.size.style().polish(card.size)
            card.size.show()
            if estimate.get("bytes") is None:
                unknown_count += 1
                continue
            known_total += int(estimate["bytes"])
            known_count += 1
            if confidence_order.get(confidence, 3) > confidence_order.get(worst_confidence, 0):
                worst_confidence = confidence

        if not hasattr(self, "preview_size_summary"):
            return
        if known_count == 0:
            if unknown_count:
                self.preview_size_summary.setText(self._t("حجم کل انتخاب‌شده: نامشخص"))
            else:
                self.preview_size_summary.setText(self._t("حجم کل انتخاب‌شده: —"))
            return
        confidence_text = self._size_confidence_label(worst_confidence)
        summary = f"{self._t('حجم کل انتخاب‌شده')}: {human_bytes(known_total)} — {confidence_text}"
        if unknown_count:
            summary += "  •  " + self._t("برخی لینک‌ها حجم نامشخص دارند")
        self.preview_size_summary.setText(soft_wrap_text(summary, 38))
        self.preview_size_summary.setToolTip(self._t("حجم بر اساس کیفیت، زبان صدا و فرمت فعلی محاسبه می‌شود."))

    def _sound_custom_paths(self) -> dict[str, str]:
        edits = getattr(self, "sound_custom_edits", {})
        return {key: edit.text().strip() for key, edit in edits.items() if edit.text().strip()}

    def _configure_sound_player(self, *_args) -> None:
        player = getattr(self, "sound_player", None)
        if player is None:
            return
        theme_combo = getattr(self, "sound_theme_combo", None)
        theme = self._combo_data(theme_combo, DEFAULT_SOUND_THEME) if theme_combo is not None else DEFAULT_SOUND_THEME
        volume_control = getattr(self, "sound_volume_slider", None)
        volume = volume_control.value() if volume_control is not None else DEFAULT_VOLUME
        player.configure(theme=theme, volume=volume, custom_paths=self._sound_custom_paths())

    def _sound_volume_changed(self, value: int) -> None:
        if hasattr(self, "sound_volume_value"):
            self.sound_volume_value.setText(f"{int(value)}%")
        self._configure_sound_player()

    def _choose_custom_sound(self, event: str) -> None:
        edit = getattr(self, "sound_custom_edits", {}).get(event)
        if edit is None:
            return
        current = edit.text().strip()
        start_dir = str(Path(current).expanduser().parent) if current else str(Path.home())
        path, _selected = QFileDialog.getOpenFileName(
            self,
            self._t("انتخاب صدای سفارشی"),
            start_dir,
            self._t("فایل صوتی (*.wav *.ogg *.oga *.mp3 *.m4a *.aac *.flac)"),
        )
        if path:
            edit.setText(path)
            self._configure_sound_player()
            self._play_app_sound(event, force=True)

    def _clear_custom_sounds(self) -> None:
        for edit in getattr(self, "sound_custom_edits", {}).values():
            edit.clear()
        self._configure_sound_player()
        self.toast.show_message(self._t("صداهای سفارشی پاک شدند؛ بستهٔ انتخاب‌شده استفاده می‌شود."))

    def _sync_sound_controls(self, enabled: bool) -> None:
        state = bool(enabled)
        for name in ("sound_theme_combo", "sound_volume_slider"):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(state)
        for control in getattr(self, "sound_event_checks", {}).values():
            control.setEnabled(state)
        for control in getattr(self, "sound_custom_edits", {}).values():
            control.setEnabled(state)
        self._configure_sound_player()

    def _play_app_sound(self, event: str, *, force: bool = False) -> None:
        key = str(event or "").strip().lower()
        if key not in SOUND_EVENTS:
            return
        if not force:
            master = getattr(self, "sound_enabled_check", None)
            if master is not None and not master.isChecked():
                return
            control = getattr(self, "sound_event_checks", {}).get(key)
            if control is not None and not control.isChecked():
                return
        self._configure_sound_player()
        # The Gentle pack is downloaded in the background.  Do not fall back
        # to a harsh OS beep while the selected sound is still being cached.
        played = self.sound_player.play(key)
        if force and not played and self.sound_player.is_preparing():
            self.toast.show_message(self._t("بستهٔ صدای ملایم در حال آماده‌شدن است؛ چند لحظه دیگر دوباره تست کن."))

    def _toggle_subtitle_controls(self, enabled: bool) -> None:
        self.subtitle_language_combo.setEnabled(enabled)
        self.auto_subtitle_check.setEnabled(enabled)

    def _show_missing_dependency(self) -> None:
        self._play_app_sound("warning")
        QMessageBox.information(
            self,
            self._t("نصب وابستگی‌ها"),
            self._t("ابتدا وابستگی‌ها را نصب کنید:\n\npython -m pip install -U -r requirements.txt"),
        )

    def _load_settings(self) -> None:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._apply_theme()
            self._toggle_subtitle_controls(False)
            self._toggle_auth_controls(self.auth_combo.currentIndex())
            return

        self.output_edit.setText(str(data.get("output_dir", self.output_edit.text())))

        saved_preset = str(data.get("preset", "auto"))
        if saved_preset not in PRESETS:
            saved_preset = next(
                (key for key, preset in PRESETS.items() if saved_preset in {preset.label_fa, preset.label_en}),
                "auto",
            )
        self._set_combo_data(self.preset_combo, saved_preset)

        saved_source = str(data.get("auth_source", "none"))
        if saved_source not in AUTH_CHOICES:
            saved_source = next(
                (key for key, labels in AUTH_CHOICES.items() if saved_source in labels),
                "browser" if data.get("browser") else "none",
            )
        self._set_combo_data(self.auth_combo, saved_source)
        self._set_combo(self.browser_combo, str(data.get("browser", "Chrome")))
        self.browser_profile_edit.setText(str(data.get("browser_profile", "")))
        self.cookie_file_edit.setText(str(data.get("cookie_file", "")))
        self.cookie_domain_edit.setText(str(data.get("cookie_domain", "")))
        self.remember_auth_check.setChecked(bool(data.get("remember_auth", True)))
        self.organize_service_check.setChecked(bool(data.get("organize_service", True)))
        self.playlist_check.setChecked(bool(data.get("playlist", True)))
        self.metadata_check.setChecked(bool(data.get("metadata", True)))
        self.thumbnail_check.setChecked(bool(data.get("thumbnail", False)))
        self.subtitle_check.setChecked(bool(data.get("subtitles", False)))
        self.auto_subtitle_check.setChecked(bool(data.get("auto_subtitles", True)))
        self.mark_watched_check.setChecked(bool(data.get("mark_watched", False)))
        if hasattr(self, "sound_enabled_check"):
            self.sound_enabled_check.setChecked(bool(data.get("sound_enabled", True)))
            raw_sound_theme = str(data.get("sound_theme", DEFAULT_SOUND_THEME)).strip().lower()
            self._set_combo_data(self.sound_theme_combo, normalize_sound_theme(raw_sound_theme))
            try:
                saved_volume = max(0, min(100, int(data.get("sound_volume", DEFAULT_VOLUME))))
            except (TypeError, ValueError):
                saved_volume = DEFAULT_VOLUME
            if raw_sound_theme in {"minimal", "soft", "digital"}:
                saved_volume = min(saved_volume, DEFAULT_VOLUME)
            self.sound_volume_slider.setValue(saved_volume)
            event_state = data.get("sound_events") if isinstance(data.get("sound_events"), dict) else {}
            legacy = {
                "download_complete": bool(data.get("sound_success", True)),
                "error": bool(data.get("sound_error", True)),
                "cancelled": bool(data.get("sound_cancelled", True)),
            }
            for key, control in self.sound_event_checks.items():
                control.setChecked(bool(event_state.get(key, legacy.get(key, True))))
            custom_state = data.get("sound_custom") if isinstance(data.get("sound_custom"), dict) else {}
            for key, edit in self.sound_custom_edits.items():
                edit.setText(str(custom_state.get(key) or ""))
            self._sync_sound_controls(self.sound_enabled_check.isChecked())
        self._refresh_audio_language_combo(str(data.get("audio_language", "")))
        saved_subtitle = str(data.get("subtitle_language") or "")
        if not saved_subtitle:
            saved_subtitle = next((item.strip() for item in str(data.get("subtitle_langs", "")).split(",") if item.strip()), "all")
        self._refresh_subtitle_language_combo(saved_subtitle)
        self.fragments_spin.setValue(max(1, min(16, int(data.get("fragments", 4)))))

        saved_runtime = str(data.get("js_runtime", "auto"))
        if saved_runtime not in RUNTIME_CHOICES:
            saved_runtime = next(
                (key for key, labels in RUNTIME_CHOICES.items() if saved_runtime in labels),
                "auto",
            )
        self._set_combo_data(self.runtime_combo, saved_runtime)
        self.runtime_path_edit.setText(str(data.get("js_runtime_path", "")))
        if hasattr(self, "spotify_official_api_check"):
            self.spotify_official_api_check.setChecked(bool(data.get("spotify_use_official_api", False)))
        if hasattr(self, "spotify_client_id_edit"):
            self.spotify_client_id_edit.setText(str(data.get("spotify_client_id", "")))
        if hasattr(self, "spotify_client_secret_edit"):
            self.spotify_client_secret_edit.clear()
        if hasattr(self, "spotify_proxy_edit"):
            self.spotify_proxy_edit.setText(str(data.get("spotify_proxy", "")))
        if hasattr(self, "google_play_email_edit"):
            self.google_play_email_edit.setText(str(data.get("google_play_email", "")))
        if hasattr(self, "google_play_aas_token_edit"):
            self.google_play_aas_token_edit.clear()
        if hasattr(self, "search_service_combo"):
            self._set_combo_data(self.search_service_combo, str(data.get("search_service", "youtube")))
            self.search_limit_spin.setValue(max(3, min(30, int(data.get("search_limit", 10)))))
        saved_theme = str(data.get("theme", "youtube"))
        if int(data.get("ui_version", 0) or 0) < 4:
            saved_theme = "youtube"
        self.theme = theme_from_name(saved_theme)
        if hasattr(self, "settings_theme_combo"):
            self._set_combo_data(self.settings_theme_combo, self.theme.name)
        if hasattr(self, "settings_language_combo"):
            self._set_combo_data(self.settings_language_combo, self.language)
        self._apply_theme()
        self._toggle_subtitle_controls(self.subtitle_check.isChecked())
        self._toggle_auth_controls(self.auth_combo.currentIndex())

    @staticmethod
    def _set_combo(combo: QComboBox, text: str) -> None:
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _save_settings(self) -> None:
        data = {
            "output_dir": self.output_edit.text(),
            "preset": self._combo_data(self.preset_combo, "auto"),
            "auth_source": self._combo_data(self.auth_combo, "none"),
            "browser": self.browser_combo.currentText(),
            "browser_profile": self.browser_profile_edit.text(),
            "cookie_file": self.cookie_file_edit.text(),
            "cookie_domain": self.cookie_domain_edit.text(),
            "remember_auth": self.remember_auth_check.isChecked(),
            "organize_service": self.organize_service_check.isChecked(),
            "playlist": self.playlist_check.isChecked(),
            "metadata": self.metadata_check.isChecked(),
            "thumbnail": self.thumbnail_check.isChecked(),
            "subtitles": self.subtitle_check.isChecked(),
            "auto_subtitles": self.auto_subtitle_check.isChecked(),
            "mark_watched": self.mark_watched_check.isChecked(),
            "sound_enabled": self.sound_enabled_check.isChecked() if hasattr(self, "sound_enabled_check") else True,
            "sound_theme": self._combo_data(self.sound_theme_combo, DEFAULT_SOUND_THEME) if hasattr(self, "sound_theme_combo") else DEFAULT_SOUND_THEME,
            "sound_volume": self.sound_volume_slider.value() if hasattr(self, "sound_volume_slider") else DEFAULT_VOLUME,
            "sound_events": {key: control.isChecked() for key, control in getattr(self, "sound_event_checks", {}).items()},
            "sound_custom": self._sound_custom_paths(),
            "subtitle_language": self._selected_subtitle_language(),
            "audio_language": self._selected_audio_language(),
            "fragments": self.fragments_spin.value(),
            "js_runtime": self._combo_data(self.runtime_combo, "auto"),
            "js_runtime_path": self.runtime_path_edit.text(),
            "spotify_use_official_api": self.spotify_official_api_check.isChecked() if hasattr(self, "spotify_official_api_check") else False,
            "spotify_client_id": self.spotify_client_id_edit.text().strip() if hasattr(self, "spotify_client_id_edit") else "",
            "spotify_proxy": self.spotify_proxy_edit.text().strip() if hasattr(self, "spotify_proxy_edit") else "",
            "google_play_email": self.google_play_email_edit.text().strip() if hasattr(self, "google_play_email_edit") else "",
            "search_service": self._combo_data(self.search_service_combo, "youtube") if hasattr(self, "search_service_combo") else "youtube",
            "search_limit": self.search_limit_spin.value() if hasattr(self, "search_limit_spin") else 10,
            "theme": self.theme.name,
            "language": self.language,
            "ui_version": 4,
        }
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        lines: list[str] = []
        if event.mimeData().hasUrls():
            lines.extend(url.toString() for url in event.mimeData().urls())
        elif event.mimeData().hasText():
            lines.extend(event.mimeData().text().splitlines())
        existing = self.urls_edit.toPlainText().strip()
        added = "\n".join(line.strip() for line in lines if line.strip())
        self.urls_edit.setPlainText(f"{existing}\n{added}".strip())
        self.toast.show_message(self._t("لینک‌ها به صف اضافه شدند"))
        event.acceptProposedAction()

    def is_effectively_maximized(self) -> bool:
        """Return the visual maximize state used by the custom title bar."""
        return bool(self._pseudo_maximized or self.isMaximized() or self.isFullScreen())

    def _expanded_window(self) -> bool:
        return self.is_effectively_maximized()

    def _stop_intro_animation(self) -> None:
        if self._intro_animation is not None:
            self._intro_animation.stop()
            self._intro_animation.deleteLater()
            self._intro_animation = None
        self.setWindowOpacity(1.0)

    def _schedule_native_blur(self, delay_ms: int = 140) -> None:
        self._native_blur_timer.stop()
        if self._window_state_transition or self._expanded_window() or not self.isVisible():
            disable_native_blur(self)
            return
        self._native_blur_timer.start(max(0, int(delay_ms)))

    def _enable_blur_if_safe(self) -> None:
        if self._window_state_transition or self._expanded_window() or not self.isVisible():
            return
        enable_native_blur(self, dark=self.theme.dark)

    def toggle_maximize_restore(self) -> None:
        """Maximize without asking Qt/DWM to change the native window state.

        Some Windows systems crash when a frameless translucent PySide window
        enters the native maximized state.  Leon therefore performs a safe
        "visual maximize": it stores the normal geometry and fits the window
        to the current monitor's available desktop area.  Restoring simply
        reapplies the saved geometry.  No native maximize transition, Acrylic
        call, or fullscreen surface recreation is involved.
        """
        if self._window_state_transition:
            return

        self._window_state_transition = True
        self._stop_intro_animation()
        self._native_blur_timer.stop()
        if hasattr(self, "surface"):
            self.surface.set_reduced_motion(True)

        def apply_geometry() -> None:
            try:
                if self._pseudo_maximized:
                    self._pseudo_maximized = False
                    restore = self._restore_geometry
                    if restore is not None and restore.isValid():
                        self.setGeometry(restore)
                    else:
                        self.resize(1380, 900)
                        screen = self.screen() or QApplication.primaryScreen()
                        if screen is not None:
                            area = screen.availableGeometry()
                            self.move(area.center() - self.rect().center())
                else:
                    self._restore_geometry = self.geometry()
                    screen = self.screen() or QApplication.primaryScreen()
                    if screen is None:
                        self._pseudo_maximized = False
                        return
                    self._pseudo_maximized = True
                    self.setGeometry(screen.availableGeometry())
            finally:
                self._window_state_timer.start(80)

        QTimer.singleShot(0, apply_geometry)

    def _finish_window_state_transition(self) -> None:
        self._window_state_transition = False
        self._sync_window_state()

    def _sync_window_state(self) -> None:
        expanded = self._expanded_window()
        if hasattr(self, "title_bar"):
            self.title_bar._update_maximize_icon()
        if hasattr(self, "surface"):
            self.surface.set_reduced_motion(expanded)
        if hasattr(self, "root_layout"):
            margin = 0 if expanded else 12
            self.root_layout.setContentsMargins(margin, margin, margin, margin)
        if expanded:
            self._native_blur_timer.stop()
            disable_native_blur(self)
        else:
            self._schedule_native_blur(180)
        self._responsive_layout_timer.start(90)

    def _apply_responsive_layout(self) -> None:
        if self._window_state_transition:
            self._responsive_layout_timer.start(120)
            return
        if not hasattr(self, "main_splitter"):
            return
        desired = Qt.Orientation.Vertical if self.width() < 1180 else Qt.Orientation.Horizontal
        if self.main_splitter.orientation() != desired:
            self.main_splitter.setUpdatesEnabled(False)
            try:
                self.main_splitter.setOrientation(desired)
                if desired == Qt.Orientation.Horizontal:
                    self.main_splitter.setSizes([540, 650])
                else:
                    self.main_splitter.setSizes([360, 420])
            finally:
                self.main_splitter.setUpdatesEnabled(True)
            self.main_splitter.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and hasattr(self, "_responsive_layout_timer")
        ):
            # Qt reports the final maximized state after this handler returns.
            QTimer.singleShot(0, self._sync_window_state)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_window_state()
        if not self._intro_played and not self._expanded_window():
            self._intro_played = True
            self.setWindowOpacity(0.0)
            self._intro_animation = QPropertyAnimation(self, b"windowOpacity", self)
            self._intro_animation.setDuration(300)
            self._intro_animation.setStartValue(0.0)
            self._intro_animation.setEndValue(1.0)
            self._intro_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._intro_animation.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Never mutate QSplitter orientation synchronously in resizeEvent.
        if hasattr(self, "_responsive_layout_timer"):
            self._responsive_layout_timer.start(70)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.move((self.surface.width() - self.toast.width()) // 2, 90)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker and self.worker.isRunning():
            # A user who already pressed Cancel must not be asked a second time.
            if not self._download_cancel_requested:
                result = QMessageBox.question(
                    self,
                    self._t("خروج از برنامه"),
                    self._t("دانلود هنوز در حال اجراست. دانلود لغو و برنامه بسته شود؟"),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if result != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
                self._download_cancel_requested = True
                self.worker.cancel()
            self._close_when_worker_stops = True
            self.status_label.setText(self._t("در حال خروج"))
            self.detail_label.setText(self._t("در حال بستن دانلود لغوشده…"))
            self._schedule_forced_cancel_close()
            event.ignore()
            return
        self._prepare_final_close()
        event.accept()

    def _download_thread_finished(self) -> None:
        self._set_busy(False)
        self._download_cancel_requested = False
        self._forced_close_scheduled = False

    def _schedule_forced_cancel_close(self) -> None:
        if self._forced_close_scheduled:
            return
        self._forced_close_scheduled = True
        QTimer.singleShot(2200, self._force_stop_cancelled_worker_for_exit)

    def _force_stop_cancelled_worker_for_exit(self) -> None:
        self._forced_close_scheduled = False
        worker = self.worker
        if not self._close_when_worker_stops or worker is None:
            return
        if worker.isRunning():
            self._append_log(self._t("لغو معمولی بیش از حد طول کشید؛ Worker فقط برای خروج برنامه متوقف می‌شود."))
            worker.terminate()
            worker.wait(1200)
        self._finish_deferred_close()

    def _prepare_final_close(self) -> None:
        for metadata_worker in self.later_metadata_workers:
            if metadata_worker.isRunning():
                metadata_worker.requestInterruption()
        if self.queue_metadata_worker and self.queue_metadata_worker.isRunning():
            self.queue_metadata_worker.requestInterruption()
        clear_app_heartbeat()
        self._save_settings()

    def _finish_deferred_close(self) -> None:
        if self._close_when_worker_stops:
            self._close_when_worker_stops = False
            self._prepare_final_close()
            QTimer.singleShot(0, self.close)
