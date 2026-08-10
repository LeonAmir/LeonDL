from __future__ import annotations

from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    window = (root / "ui" / "window.py").read_text(encoding="utf-8")
    sound_events = (root / "core" / "sound_events.py").read_text(encoding="utf-8")
    build = (root / "build_windows.ps1").read_text(encoding="utf-8")
    sources = (root / "assets" / "sounds" / "SOURCES.md").read_text(encoding="utf-8")

    assert "SoundEventPlayer(self)" in window
    assert '"sound_theme"' in window
    assert '"sound_volume"' in window
    assert '"sound_events"' in window
    assert '"sound_custom"' in window
    assert '"gentle"' in window
    assert "*.ogg" in window and "*.mp3" in window
    assert "QMediaPlayer" in sound_events and "QAudioOutput" in sound_events
    assert "Wikimedia Commons" in sources and "CC0 1.0" in sources
    for event in (
        "download_complete",
        "queue_complete",
        "error",
        "warning",
        "cancelled",
        "notification",
    ):
        assert event in window
    assert 'self.worker.item_finished.connect(self._on_download_item_finished)' in window
    assert 'self._play_app_sound("queue_complete")' in window
    assert 'self._play_app_sound("notification")' in window
    assert 'self._play_app_sound("warning")' in window
    assert '--add-data "assets;assets"' in build
    print("Sound UI wiring smoke test: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
