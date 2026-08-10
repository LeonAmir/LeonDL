from __future__ import annotations

from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    downloader = (root / "core" / "downloader.py").read_text(encoding="utf-8")
    window = (root / "ui" / "window.py").read_text(encoding="utf-8")

    assert "item_finished = Signal(str)" in downloader
    assert "self.item_finished.emit(url)" in downloader
    assert "self.worker.item_finished.connect(self._on_download_item_finished)" in window
    assert "def _on_download_item_finished(self, completed_url: str)" in window
    assert "self._remove_completed_download_input(completed_url)" in window
    assert "self._play_app_sound(\"download_complete\")" in window
    assert "def _remove_completed_download_input(self, completed_url: str)" in window
    assert "self.urls_edit.clear()" not in window[window.index("def _remove_completed_download_input"):window.index("def _prepare_preview_cards")]
    finish_block = window[window.index("def _finish_success"):window.index("def _finish_cancelled")]
    assert "_clear_completed_download_inputs" not in finish_block
    print("Completed input cleanup smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
