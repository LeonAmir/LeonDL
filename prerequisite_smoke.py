"""Prerequisite auto-install smoke test for frozen (EXE) builds.

Verifies the required-tool catalog, the WinGet command builder, and the
PrerequisiteWorker skip path without performing real installs and without
requiring a display server.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.package_manager import (  # noqa: E402
    FROZEN_REQUIRED_TOOLS,
    PrerequisiteWorker,
    missing_required_tools,
    winget_install_command,
)


def test_tool_catalog() -> None:
    assert "ffmpeg" in FROZEN_REQUIRED_TOOLS
    assert "deno" in FROZEN_REQUIRED_TOOLS


def test_winget_command_builder() -> None:
    # Build without winget availability so the command shape stays checkable.
    ffmpeg = winget_install_command("ffmpeg", check_available=False)
    assert ffmpeg[0] == "winget"
    assert "install" in ffmpeg
    assert "Gyan.FFmpeg" in ffmpeg
    assert "--silent" in ffmpeg
    deno = winget_install_command("deno", check_available=False)
    assert "DenoLand.Deno" in deno
    assert winget_install_command("yt_dlp", check_available=False) == []


def test_missing_required_tools_shape() -> None:
    missing = missing_required_tools()
    assert isinstance(missing, list)
    for key in missing:
        assert key in FROZEN_REQUIRED_TOOLS


def test_worker_skip_check_emits_empty() -> None:
    worker = PrerequisiteWorker(skip_check=True)
    results: list[tuple[list[str], list[str]]] = []

    def capture(installed: list[str], failed: list[str]) -> None:
        results.append((list(installed), list(failed)))

    worker.done.connect(capture)
    worker.run()  # synchronous direct call; no thread or display needed
    assert results == [([], [])]


if __name__ == "__main__":
    test_tool_catalog()
    test_winget_command_builder()
    test_missing_required_tools_shape()
    test_worker_skip_check_emits_empty()
    print("prerequisite_smoke: OK")