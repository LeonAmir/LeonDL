"""Self-update from GitHub releases for LeonDL.

Frozen (EXE) builds can check the latest release on GitHub, download the
Windows ZIP, verify it with the SHA-256 digest GitHub exposes on each asset,
stage the new files next to the running EXE and apply them through a small
VBScript once the application exits (a running onefile EXE is locked on
Windows). Source runs always support checking but never apply themselves;
their update path stays ``git pull``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

GITHUB_REPO = "LeonAmir/LeonDL"
RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
APP_NAME = "LeonDL"
NATIVE_HOST_PREFIX = f"{APP_NAME}-Native-Host-"
STAGING_DIR_NAME = "_update_staging"
APPLIER_VBS_NAME = "apply_update.vbs"
APPLIER_MARKER_NAME = "apply_update.marker"
APPLY_LOG_NAME = "_update_log.txt"
FALLBACK_VERSION = "2.6.3"


class UpdaterError(RuntimeError):
    """Raised for every failure inside the updater flow."""


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    published_at: str
    body: str
    asset_name: str
    asset_url: str
    asset_size: int
    asset_digest: str | None  # "sha256:..." when GitHub computed it


def version_tuple(version_text: str) -> tuple[int, int, int] | None:
    """Parse '2.6.2' / 'v2.6.2' into (2, 6, 2); None on garbage."""
    text = (version_text or "").strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = text.split(".")
    if len(parts) != 3:
        return None
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def compare_versions(left: str, right: str) -> int:
    """-1 / 0 / 1 comparing two version strings; unparsable == 0."""
    l_tuple = version_tuple(left)
    r_tuple = version_tuple(right)
    if l_tuple is None or r_tuple is None:
        return 0
    if l_tuple < r_tuple:
        return -1
    if l_tuple > r_tuple:
        return 1
    return 0


def _release_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _bundled_assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", str(_release_dir()))) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def read_current_version() -> str:
    """Current build version: VERSION file next to the app, then fallback."""
    version_file = _release_dir() / "VERSION"
    try:
        text = version_file.read_text(encoding="utf-8").strip()
        if version_tuple(text) is not None:
            return text
    except (OSError, UnicodeDecodeError):
        pass
    return FALLBACK_VERSION


def _user_agent() -> str:
    return f"{APP_NAME}/{read_current_version()} (+https://github.com/{GITHUB_REPO})"


def _download_url(url: str, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(1024).decode("utf-8", "replace")
        except Exception:
            pass
        if exc.code == 403 and "rate limit" in detail.lower():
            raise UpdaterError("GitHub rate limit hit; try again later.") from exc
        raise UpdaterError(f"GitHub returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdaterError("Network error while reaching GitHub.") from exc
    except TimeoutError as exc:
        raise UpdaterError("Timed out while reaching GitHub.") from exc
    return payload


def _choose_windows_asset(release: dict[str, Any]) -> dict[str, Any]:
    chosen: dict[str, Any] | None = None
    chosen_score = 0
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "").lower()
        if not name.endswith(".zip"):
            continue
        if "source" in name or "checksum" in name or ".sig" in name:
            continue
        score = 0
        if "window" in name:
            score += 8
        if "win64" in name or "x64" in name or "amd64" in name:
            score += 4
        if score and score > chosen_score:
            chosen_score = score
            chosen = asset
    return chosen or {}


def fetch_latest_release() -> ReleaseInfo:
    """Query the latest published (non-draft, non-prerelease) release.

    Raises UpdaterError when the release is unusable (draft/prerelease,
    no version tag, no Windows asset, no download URL).
    """
    payload = _download_url(RELEASE_URL)
    try:
        release = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdaterError("GitHub returned an unreadable response.") from exc
    if release.get("draft") or release.get("prerelease"):
        raise UpdaterError("The latest GitHub release is not published yet.")
    tag = str(release.get("tag_name") or "")
    parsed = version_tuple(tag)
    if parsed is None:
        raise UpdaterError(f"Latest release tag '{tag}' is not a valid version.")
    asset = _choose_windows_asset(release)
    if not asset:
        raise UpdaterError("No Windows ZIP asset found in the latest release.")
    asset_url = str(asset.get("browser_download_url") or "")
    if not asset_url:
        raise UpdaterError("The Windows asset has no download URL.")
    digest = str(asset.get("digest") or "")
    return ReleaseInfo(
        tag=tag,
        version=tag.lstrip("v"),
        name=str(release.get("name") or tag),
        published_at=str(release.get("published_at") or ""),
        body=str(release.get("body") or ""),
        asset_name=str(asset.get("name") or f"{APP_NAME}-{tag}-Windows.zip"),
        asset_url=asset_url,
        asset_size=int(asset.get("size") or 0),
        asset_digest=digest if digest.startswith("sha256:") else None,
    )


def download_and_verify(
    release: ReleaseInfo,
    destination: Path,
    progress: Callable[[int, int], None],
    log: Callable[[str], None],
) -> None:
    """Stream the Windows ZIP to ``destination`` and verify size + SHA-256.

    progress(received, total) is called roughly per chunk; total may be 0
    when the server does not send Content-Length.
    """
    request = urllib.request.Request(release.asset_url, headers={"User-Agent": _user_agent()})
    digest_hex = ""
    if release.asset_digest:
        digest_hex = release.asset_digest.split(":", 1)[1]
    hasher = hashlib.sha256() if digest_hex else None
    received = 0
    total = release.asset_size
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared and not total:
                total = declared
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if hasher is not None:
                    hasher.update(chunk)
                if total:
                    progress(received, total)
                else:
                    log(f"Downloaded {received} bytes")
    except urllib.error.HTTPError as exc:
        raise UpdaterError(f"Download failed with HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise UpdaterError("Download failed: network error.") from exc
    except TimeoutError as exc:
        raise UpdaterError("Download timed out.") from exc
    except OSError as exc:
        raise UpdaterError(f"Could not write the downloaded file: {exc}") from exc
    if total and received != total:
        raise UpdaterError(f"Download incomplete ({received} of {total} bytes).")
    if hasher is not None and hasher.hexdigest().lower() != digest_hex.lower():
        raise UpdaterError("SHA-256 check failed; the downloaded file is corrupted.")
    if hasher is None:
        log("No SHA-256 digest from GitHub; size check only.")


def _applier_source() -> Path:
    return _bundled_assets_dir() / APPLIER_VBS_NAME


def prepare_staged_update(
    release: ReleaseInfo,
    release_dir: Path,
    log: Callable[[str], None],
    progress: Callable[[int, int], None],
) -> Path:
    """Download, verify, extract and stage the next build beside the EXE.

    Returns the staging directory; the caller keeps it and launches the
    applier only after the user confirms (see ``launch_applier``).
    """
    staging = release_dir / STAGING_DIR_NAME
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="leon-download-") as temp_dir:
            zip_path = Path(temp_dir) / release.asset_name
            log(f"Downloading {release.asset_name}")
            download_and_verify(release, zip_path, progress, log)
            log("Extracting release archive…")
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(staging)
    except UpdaterError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    vbs = _applier_source()
    if vbs.is_file():
        shutil.copy2(vbs, staging / APPLIER_VBS_NAME)
    else:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdaterError(f"The update applier ({APPLIER_VBS_NAME}) is missing from the build.")
    main_old = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else release_dir / f"{APP_NAME}-{FALLBACK_VERSION}.exe"
    _write_applier_marker(
        staging,
        release_dir=release_dir,
        staging_dir=staging,
        main_old=main_old.name,
        main_new=main_old.with_name(f"{APP_NAME}-{release.version}.exe").name,
        native_old=f"{NATIVE_HOST_PREFIX}{main_old.name.removeprefix(APP_NAME + '-')}",
        native_new=f"{NATIVE_HOST_PREFIX}{release.version}.exe",
    )
    log("Update staged and ready to apply.")
    return staging


def _write_applier_marker(
    staging: Path,
    *,
    release_dir: Path,
    staging_dir: Path,
    main_old: str,
    main_new: str,
    native_old: str,
    native_new: str,
) -> None:
    marker: list[str] = []
    for key, value in (
        ("RELEASE_DIR", str(release_dir)),
        ("STAGING_DIR", str(staging_dir)),
        ("MAIN_OLD", main_old),
        ("MAIN_NEW", main_new),
        ("NATIVE_OLD", native_old),
        ("NATIVE_NEW", native_new),
    ):
        marker.append(f"{key}={value.encode('utf-8').hex()}")
    (staging / APPLIER_MARKER_NAME).write_text("\n".join(marker) + "\n", encoding="ascii")


def launch_applier(staging: Path) -> None:
    """Run the apply VBScript detached; it waits for the app to exit."""
    vbs = staging / APPLIER_VBS_NAME
    if not vbs.is_file():
        raise UpdaterError("The staged applier script is missing.")
    wscript = shutil.which("wscript.exe") or str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "wscript.exe")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([wscript, str(vbs)], creationflags=flags, close_fds=True)


def discard_staged_update(staging: Path) -> None:
    """Remove staged files after the user declines to apply."""
    shutil.rmtree(staging, ignore_errors=True)


class UpdateCheckWorker(QThread):
    """Queries GitHub for the latest published release (fast, no download)."""

    checked = Signal(bool, object, str)  # ok, ReleaseInfo | None, error message

    def run(self) -> None:
        try:
            release = fetch_latest_release()
        except UpdaterError as exc:
            self.checked.emit(False, None, str(exc))
            return
        except Exception as exc:  # defensive: never crash a worker thread
            self.checked.emit(False, None, f"{exc.__class__.__name__}: {exc}")
            return
        self.checked.emit(True, release, "")


class UpdateDownloadWorker(QThread):
    """Downloads, verifies and stages the next build (frozen builds only)."""

    progress = Signal(int, int)  # received, total
    staged = Signal(bool, str, object)  # ok, message, staging Path | None

    def __init__(self, release: ReleaseInfo) -> None:
        super().__init__()
        self.release = release

    def run(self) -> None:
        release_dir = _release_dir()
        try:
            staging = prepare_staged_update(
                self.release,
                release_dir,
                log=lambda text: None,
                progress=lambda received, total: self.progress.emit(received, total),
            )
        except UpdaterError as exc:
            self.staged.emit(False, str(exc), None)
            return
        except Exception as exc:  # defensive: never crash a worker thread
            self.staged.emit(False, f"{exc.__class__.__name__}: {exc}", None)
            return
        self.staged.emit(True, f"Update {self.release.version} is ready.", staging)