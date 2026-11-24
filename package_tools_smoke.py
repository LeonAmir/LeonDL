import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QTableWidget

from core import package_manager as packages
from ui.window import MainWindow

KEYS = ("yt_dlp", "yt_dlp_ejs", "curl_cffi", "gallery_dl", "spotdl", "apkeep", "ffmpeg", "deno", "pyinstaller")


class PackagePage:
    _package_action_for_key = staticmethod(MainWindow._package_action_for_key)
    _package_action_available = MainWindow._package_action_available

    def __init__(self):
        self.package_table = QTableWidget(0, 6)
        self.theme = SimpleNamespace(success="#00aa00", danger="#aa0000")
        self.actions = []

    def _t(self, value):
        return value

    def _package_description(self, key):
        return key

    def _sync_package_table_height(self):
        pass

    def _detect_runtime(self):
        pass

    def _run_package_action(self, action):
        self.actions.append(action)


def main():
    app = QApplication.instance() or QApplication([])
    with TemporaryDirectory() as folder, patch.object(sys, "frozen", True, create=True):
        page = PackagePage()
        with patch("shutil.which", side_effect=lambda name: name):
            for installed in (True, False):
                MainWindow._render_package_status(page, [{"key": key, "installed": installed} for key in KEYS])
                assert len(page.package_action_buttons) == len(KEYS)
                for button in page.package_action_buttons:
                    assert button.isEnabled(), button.toolTip()
                    button.click()
                mode = "update" if installed else "install"
                assert page.actions[-len(KEYS):] == [f"{mode}_{key}" for key in KEYS]
        with patch("shutil.which", return_value=None), patch.object(packages, "BUILD_ENV", Path(folder)):
            for key in ("gallery_dl", "ffmpeg", "deno", "pyinstaller"):
                available, reason = page._package_action_available(key)
                assert not available and reason

        def run(key):
            result = []
            worker = packages.PackageActionWorker(key)
            worker.finished_action.connect(lambda ok, message: result.append((ok, message)))
            worker.run()
            return result

        with patch.object(packages, "update_engine", return_value="engine") as engine, patch.object(
            packages, "update_extra_engine", return_value="extra"
        ) as extra:
            assert run("update_yt_dlp") == [(True, "engine")]
            assert run("update_yt_dlp_ejs") == [(True, "extra")]
            assert run("update_curl_cffi") == [(True, "extra")]
            engine.assert_called_once()
            assert [call.args[0] for call in extra.call_args_list] == ["yt-dlp-ejs", "curl-cffi"]

        with patch.object(packages, "_install_github_executable") as binary:
            assert run("update_spotdl")[0][0]
            assert run("update_apkeep")[0][0]
            assert len(binary.call_args_list) == 2

        with patch("shutil.which", return_value="winget.exe"), patch.object(
            packages.PackageActionWorker, "_run_command_and_report", return_value=True
        ) as command:
            for key, package_id in packages.PackageActionWorker.WINGET_IDS.items():
                run("update_" + key)
                assert command.call_args.args[0][:4] == ["winget.exe", "upgrade", "--id", package_id]

        with patch.object(packages, "BUILD_ENV", Path(folder)), patch.object(
            packages, "build_python", return_value="python.exe"
        ), patch.object(packages.PackageActionWorker, "_run_command_and_report", return_value=True) as command:
            run("install_pyinstaller")
            assert command.call_args_list[0].args[0] == ["python.exe", "-m", "venv", folder]
            assert command.call_args_list[1].args[0][1:] == ["-m", "pip", "install", "--upgrade", "pyinstaller"]
    print("Packages and Tools: nine rows, all install/update buttons and worker routes passed.")
    app.quit()


if __name__ == "__main__":
    main()
