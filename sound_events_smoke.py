from __future__ import annotations

import os
import tempfile
from pathlib import Path

import core.sound_events as sound_events
from core.sound_events import (
    DEFAULT_SOUND_THEME,
    GENTLE_EVENT_ASSET,
    INTERNET_SOUND_ASSETS,
    SOUND_EVENTS,
    SOUND_THEMES,
    SUPPORTED_CUSTOM_AUDIO,
    cached_internet_asset,
    download_internet_sound_asset,
    normalize_sound_event,
    normalize_sound_theme,
    resolve_sound_path,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.payload


def main() -> None:
    expected = {
        "download_complete",
        "queue_complete",
        "error",
        "warning",
        "cancelled",
        "notification",
    }
    assert SOUND_EVENTS == expected
    assert DEFAULT_SOUND_THEME == "gentle"
    assert set(SOUND_THEMES) == {"gentle", "system"}
    assert normalize_sound_theme("minimal") == "gentle"
    assert normalize_sound_theme("soft") == "gentle"
    assert normalize_sound_theme("digital") == "gentle"
    assert normalize_sound_event("not-an-event") == ""
    assert set(GENTLE_EVENT_ASSET) == expected
    assert ".wav" in SUPPORTED_CUSTOM_AUDIO and ".ogg" in SUPPORTED_CUSTOM_AUDIO and ".mp3" in SUPPORTED_CUSTOM_AUDIO

    for asset_key, asset in INTERNET_SOUND_ASSETS.items():
        assert str(asset["source_page"]).startswith("https://commons.wikimedia.org/wiki/File:")
        assert str(asset["download_url"]).startswith("https://commons.wikimedia.org/wiki/Special:Redirect/file/")
        assert asset["license"] == "CC0-1.0"
        assert str(asset["filename"]).endswith(".ogg")
        assert int(asset["max_bytes"]) <= 500_000

    original_urlopen = sound_events.urlopen
    old_cache = os.environ.get("LEON_SOUND_CACHE_DIR")
    try:
        with tempfile.TemporaryDirectory() as temporary:
            os.environ["LEON_SOUND_CACHE_DIR"] = temporary
            payload = b"OggS" + b"\0" * 1024
            sound_events.urlopen = lambda *_args, **_kwargs: FakeResponse(payload)
            path = download_internet_sound_asset("happy_beep")
            assert path is not None and path.is_file()
            assert path.read_bytes().startswith(b"OggS")
            assert cached_internet_asset("happy_beep") == path

            custom = Path(temporary) / "custom.mp3"
            custom.write_bytes(b"ID3" + b"\0" * 64)
            resolved = resolve_sound_path("gentle", "notification", {"notification": str(custom)})
            assert resolved == custom
    finally:
        sound_events.urlopen = original_urlopen
        if old_cache is None:
            os.environ.pop("LEON_SOUND_CACHE_DIR", None)
        else:
            os.environ["LEON_SOUND_CACHE_DIR"] = old_cache

    assert resolve_sound_path("system", "error") is None
    print("Sound events smoke test: OK")


if __name__ == "__main__":
    main()
