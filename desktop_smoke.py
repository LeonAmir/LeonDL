"""Check the web desktop's Python operations independently of any GUI toolkit."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys

from core.desktop import Desktop
from core.workers import Worker, Signal


class StubDownload(Worker):
    progress = Signal(dict)
    log = Signal(str)
    postprocess = Signal(str)
    item_finished = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, urls, options, *_args):
        super().__init__()
        self.urls = urls
        self.options = options
        self.received_by_url = {}

    def run(self):
        for url in self.urls:
            self.received_by_url[url] = 1024
            self.progress.emit({"status":"finished","title":"Example","service":"Test","percent":100})
            self.item_finished.emit(url)
        self.finished_ok.emit()


def main():
    with TemporaryDirectory() as folder, patch("core.desktop.read_clipboard", return_value=""), patch(
        "core.desktop.browser_bridge.touch_app_heartbeat"
    ), patch("core.desktop.browser_bridge.consume_browser_requests", return_value=[]), patch(
        "core.desktop.javascript_runtime_options", return_value=({},None)
    ), patch("core.desktop.DownloadWorker", StubDownload):
        root=Path(folder)
        url="https://example.com/demo"
        app=Desktop("2.7.1",root)
        assert app.dispatch("save",{"output_dir":str(root/"files"),"theme":"royal_navy",
                                    "sound_enabled":False,"language":"en"})["ok"]
        assert app.dispatch("queue_add",{"urls":f"{url}\n{url}"})["ok"]
        assert app.dispatch("queue_quality",{"index":0,"preset":"video_720"})["ok"]
        assert app.snapshot()["queue"][0]["preset"]=="video_720"
        assert app.dispatch("download",{"urls":url,"codecs":{url:"av1"}})["ok"]
        assert app._worker.wait(2000)
        assert app._worker.options["_leon_video_codecs"]=={url:"av1"}
        state=app.snapshot()
        assert state["received"]==1024 and state["history"][0]["received_bytes"]==1024
        assert state["progress"]["status"]=="completed"
        assert state["batch"][0]["status"]=="completed"
        assert state["incoming"]==[{"action":"completed","url":url}]
        assert app.dispatch("history_clear")["ok"] and app.snapshot()["received"]==1024
        assert app.dispatch("run_shell",{"command":"ignored"})["error"]
        reloaded=Desktop("2.7.1",root).snapshot()
        assert reloaded["settings"]["theme"]=="royal_navy"
        assert len(reloaded["themes"])==5
        assert "PySide6" not in sys.modules
    print("Desktop: Python workers, settings, queue, codec, history, usage and bridge passed without Qt.")


if __name__=="__main__":
    main()
