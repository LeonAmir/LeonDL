from __future__ import annotations

import os
import tempfile
from pathlib import Path

from core.auth_store import AuthProfileStore, domains_for_urls, service_domain


def main() -> int:
    assert service_domain("https://www.youtube.com/watch?v=abc") == "youtube.com"
    assert service_domain("https://youtu.be/abc") == "youtube.com"
    assert service_domain("https://m.instagram.com/p/abc") == "instagram.com"
    assert domains_for_urls(["https://youtube.com/a", "https://youtu.be/b"]) == ["youtube.com"]

    with tempfile.TemporaryDirectory(prefix="leon_auth_test_") as temp_dir:
        root = Path(temp_dir)
        store = AuthProfileStore(root)
        store.remember_browser(["youtube.com"], "Firefox", "default-release")
        assert store.profile("youtube.com") is None
        store.mark_valid(["youtube.com"])
        profile = store.profile_for_urls(["https://youtu.be/test"])
        assert profile and profile[1]["browser"] == "Firefox"

        source = root / "cookies.txt"
        source.write_text(
            "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\ttest\tvalue\n",
            encoding="utf-8",
        )
        managed = store.remember_cookie_file(["instagram.com"], source)
        assert managed.is_file()
        extension_managed = store.remember_cookie_file(["youtube.com"], source, method="extension")
        extension_pending = store.profile("youtube.com", valid_only=False)
        assert extension_managed.is_file()
        assert extension_pending and extension_pending["method"] == "extension"

        # The Chrome native host writes profiles from another process while the
        # GUI keeps an AuthProfileStore instance alive. A stale reader must see
        # the newly written profile without being recreated.
        stale_reader = AuthProfileStore(root)
        external_writer = AuthProfileStore(root)
        external_writer.remember_cookie_file(["vimeo.com"], source, method="extension")
        externally_written = stale_reader.profile("https://www.vimeo.com/video", valid_only=False)
        assert externally_written and externally_written["method"] == "extension"
        stale_reader.mark_valid(["vimeo.com"])
        assert external_writer.profile("vimeo.com") is not None
        assert external_writer.profile("youtube.com", valid_only=False) is not None

        store.mark_valid(["instagram.com"])
        assert store.profile("instagram.com") is not None

        if os.name == "nt":
            raw = "Cookie: sessionid=test; csrftoken=token"
            store.remember_manual(["twitter.com"], raw, ".twitter.com")
            pending = store.profile("twitter.com", valid_only=False)
            assert pending is not None
            assert store.read_manual_secret(pending) == raw
            store.mark_valid(["twitter.com"])
            assert store.profile("https://x.com/user") is not None

        store.remove("instagram.com")
        assert store.profile("instagram.com", valid_only=False) is None

    print("Authentication storage smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
