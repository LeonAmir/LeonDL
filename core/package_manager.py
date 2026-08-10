from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from core.optional_engines import APKEEP_PATH, TOOLS_DIR


APP_DIR = Path(__file__).resolve().parents[1]
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass(frozen=True)
class PackageStatus:
    key: str
    name: str
    installed: bool
    version: str
    path: str
    detail: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "installed": self.installed,
            "version": self.version,
            "path": self.path,
            "detail": self.detail,
            "source": self.source,
        }


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except (importlib.metadata.PackageNotFoundError, ValueError, OSError):
        return ""


def _distribution_path(name: str) -> str:
    try:
        return str(Path(importlib.metadata.distribution(name).locate_file("")).resolve())
    except (importlib.metadata.PackageNotFoundError, ValueError, OSError):
        return ""


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _first_line(command: list[str], timeout: int = 8) -> str:
    if not command or not command[0]:
        return ""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0].strip() if output else ""


def _candidate_tool_directories() -> list[Path]:
    directories = [
        TOOLS_DIR,
        APP_DIR / "tools",
        APP_DIR / "tools" / "ffmpeg" / "bin",
        APP_DIR / "tools" / "deno",
        Path(sys.executable).resolve().parent,
        Path(sys.executable).resolve().parent / "Scripts",
        Path.home() / ".local" / "bin",
        Path.home() / ".deno" / "bin",
    ]
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        directories.extend(
            [
                local / "Microsoft" / "WinGet" / "Links",
                Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "ffmpeg" / "bin",
            ]
        )
    result: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        try:
            key = str(directory.resolve()).casefold()
        except OSError:
            key = str(directory).casefold()
        if key not in seen:
            seen.add(key)
            result.append(directory)
    return result


def _prepend_tool_paths() -> None:
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    known = {entry.casefold() for entry in entries}
    additions: list[str] = []
    for directory in _candidate_tool_directories():
        if not directory.is_dir():
            continue
        value = str(directory)
        if value.casefold() not in known:
            known.add(value.casefold())
            additions.append(value)
    if additions:
        os.environ["PATH"] = os.pathsep.join([*additions, current] if current else additions)


def _find_winget_executable(names: tuple[str, ...]) -> str:
    if os.name != "nt":
        return ""
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    package_root = local / "Microsoft" / "WinGet" / "Packages"
    if not package_root.is_dir():
        return ""
    for name in names:
        try:
            match = next(package_root.rglob(name), None)
        except OSError:
            match = None
        if match and match.is_file():
            return str(match)
    return ""


def _find_executable(*names: str) -> str:
    clean = tuple(name for name in names if name)
    if not clean:
        return ""
    _prepend_tool_paths()
    for name in clean:
        found = shutil.which(name)
        if found:
            return found
    for directory in _candidate_tool_directories():
        for name in clean:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return _find_winget_executable(clean)


def _python_status(
    key: str,
    display_name: str,
    distribution: str,
    module: str,
    detail: str,
    executable_names: tuple[str, ...] = (),
    *,
    executable_counts: bool = False,
) -> PackageStatus:
    version = _distribution_version(distribution)
    package_path = _distribution_path(distribution)
    module_found = _module_available(module)
    executable = _find_executable(*executable_names) if executable_names else ""
    current_environment = bool(version or module_found)
    installed = current_environment or bool(executable and executable_counts)
    path = (executable if executable and executable_counts else package_path) or (sys.executable if current_environment else "")
    sources: list[str] = []
    if current_environment:
        sources.append("current Python environment")
    if executable and executable_counts:
        sources.append("system/local executable")
    source = " + ".join(sources)
    facts = [detail]
    if source:
        facts.append("Detected in " + source)
    return PackageStatus(key, display_name, installed, version or _first_line([executable, "--version"]), path, "; ".join(facts), source)


def collect_package_status() -> list[dict[str, Any]]:
    """Perform a full, read-only inventory before exposing install/update actions."""
    _prepend_tool_paths()

    gallery = _python_status(
        "gallery_dl",
        "gallery-dl",
        "gallery-dl",
        "gallery_dl",
        "Optional Reddit/Instagram image and gallery engine",
        ("gallery-dl.exe", "gallery-dl"),
        executable_counts=True,
    )
    spotdl = _python_status(
        "spotdl",
        "spotDL",
        "spotdl",
        "spotdl",
        "Optional Spotify metadata-to-audio engine",
        ("spotdl.exe", "spotdl"),
        executable_counts=True,
    )

    apkeep = _find_executable("apkeep.exe", "apkeep")
    if not apkeep and APKEEP_PATH.is_file():
        apkeep = str(APKEEP_PATH)

    ffmpeg = _find_executable("ffmpeg.exe", "ffmpeg")
    ffprobe = _find_executable("ffprobe.exe", "ffprobe")
    ffmpeg_installed = bool(ffmpeg and ffprobe)
    ffmpeg_detail = f"ffmpeg: {ffmpeg or 'not found'}; ffprobe: {ffprobe or 'not found'}"

    deno = _find_executable("deno.exe", "deno")

    statuses = [
        _python_status("yt_dlp", "yt-dlp", "yt-dlp", "yt_dlp", "Primary media engine"),
        _python_status("yt_dlp_ejs", "yt-dlp-ejs", "yt-dlp-ejs", "yt_dlp_ejs", "JavaScript challenge components"),
        _python_status("curl_cffi", "curl-cffi", "curl-cffi", "curl_cffi", "Browser impersonation"),
        gallery,
        spotdl,
        PackageStatus(
            "apkeep",
            "apkeep",
            bool(apkeep),
            _first_line([apkeep, "--version"]) if apkeep else "",
            apkeep,
            "Optional APKPure/F-Droid/Google Play/AppGallery engine" + ("; detected executable" if apkeep else ""),
            "system/local executable" if apkeep else "",
        ),
        PackageStatus(
            "ffmpeg",
            "FFmpeg",
            ffmpeg_installed,
            _first_line([ffmpeg, "-version"]) if ffmpeg else "",
            ffmpeg or ffprobe,
            ffmpeg_detail,
            "system/local executable" if ffmpeg or ffprobe else "",
        ),
        PackageStatus(
            "deno",
            "Deno",
            bool(deno),
            _first_line([deno, "--version"]) if deno else "",
            deno,
            "JavaScript runtime" + ("; detected executable" if deno else ""),
            "system/local executable" if deno else "",
        ),
        _python_status("pyinstaller", "PyInstaller", "PyInstaller", "PyInstaller", "EXE builder"),
    ]
    return [status.as_dict() for status in statuses]


class PackageStatusWorker(QThread):
    ready = Signal(list)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.ready.emit(collect_package_status())
        except Exception as exc:
            self.failed.emit(str(exc) or exc.__class__.__name__)


def _download_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "LeonDL/2.6.2"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_file(url: str, destination: Path, log: Callable[[str], None]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "LeonDL/2.6.2"})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as handle:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)
            received += len(chunk)
            if total:
                log(f"Downloaded {received * 100 // total}%")


def _choose_asset(assets: list[dict[str, Any]], keywords: tuple[str, ...]) -> dict[str, Any] | None:
    scored: list[tuple[int, dict[str, Any]]] = []
    for asset in assets:
        name = str(asset.get("name") or "").lower()
        if not name or any(token in name for token in ("sha256", "checksum", ".sig", "source")):
            continue
        score = sum(5 for keyword in keywords if keyword in name)
        if name.endswith(".exe"):
            score += 5
        elif name.endswith(".zip"):
            score += 3
        if "win" in name or "windows" in name:
            score += 6
        if "x64" in name or "x86_64" in name or "amd64" in name:
            score += 4
        if score > 0:
            scored.append((score, asset))
    return max(scored, key=lambda item: item[0])[1] if scored else None


def _install_github_executable(
    repo: str,
    final_name: str,
    keywords: tuple[str, ...],
    log: Callable[[str], None],
) -> None:
    release = _download_json(f"https://api.github.com/repos/{repo}/releases/latest")
    asset = _choose_asset(list(release.get("assets") or []), keywords)
    if not asset:
        raise RuntimeError(f"No compatible Windows asset was found in the latest {repo} release.")
    url = str(asset.get("browser_download_url") or "")
    name = str(asset.get("name") or "download.bin")
    if not url:
        raise RuntimeError("The selected release asset has no download URL.")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="leon-engine-") as temp_dir:
        downloaded = Path(temp_dir) / name
        log(f"Downloading {name}")
        _download_file(url, downloaded, log)
        target = TOOLS_DIR / final_name
        if downloaded.suffix.lower() == ".exe":
            shutil.copy2(downloaded, target)
        elif downloaded.suffix.lower() == ".zip":
            with zipfile.ZipFile(downloaded) as archive:
                candidates = [member for member in archive.namelist() if member.lower().endswith(".exe")]
                if not candidates:
                    raise RuntimeError("The release archive did not contain a Windows executable.")
                preferred = max(candidates, key=lambda value: sum(k in value.lower() for k in keywords))
                with archive.open(preferred) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        else:
            raise RuntimeError(f"Unsupported release asset format: {downloaded.suffix}")
    log(f"Installed to {target}")


class PackageActionWorker(QThread):
    log = Signal(str)
    finished_action = Signal(bool, str)

    PIP_ACTIONS: dict[str, tuple[bool, list[str]]] = {
        "install_yt_dlp": (False, ["yt-dlp[default,curl-cffi]"]),
        "update_yt_dlp": (True, ["yt-dlp[default,curl-cffi]"]),
        "install_yt_dlp_ejs": (False, ["yt-dlp-ejs"]),
        "update_yt_dlp_ejs": (True, ["yt-dlp-ejs"]),
        "install_curl_cffi": (False, ["curl-cffi"]),
        "update_curl_cffi": (True, ["curl-cffi"]),
        "install_gallery_dl": (False, ["gallery-dl"]),
        "update_gallery_dl": (True, ["gallery-dl"]),
        "install_spotdl": (False, ["spotdl"]),
        "update_spotdl": (True, ["--upgrade-strategy", "eager", "spotdl"]),
        "install_pyinstaller": (False, ["pyinstaller"]),
        "update_pyinstaller": (True, ["pyinstaller"]),
    }

    WINGET_IDS = {
        "ffmpeg": "Gyan.FFmpeg",
        "deno": "DenoLand.Deno",
        "gallery_dl": "mikf.gallery-dl",
    }

    def __init__(self, action: str) -> None:
        super().__init__()
        self.action = action

    def _pip_command(self) -> list[str]:
        spec = self.PIP_ACTIONS.get(self.action)
        if not spec or getattr(sys, "frozen", False):
            return []
        update, arguments = spec
        command = [sys.executable, "-m", "pip", "install"]
        if update:
            command.append("--upgrade")
        command.extend(arguments)
        return command

    def _winget_command(self) -> list[str]:
        if os.name != "nt" or not shutil.which("winget"):
            return []
        if not (self.action.startswith("install_") or self.action.startswith("update_")):
            return []
        mode, _, key = self.action.partition("_")
        package_id = self.WINGET_IDS.get(key)
        if not package_id:
            return []
        common = ["--accept-package-agreements", "--accept-source-agreements", "--silent"]
        if mode == "update":
            return ["winget", "upgrade", "--id", package_id, "--exact", "--include-unknown", *common]
        return ["winget", "install", "--id", package_id, "--exact", *common]

    def _binary_action(self) -> bool:
        binary_specs = {
            "install_spotdl_binary": ("spotDL/spotify-downloader", "spotdl.exe", ("spotdl", "win", "x64"), "installed"),
            "update_spotdl_binary": ("spotDL/spotify-downloader", "spotdl.exe", ("spotdl", "win", "x64"), "updated"),
            "install_apkeep": ("EFForg/apkeep", APKEEP_PATH.name, ("apkeep", "windows", "x86_64"), "installed"),
            "update_apkeep": ("EFForg/apkeep", APKEEP_PATH.name, ("apkeep", "windows", "x86_64"), "updated"),
        }
        spec = binary_specs.get(self.action)
        if not spec:
            return False
        repo, final_name, keywords, verb = spec
        try:
            _install_github_executable(repo, final_name, keywords, self.log.emit)
        except Exception as exc:
            self.finished_action.emit(False, str(exc) or exc.__class__.__name__)
            return True
        self.finished_action.emit(True, f"Optional engine {verb} successfully.")
        return True

    def _commands(self) -> list[list[str]]:
        pip_command = self._pip_command()
        if pip_command:
            return [pip_command]
        winget_command = self._winget_command()
        if winget_command:
            return [winget_command]
        return []

    def run(self) -> None:
        # Frozen builds cannot mutate bundled Python packages. For their
        # executable-only optional engines, use the official binary path.
        if self.action in {"install_apkeep", "update_apkeep"}:
            if os.name != "nt":
                self.finished_action.emit(False, "Automatic apkeep installation is available only on Windows.")
                return
            if self._binary_action():
                return
        if self.action in {"install_spotdl", "update_spotdl"} and getattr(sys, "frozen", False):
            self.action = self.action + "_binary"
            if self._binary_action():
                return

        commands = self._commands()
        if not commands:
            if getattr(sys, "frozen", False) and self.action in self.PIP_ACTIONS:
                self.finished_action.emit(False, "Bundled Python packages are updated by installing a newer LeonDL build.")
            else:
                self.finished_action.emit(False, "The required package manager is unavailable for this action.")
            return

        command = commands[0]
        self.log.emit("$ " + subprocess.list2cmdline(command))
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            assert process.stdout is not None
            for line in process.stdout:
                text = line.rstrip()
                if text:
                    self.log.emit(text)
            final_code = process.wait()
        except (OSError, subprocess.SubprocessError) as exc:
            self.finished_action.emit(False, str(exc) or exc.__class__.__name__)
            return

        if final_code == 0:
            verb = "updated" if self.action.startswith("update_") else "installed"
            self.finished_action.emit(True, f"Package {verb} successfully.")
        else:
            self.finished_action.emit(False, f"Command finished with exit code {final_code}.")


# ---------------------------------------------------------------------------
# Automatic prerequisite check/install for frozen (EXE) builds.
# Frozen builds bundle their Python packages, but FFmpeg/FFprobe and Deno
# remain external runtime tools. On startup the EXE checks for them and, when
# missing, installs them through WinGet in the background. The Packages page
# stays authoritative; this path only covers the minimal external tools the
# app needs to merge audio/video and run JavaScript-dependent extractors.
# ---------------------------------------------------------------------------

FROZEN_REQUIRED_TOOLS: tuple[str, ...] = ("ffmpeg", "deno")


def missing_required_tools() -> list[str]:
    """Return keys of frozen-build external prerequisites missing on this machine."""
    missing: list[str] = []
    ffmpeg = _find_executable("ffmpeg.exe", "ffmpeg")
    ffprobe = _find_executable("ffprobe.exe", "ffprobe")
    if not (ffmpeg and ffprobe):
        missing.append("ffmpeg")
    if not _find_executable("deno.exe", "deno"):
        missing.append("deno")
    return missing


def winget_install_command(key: str, *, check_available: bool = True) -> list[str]:
    """Build the WinGet install command for a required tool key (pure/testable)."""
    if os.name != "nt":
        return []
    if check_available and not shutil.which("winget"):
        return []
    package_id = PackageActionWorker.WINGET_IDS.get(key)
    if not package_id:
        return []
    return [
        "winget",
        "install",
        "--id",
        package_id,
        "--exact",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent",
    ]


def run_winget_install(key: str, log: Callable[[str], None]) -> bool:
    """Install one required tool via WinGet, streaming output to ``log``."""
    command = winget_install_command(key)
    if not command:
        log(f"No WinGet install path available for {key}.")
        return False
    log("$ " + subprocess.list2cmdline(command))
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=CREATE_NO_WINDOW,
        )
        assert process.stdout is not None
        for line in process.stdout:
            text = line.rstrip()
            if text:
                log(text)
        return process.wait() == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log(str(exc) or exc.__class__.__name__)
        return False


class PrerequisiteWorker(QThread):
    """Background worker: check and install frozen-build external prerequisites."""

    log = Signal(str)
    done = Signal(list, list)  # installed_keys, failed_keys

    def __init__(self, *, skip_check: bool = False) -> None:
        super().__init__()
        self._skip_check = skip_check

    def run(self) -> None:
        missing = [] if self._skip_check else missing_required_tools()
        if not missing:
            self.done.emit([], [])
            return
        installed: list[str] = []
        failed: list[str] = []
        for key in missing:
            self.log.emit(f"Installing prerequisite: {key} ...")
            if run_winget_install(key, self.log.emit):
                installed.append(key)
            else:
                failed.append(key)
        self.done.emit(installed, failed)
