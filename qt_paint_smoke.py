from __future__ import annotations

"""Small offscreen smoke test for Leon's custom-painted Qt widgets.

It catches Python exceptions raised by paintEvent overrides and serious QPainter /
QBackingStore warnings before the real window is shown.
"""

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import qInstallMessageHandler  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.theme import YOUTUBE  # noqa: E402
from ui.widgets import AuroraSurface, BrandMark, EmptyStateGraphic, SpeedWaveWidget, make_line_icon  # noqa: E402


_FATAL_QT_FRAGMENTS = (
    "QPainter::begin",
    "Painter not active",
    "QBackingStore::endPaint",
    "Cannot destroy paint device",
)


def main() -> int:
    python_errors: list[str] = []
    qt_errors: list[str] = []

    old_hook = sys.excepthook

    def exception_hook(exc_type, exc, tb) -> None:
        python_errors.append("".join(traceback.format_exception(exc_type, exc, tb)))

    def message_handler(_mode, _context, message: str) -> None:
        if any(fragment in message for fragment in _FATAL_QT_FRAGMENTS):
            qt_errors.append(message)

    sys.excepthook = exception_hook
    previous_handler = qInstallMessageHandler(message_handler)
    app = QApplication.instance() or QApplication([])

    try:
        # Icons are painted into high-DPI pixmaps.
        for name in ("minimize", "maximize", "restore", "close", "theme", "language", "search", "history", "later", "log"):
            icon = make_line_icon(name, YOUTUBE.text, accent=YOUTUBE.accent)
            if icon.isNull():
                raise RuntimeError(f"Generated icon is null: {name}")

        brand = BrandMark()
        brand.set_theme(YOUTUBE)
        brand.show()

        empty = EmptyStateGraphic()
        empty.set_theme(YOUTUBE)
        empty.show()

        surface = AuroraSurface()
        surface.set_theme(YOUTUBE)
        surface.set_reduced_motion(True)
        surface.resize(1920, 1000)
        surface.show()

        speed_wave = SpeedWaveWidget()
        speed_wave.set_theme(YOUTUBE)
        speed_wave.set_speed(8_000_000)
        speed_wave.resize(640, 64)
        speed_wave.show()

        app.processEvents()

        for widget in (brand, empty, surface, speed_wave):
            target = QPixmap(widget.size())
            target.fill()
            widget.render(target)
            app.processEvents()

        # Force the same repaint path that is exercised by the pseudo-maximize
        # button and monitor-sized geometry changes.
        surface.resize(2560, 1400)
        surface.repaint()
        empty.repaint()
        brand.repaint()
        app.processEvents()

        if python_errors:
            raise RuntimeError("Custom paint exception:\n" + "\n".join(python_errors))
        if qt_errors:
            raise RuntimeError("Qt paint warning:\n" + "\n".join(qt_errors))

        print("Qt paint smoke test: OK")
        return 0
    finally:
        for widget in (locals().get("surface"), locals().get("empty"), locals().get("brand"), locals().get("speed_wave")):
            if widget is not None:
                widget.close()
                widget.deleteLater()
        app.processEvents()
        qInstallMessageHandler(previous_handler)
        sys.excepthook = old_hook


if __name__ == "__main__":
    raise SystemExit(main())
