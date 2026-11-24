"""Regressions for link removal, strict video codecs, and the usage counter."""
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication
from yt_dlp import YoutubeDL

from core.downloader import DownloadWorker, _codec_selector, available_video_codecs
from core.history_store import HistoryStore
from ui.window import MainWindow


def main() -> None:
    app = QApplication.instance() or QApplication([])
    formats = [
        {"format_id": "avc", "vcodec": "avc1.64001f", "acodec": "aac", "height": 1080, "ext": "mp4"},
        {"format_id": "av1", "vcodec": "av01.0.08M", "acodec": "opus", "height": 720, "ext": "webm"},
    ]
    info = {"title": "Sample", "formats": formats}
    assert available_video_codecs(info) == ["h264", "av1"]
    with YoutubeDL({"quiet": True}) as ydl:
        selector = _codec_selector("bv*[height<=1080]+ba/b[height<=1080]/ba", "av1")
        selected = list(ydl.build_format_selector(selector)({
            "formats": formats, "has_merged_format": True, "incomplete_formats": False,
        }))
        assert [fmt["format_id"] for fmt in selected] == ["av1"]
        assert not list(ydl.build_format_selector(selector)({
            "formats": formats[:1], "has_merged_format": True, "incomplete_formats": False,
        }))

    first = "https://example.com/first"
    second = "https://example.com/second"
    window = MainWindow()
    window.urls_edit.setPlainText(f"{first}\n{second}")
    window._prepare_preview_cards([first, second])
    window._preview_request_urls = (first, second)
    window.preview_cards[0].remove_requested.emit(first)
    assert window._urls() == [second]
    window._route_preview_ready(0, info)
    assert window.preview_results[0]["state"] == "pending"
    window._route_preview_ready(1, info)
    card = window.preview_cards[0]
    card.video_codec.setCurrentIndex(card.video_codec.findData("av1"))
    saved = window._capture_preview_state()
    window._restore_preview_state(saved)
    assert window.preview_cards[0].video_codec.currentData() == "av1"

    worker = DownloadWorker([second], {})
    worker._transfer_url = second
    for path, amount, state in [("video", 3, "downloading"), ("video", 5, "downloading"),
                                ("video", 5, "finished"), ("audio", 2, "downloading")]:
        worker._progress_hook({"status": state, "filename": path, "downloaded_bytes": amount})
    assert worker.received_by_url == {second: 7}
    with TemporaryDirectory() as folder:
        history = HistoryStore(Path(folder))
        history.add_received_bytes(7)
        history.add_received_bytes(3)
        history.clear()
        assert HistoryStore(Path(folder)).received_bytes() == 10
    app.quit()
    print("Download controls and history usage smoke test: OK")


if __name__ == "__main__":
    main()
