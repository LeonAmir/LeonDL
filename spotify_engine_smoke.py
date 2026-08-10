from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import core.optional_engines as engines


class FakeYoutubeDL:
    calls: list[tuple[str, object]] = []

    def __init__(self, options: dict[str, object]) -> None:
        self.calls.append(("options", options))

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def download(self, queries: list[str]) -> int:
        self.calls.append(("download", list(queries)))
        return 0


class FakeYtDlp:
    YoutubeDL = FakeYoutubeDL


def _common_setup():
    original = (
        engines._run_process,
        engines.spotdl_available,
        engines.spotdl_executable,
        engines._spotify_oembed,
        engines.yt_dlp,
    )
    engines.spotdl_available = lambda: True
    engines.spotdl_executable = lambda: ""
    engines._spotify_oembed = lambda url, proxy="": {"title": "Example track"}
    engines.yt_dlp = FakeYtDlp()
    return original


def _restore(original) -> None:
    (
        engines._run_process,
        engines.spotdl_available,
        engines.spotdl_executable,
        engines._spotify_oembed,
        engines.yt_dlp,
    ) = original


def main() -> None:
    masked = engines._safe_command_text(
        ["spotdl", "download", "x", "--client-id", "demo", "--client-secret", "very-secret"]
    )
    assert "very-secret" not in masked
    assert "********" in masked
    masked_proxy = engines._safe_command_text(
        ["spotdl", "download", "x", "--proxy", "http://proxy-user:proxy-pass@127.0.0.1:8080"]
    )
    assert "proxy-pass" not in masked_proxy
    assert "proxy-user:********@127.0.0.1:8080" in masked_proxy

    # Existing metadata-service fallback remains available for single tracks.
    process_calls: list[list[str]] = []
    logs: list[str] = []
    FakeYoutubeDL.calls.clear()

    def fail_spotify_metadata(command: list[str], log, cancel_event, *, cwd=None):
        process_calls.append(list(command))
        raise engines.OptionalEngineError(
            "failed",
            output=["SpotifyFree", "spotapi", "RequestError: Failed to complete request."],
        )

    original = _common_setup()
    try:
        engines._run_process = fail_spotify_metadata
        engines.run_spotdl(
            "https://open.spotify.com/track/7jSNus36p3indl4oASNSSZ",
            str(Path.cwd()),
            logs.append,
            threading.Event(),
        )
    finally:
        _restore(original)

    assert process_calls
    assert any(kind == "download" for kind, _ in FakeYoutubeDL.calls)
    assert any("oEmbed" in line for line in logs)

    # A blocked music.youtube.com probe must retry spotDL with standard YouTube.
    process_calls.clear()
    logs.clear()

    def ytmusic_timeout_then_success(command: list[str], log, cancel_event, *, cwd=None):
        process_calls.append(list(command))
        if "--audio" not in command:
            raise engines.OptionalEngineError(
                "failed",
                output=[
                    "ConnectTimeoutError: Connection to music.youtube.com timed out.",
                    "check_ytmusic_connection",
                ],
            )
        assert command[-2:] == ["--audio", "youtube"]
        return []

    original = _common_setup()
    try:
        engines._run_process = ytmusic_timeout_then_success
        engines.run_spotdl(
            "https://open.spotify.com/album/example",
            str(Path.cwd()),
            logs.append,
            threading.Event(),
        )
    finally:
        _restore(original)

    assert len(process_calls) == 2
    assert process_calls[1][-2:] == ["--audio", "youtube"]
    assert any("standard YouTube" in line for line in logs)

    # For a single track, failed default and standard-provider attempts reach Leon fallback.
    process_calls.clear()
    logs.clear()
    FakeYoutubeDL.calls.clear()

    def both_spotdl_attempts_fail(command: list[str], log, cancel_event, *, cwd=None):
        process_calls.append(list(command))
        if "--audio" not in command:
            raise engines.OptionalEngineError(
                "failed",
                output=["ConnectTimeout: music.youtube.com", "WinError 10060"],
            )
        raise engines.OptionalEngineError(
            "failed",
            output=["ERROR: standard YouTube provider failed"],
        )

    original = _common_setup()
    try:
        engines._run_process = both_spotdl_attempts_fail
        engines.run_spotdl(
            "https://open.spotify.com/track/7jSNus36p3indl4oASNSSZ",
            str(Path.cwd()),
            logs.append,
            threading.Event(),
            proxy="http://127.0.0.1:8080",
        )
    finally:
        _restore(original)

    assert len(process_calls) == 2
    assert "--proxy" in process_calls[0]
    assert any(kind == "download" for kind, _ in FakeYoutubeDL.calls)
    print("Spotify engine smoke test: OK")


if __name__ == "__main__":
    main()
