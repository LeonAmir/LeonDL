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


if getattr(sys, "frozen", False):
    from core.engine_update import activate_engine, activate_extra_engines, probe_engine, probe_extra

    if len(sys.argv) in {3, 4} and sys.argv[1] == "--leondl-engine-probe":
        root = Path(sys.argv[2])
        raise SystemExit(probe_extra(root, sys.argv[3]) if len(sys.argv) == 4 else probe_engine(root))
    activate_engine()
    activate_extra_engines()


from bootstrap import SetupReport, ensure_environment

APP_VERSION = "2.7.2"


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

def main() -> int:
    import base64
    import webview

    from core import browser_bridge
    from core.desktop import Desktop

    if sys.platform == "win32":
        from webview.platforms import winforms

        if not winforms.is_chromium:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, "Microsoft Edge WebView2 Runtime is required to open LeonDL.",
                "LeonDL", 0x10,
            )
            return 1

    root = Path(__file__).resolve().parent / "assets"
    web = root / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "app.css").read_text(encoding="utf-8")
    for face, weight in (("Regular", 400), ("Bold", 700)):
        font = base64.b64encode((web / "fonts" / f"Vazir-{face}.woff2").read_bytes()).decode("ascii")
        css += (
            f"@font-face{{font-family:Vazir;src:url(data:font/woff2;base64,{font}) "
            f"format('woff2');font-weight:{weight};font-display:swap}}"
        )
    script = (web / "app.js").read_text(encoding="utf-8-sig")
    icon = "data:image/png;base64," + base64.b64encode((web / "icon.png").read_bytes()).decode("ascii")
    html = html.replace("__STYLE__", css).replace("__SCRIPT__", script).replace("__ICON__", icon)
    desktop = Desktop(APP_VERSION)
    window = webview.create_window(f"LeonDL {APP_VERSION}", html=html, js_api=desktop,
                                   width=1300, height=900, min_size=(760, 560), frameless=False,
                                   text_select=True, background_color="#101424")
    desktop._window = window

    def closing():
        worker = desktop._worker
        if worker and worker.isRunning() and not desktop._allowed_close:
            desktop._request_close_confirmation()
            return False
        return True

    window.events.closing += closing
    window.events.closed += browser_bridge.clear_app_heartbeat
    webview.start(gui="edgechromium" if sys.platform == "win32" else None, private_mode=True,
                  icon=str(root / "app_icon.ico"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
