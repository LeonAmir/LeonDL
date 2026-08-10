from __future__ import annotations

import tempfile
from pathlib import Path

from core.auth_store import AuthProfileStore, service_domain


def main() -> int:
    assert service_domain("https://www.youtube.com/watch?v=test") == "youtube.com"
    assert service_domain(".youtube.com") == "youtube.com"
    assert service_domain("https://m.youtube.com/shorts/test") == "youtube.com"

    with tempfile.TemporaryDirectory(prefix="leon-extension-cookie-sync-") as temp_dir:
        root = Path(temp_dir)
        source = root / "cookies.txt"
        source.write_text(
            "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n",
            encoding="utf-8",
        )

        # Model the GUI store being created first and the Native Messaging host
        # writing a profile later from another process/store instance.
        gui_store = AuthProfileStore(root)
        native_host_store = AuthProfileStore(root)
        native_host_store.remember_cookie_file(["https://www.youtube.com/watch?v=test"], source, method="extension")

        profile = gui_store.profile("https://youtu.be/test", valid_only=False)
        assert profile is not None
        assert profile["method"] == "extension"
        assert Path(profile["cookie_file"]).is_file()

        gui_store.mark_valid(["www.youtube.com"])
        assert native_host_store.profile("youtube.com") is not None

    window_source = (Path(__file__).resolve().parent / "ui" / "window.py").read_text(encoding="utf-8")
    assert '"extension": ("کوکی دریافت‌شده از افزونه Chrome"' in window_source
    assert "بررسی مجدد وضعیت کوکی افزونه" in window_source
    assert "self.auth_store.refresh(force=True)" in window_source

    print("Extension cookie synchronization smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
