from __future__ import annotations

import faulthandler
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


def _native_host_mode() -> bool:
    return "--native-messaging-host" in sys.argv or any(
        str(argument or "").startswith("chrome-extension://") for argument in sys.argv[1:]
    )


# Native Messaging must own stdout from the first byte. Dispatch before runtime
# logging, bootstrap, Qt, or any dependency that could print to the protocol.
if _native_host_mode():
    from core.browser_bridge import run_native_host

    raise SystemExit(run_native_host(sys.argv))


from bootstrap import SetupReport, ensure_environment

APP_VERSION = "2.6.7"


def _install_runtime_logging() -> None:
    """Keep Python/native crash details in a predictable per-user log."""
    try:
        log_dir = Path.home() / ".yt_dlp_liquid"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "leon_runtime.log"
        handle = log_path.open("a", encoding="utf-8", buffering=1)
        globals()["_RUNTIME_LOG_HANDLE"] = handle
        faulthandler.enable(file=handle, all_threads=True)

        previous_hook = sys.excepthook

        def hook(exc_type, exc_value, exc_tb) -> None:
            handle.write("\n--- unhandled exception ---\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=handle)
            handle.flush()
            previous_hook(exc_type, exc_value, exc_tb)

        sys.excepthook = hook
    except Exception:
        pass


_install_runtime_logging()

# The console-free launcher performs the full bootstrap only when its dependency
# fingerprint changes. Frozen builds already contain their Python packages.
_BOOTSTRAP_ALREADY_DONE = os.environ.get("LEON_BOOTSTRAP_DONE") == "1" or getattr(sys, "frozen", False)
_SETUP_REPORT: SetupReport = (
    SetupReport()
    if _BOOTSTRAP_ALREADY_DONE
    else ensure_environment(install=True, include_external=False, verbose=True)
)
if not _SETUP_REPORT.python_ok or not _SETUP_REPORT.python_packages_ok:
    missing = ", ".join(_SETUP_REPORT.missing) or "Python requirements"
    raise SystemExit(f"LeonDL could not prepare its Python environment: {missing}")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.splash import StartupSplash
from ui.theme import theme_from_name


def _apply_application_font(app: QApplication) -> str:
    """Prefer Vazir without bundling or exposing a font file."""
    available = set(QFontDatabase.families())
    for family in ("Vazir", "Vazirmatn", "Tahoma", "Segoe UI"):
        if family in available:
            font = QFont(family)
            font.setPointSizeF(10.0)
            app.setFont(font)
            return family
    return app.font().family()


def _initial_settings() -> dict[str, Any]:
    try:
        payload = json.loads((Path.home() / ".yt_dlp_liquid" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _initial_language(settings: dict[str, Any] | None = None) -> str:
    payload = settings if settings is not None else _initial_settings()
    return "en" if str(payload.get("language") or "fa").lower() == "en" else "fa"


def _show_setup_result(window: Any) -> None:
    if _SETUP_REPORT.installed:
        prefix = "Dependencies ready: " if window.language == "en" else "پیش‌نیازها آماده شدند: "
        separator = ", " if window.language == "en" else "، "
        window.toast.show_message(prefix + separator.join(_SETUP_REPORT.installed), duration_ms=4200)
    if _SETUP_REPORT.missing:
        QMessageBox.warning(
            window,
            "بررسی پیش‌نیازها",
            "برخی پیش‌نیازهای جانبی هنوز در دسترس نیستند:\n\n"
            + "\n".join(f"• {item}" for item in _SETUP_REPORT.missing)
            + "\n\nفایل setup_windows.bat را اجرا کنید یا نصب را از مدیریت پکیج‌ها انجام دهید.",
        )


def _signal_launcher_ready() -> None:
    ready_file = str(os.environ.get("LEON_READY_FILE") or "").strip()
    if not ready_file:
        return
    try:
        Path(ready_file).write_text("ready", encoding="utf-8")
    except OSError:
        pass


def _start_prerequisite_worker(window: Any) -> None:
    """Frozen builds bundle Python packages but need FFmpeg/FFprobe/Deno as
    external tools. Check for them in the background and install what is
    missing through WinGet, without blocking the visible window."""
    from core.package_manager import PrerequisiteWorker

    worker = PrerequisiteWorker()
    # Keep a strong reference so Python GC cannot destroy the running thread.
    window._prerequisite_worker = worker

    def on_log(text: str) -> None:
        if hasattr(window, "_append_log"):
            window._append_log(text)

    def on_done(installed: list[str], failed: list[str]) -> None:
        if installed:
            if window.language == "en":
                message = "Prerequisites ready: " + ", ".join(installed)
            else:
                message = "پیش‌نیازها آماده شدند: " + "، ".join(installed)
            window.toast.show_message(message, duration_ms=4200)
        if failed:
            if window.language == "en":
                note = "Some prerequisites could not be installed: " + ", ".join(failed)
            else:
                note = "برخی پیش‌نیازها نصب نشدند: " + "، ".join(failed)
            window._append_log(note)

    worker.log.connect(on_log)
    worker.done.connect(on_done)
    worker.start()


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("LeonDL")
    app.setOrganizationName("LeonDL")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    _apply_application_font(app)

    icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    initial_settings = _initial_settings()
    initial_language = _initial_language(initial_settings)
    initial_theme = theme_from_name(str(initial_settings.get("theme") or "youtube"))
    external_splash = os.environ.get("LEON_EXTERNAL_SPLASH") == "1"
    splash: StartupSplash | None = None
    if not external_splash:
        splash = StartupSplash(APP_VERSION, initial_language, initial_theme)
        splash.show()
        splash.set_status("Loading interface…" if initial_language == "en" else "در حال بارگذاری رابط…")
        app.processEvents()

    # Importing the full UI after the splash is visible keeps frozen and direct
    # Python launches responsive while the large window module is initialized.
    from ui.window import MainWindow

    if splash:
        splash.set_status("Preparing workspace…" if initial_language == "en" else "در حال آماده‌سازی فضای کار…")
        app.processEvents()

    window = MainWindow()
    window.show()
    app.processEvents()
    _signal_launcher_ready()
    if getattr(sys, "frozen", False):
        # EXE builds: verify/install external prerequisites in the background.
        _start_prerequisite_worker(window)
    if splash:
        splash.finish(window)

    if _SETUP_REPORT.installed or _SETUP_REPORT.missing:
        QTimer.singleShot(650, lambda: _show_setup_result(window))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
