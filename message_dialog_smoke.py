from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    theme_text = (ROOT / "ui" / "theme.py").read_text(encoding="utf-8")
    window_text = (ROOT / "ui" / "window.py").read_text(encoding="utf-8")

    assert "def build_message_box_stylesheet" in theme_text
    assert "QMessageBox QLabel" in theme_text
    assert "QMessageBox QPushButton" in theme_text
    assert "dialog.setStyleSheet(build_message_box_stylesheet(self.theme))" in window_text
    assert "An unknown error occurred" in window_text
    assert "یک خطای نامشخص رخ داد" in window_text
    assert "_persist_error_report" in window_text
    assert "setDetailedText" in window_text
    print("Message dialog smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
