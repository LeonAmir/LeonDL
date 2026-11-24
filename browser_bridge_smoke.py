from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import os
import tempfile
from pathlib import Path


def extension_id_from_key(key: str) -> str:
    public_key = base64.b64decode(key)
    digest = hashlib.sha256(public_key).digest()[:16]
    return "".join(chr(ord("a") + (byte >> 4)) + chr(ord("a") + (byte & 15)) for byte in digest)


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "chrome_extension" / "manifest.json").read_text(encoding="utf-8"))
    expected_id = "cilmnmiidbeningdcggocddbpjmmclmn"
    assert manifest["manifest_version"] == 3
    assert manifest["version"] == "2.7.1"
    assert extension_id_from_key(manifest["key"]) == expected_id
    assert "nativeMessaging" in manifest["permissions"]
    assert "cookies" in manifest["permissions"]
    assert manifest["optional_host_permissions"] == ["*://*/*"]
    bridge_js = (root / "chrome_extension" / "bridge.js").read_text(encoding="utf-8")
    popup_js = (root / "chrome_extension" / "popup.js").read_text(encoding="utf-8")
    background_js = (root / "chrome_extension" / "background.js").read_text(encoding="utf-8")
    assert "chrome.cookies.getAll({url})" in bridge_js
    assert "isPairingError" in popup_js
    assert 'elements.pairingPanel.classList.toggle("hidden", Boolean(settings.pairingToken))' in popup_js
    assert "ensureCookiePermission" in background_js
    assert "cookiesForUserAction" in background_js

    with tempfile.TemporaryDirectory(prefix="leon-browser-bridge-") as temporary_home:
        home_key = "USERPROFILE" if os.name == "nt" else "HOME"
        previous_home = os.environ.get(home_key)
        os.environ[home_key] = temporary_home
        try:
            import core.auth_store as auth_store
            import core.browser_bridge as bridge

            importlib.reload(auth_store)
            bridge = importlib.reload(bridge)
            assert bridge.EXTENSION_ID == expected_id
            assert bridge.EXTENSION_ORIGIN == f"chrome-extension://{expected_id}/"
            token = bridge.pairing_token()
            assert len(token) >= 24
            prefs = bridge.CONFIG_DIR / "settings.json"
            message = {"type": "ping", "pairingToken": token}
            for palette in ("aurora", "obsidian", "royal_navy", "light", "youtube"):
                prefs.write_text(json.dumps({"theme": palette}), encoding="utf-8")
                reply = bridge._handle_native_message(message)
                assert reply["theme"] == palette
                assert set(reply) == {"ok", "version", "app", "theme"}
            prefs.write_text("{invalid", encoding="utf-8")
            assert bridge._handle_native_message(message)["theme"] == "youtube"
            prefs.unlink()

            cookies = [
                {
                    "domain": ".youtube.com",
                    "hostOnly": False,
                    "httpOnly": True,
                    "secure": True,
                    "path": "/",
                    "expirationDate": 2_000_000_000,
                    "name": "SID",
                    "value": "secret-value",
                },
                {
                    "domain": ".example.com",
                    "hostOnly": False,
                    "secure": True,
                    "path": "/",
                    "name": "unrelated",
                    "value": "must-not-be-saved",
                },
                {
                    "domain": ".youtube.com",
                    "hostOnly": False,
                    "secure": True,
                    "path": "/",
                    "name": "partitioned",
                    "value": "skip",
                    "partitionKey": {"topLevelSite": "https://example.com"},
                },
            ]
            netscape, accepted, skipped = bridge._cookies_to_netscape(
                "https://www.youtube.com/watch?v=test", cookies
            )
            assert accepted == 1
            assert skipped == 1
            assert "#HttpOnly_.youtube.com" in netscape
            assert "secret-value" in netscape
            assert "must-not-be-saved" not in netscape

            framed = io.BytesIO()
            bridge._write_native_message(framed, {"hello": "Leon", "version": 1})
            framed.seek(0)
            assert bridge._read_native_message(framed) == {"hello": "Leon", "version": 1}

            try:
                bridge._handle_native_message(
                    {
                        "type": "submit",
                        "action": "queue",
                        "url": "https://www.youtube.com/watch?v=test",
                        "pairingToken": "invalid-token",
                    }
                )
            except bridge.BrowserBridgeError:
                pass
            else:
                raise AssertionError("Invalid pairing token was accepted")

            bridge._start_gui_if_needed = lambda: False
            gui_store_created_before_native_message = auth_store.AuthProfileStore(bridge.CONFIG_DIR)
            response = bridge._handle_native_message(
                {
                    "type": "submit",
                    "action": "queue",
                    "url": "https://www.youtube.com/watch?v=test",
                    "title": "Bridge smoke item",
                    "cookies": cookies,
                    "pairingToken": token,
                }
            )
            assert response["ok"] is True
            assert response["cookiesSaved"] == 1
            stored_profile = auth_store.AuthProfileStore(bridge.CONFIG_DIR).profile("youtube.com", valid_only=False)
            assert stored_profile and stored_profile["method"] == "extension"
            refreshed_gui_profile = gui_store_created_before_native_message.profile(
                "https://www.youtube.com/watch?v=test", valid_only=False
            )
            assert refreshed_gui_profile and refreshed_gui_profile["method"] == "extension"
            request_files = list(bridge.REQUESTS_DIR.glob("*.json"))
            assert len(request_files) == 1
            inbox_text = request_files[0].read_text(encoding="utf-8")
            assert "secret-value" not in inbox_text
            assert "must-not-be-saved" not in inbox_text

            requests = bridge.consume_browser_requests()
            assert len(requests) == 1
            assert requests[0]["action"] == "queue"
            assert requests[0]["title"] == "Bridge smoke item"
            assert requests[0]["url"].startswith("https://www.youtube.com/")
            assert requests[0]["cookie_count"] == 1

            release_dir = Path(temporary_home) / "release"
            release_dir.mkdir()
            (release_dir / "VERSION").write_text("2.7.1\n", encoding="utf-8")
            native_exe = release_dir / "LeonDL-Native-Host-2.7.1.exe"
            gui_exe = release_dir / "LeonDL-2.7.1.exe"
            native_exe.write_bytes(b"native")
            gui_exe.write_bytes(b"gui")
            previous_executable = bridge.sys.executable
            had_frozen = hasattr(bridge.sys, "frozen")
            previous_frozen = getattr(bridge.sys, "frozen", None)
            try:
                bridge.sys.executable = str(native_exe)
                bridge.sys.frozen = True
                assert bridge._main_gui_executable() == gui_exe.resolve()
            finally:
                bridge.sys.executable = previous_executable
                if had_frozen:
                    bridge.sys.frozen = previous_frozen
                else:
                    delattr(bridge.sys, "frozen")
        finally:
            if previous_home is None:
                os.environ.pop(home_key, None)
            else:
                os.environ[home_key] = previous_home

    print("Browser bridge smoke test: OK")


if __name__ == "__main__":
    main()
