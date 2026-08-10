"""Offline smoke test for core/updater.py.

Validates version parsing/compare, asset selection, JSON parsing, real
streaming download + SHA-256 verification against a local HTTP server,
staging preparation and the applier marker contract.
"""

from __future__ import annotations

import hashlib
import http.server
import shutil
import socketserver
import tempfile
import threading
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.updater import (  # noqa: E402
    APPLIER_MARKER_NAME,
    APPLIER_VBS_NAME,
    ReleaseInfo,
    UpdaterError,
    _choose_windows_asset,
    _write_applier_marker,
    compare_versions,
    download_and_verify,
    fetch_latest_release,
    prepare_staged_update,
    version_tuple,
)

FAILED = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        FAILED.append(name)


# 1. Version helpers -------------------------------------------------------
check("version_tuple basic", version_tuple("2.6.2") == (2, 6, 2))
check("version_tuple with v", version_tuple("v2.6.2") == (2, 6, 2))
check("version_tuple garbage", version_tuple("abc") is None)
check("compare newer", compare_versions("2.6.3", "2.6.2") == 1)
check("compare older", compare_versions("2.6.1", "2.6.2") == -1)
check("compare equal", compare_versions("2.6.2", "v2.6.2") == 0)

# 2. Asset selection -------------------------------------------------------
fake_release = {
    "assets": [
        {"name": "LeonDL-v2.6.2.zip", "browser_download_url": "https://x/s.zip"},
        {"name": "LeonDL-v2.6.2-Windows.zip", "browser_download_url": "https://x/w.zip"},
        {"name": "LeonDL-v2.6.2-Windows.zip.sha256"},
        {"name": "LeonDL-v2.6.2-source.zip"},
    ]
}
asset = _choose_windows_asset(fake_release)
check("asset picks Windows zip", asset.get("name") == "LeonDL-v2.6.2-Windows.zip")
check("asset rejects empty", _choose_windows_asset({"assets": []}) == {})

# 3. Release JSON parsing (networkless) ------------------------------------
canned = {
    "tag_name": "v2.6.3",
    "name": "LeonDL v2.6.3",
    "published_at": "2026-01-01T00:00:00Z",
    "body": "release notes",
    "draft": False,
    "prerelease": False,
    "assets": [
        {"name": "LeonDL-v2.6.3-Windows.zip", "browser_download_url": "https://x/w.zip", "size": 123, "digest": "sha256:" + "a" * 64},
    ],
}
original_download = None
import core.updater as updater_mod  # noqa: E402

original_download = updater_mod._download_url
updater_mod._download_url = lambda url: (  # type: ignore[assignment]
    __import__("json").dumps(canned).encode() if "releases/latest" in url else b""
)
try:
    info = fetch_latest_release()
    check("release parse version", info.version == "2.6.3", info.version)
    check("release parse asset", info.asset_name == "LeonDL-v2.6.3-Windows.zip")
    check("release parse digest", info.asset_digest == "sha256:" + "a" * 64)
finally:
    updater_mod._download_url = original_download  # type: ignore[assignment]

# 4. Streaming download + SHA-256 verify against local server --------------
with tempfile.TemporaryDirectory(prefix="leon-smoke-") as tmp:
    root = Path(tmp)
    payload = b"LeonDL fake release content " * 1000
    zip_path = root / "fake.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("LeonDL-9.9.9.exe", payload)
        archive.writestr("README.md", "# test")

    digest = "sha256:" + hashlib.sha256(zip_path.read_bytes()).hexdigest()
    handler = lambda *args, **kw: http.server.SimpleHTTPRequestHandler(*args, directory=tmp, **kw)  # noqa: E731
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    release = ReleaseInfo(
        tag="v9.9.9", version="9.9.9", name="t", published_at="", body="",
        asset_name="fake.zip", asset_url=f"http://127.0.0.1:{port}/fake.zip",
        asset_size=zip_path.stat().st_size, asset_digest=digest,
    )

    dest = root / "downloaded.zip"
    download_and_verify(release, dest, progress=lambda r, t: None, log=lambda t: None)
    check("download matches payload", dest.read_bytes() == zip_path.read_bytes())

    # corrupt digest must fail (digest is compared after a full download)
    bad = ReleaseInfo(**{**release.__dict__, "asset_digest": "sha256:" + "b" * 64})
    raised = False
    try:
        download_and_verify(bad, root / "bad.zip", progress=lambda r, t: None, log=lambda t: None)
    except UpdaterError:
        raised = True
    check("corrupt digest rejected", raised)

    # 5. Staging preparation + marker contract ------------------------------
    release_dir = root / "release"
    release_dir.mkdir()
    staging = prepare_staged_update(release, release_dir, log=lambda t: None, progress=lambda r, t: None)
    check("staging exists", staging.is_dir(), str(staging))
    check("new exe staged", (staging / "LeonDL-9.9.9.exe").is_file())
    check("applier vbs staged", (staging / APPLIER_VBS_NAME).is_file())
    marker_text = (staging / APPLIER_MARKER_NAME).read_text(encoding="ascii")
    decoded: dict[str, str] = {}
    for line in marker_text.strip().splitlines():
        key, _, hex_value = line.partition("=")
        decoded[key] = bytes.fromhex(hex_value).decode("utf-8")
    check("marker has MAIN_OLD", "MAIN_OLD" in decoded, decoded.get("MAIN_OLD", ""))
    check("marker MAIN_NEW correct", decoded.get("MAIN_NEW") == "LeonDL-9.9.9.exe")
    check("marker RELEASE_DIR correct", decoded.get("RELEASE_DIR") == str(release_dir))
    check("marker NATIVE_NEW correct", decoded.get("NATIVE_NEW") == "LeonDL-Native-Host-9.9.9.exe")

    applier = Path(__file__).resolve().parent / "assets" / APPLIER_VBS_NAME
    check("applier source exists", applier.is_file())
    vbs_text = applier.read_text(encoding="utf-8") if applier.is_file() else ""
    for token in ("HexDecode", "apply_update.marker", "WaitForExit", "MAIN_NEW", "WScript.Quit"):
        check(f"applier contains {token}", token in vbs_text)

    shutil.rmtree(staging, ignore_errors=True)

    server.shutdown()
    server.server_close()

print()
if FAILED:
    print(f"FAILED: {len(FAILED)} check(s) -> {FAILED}")
    raise SystemExit(1)
print("ALL PASS")