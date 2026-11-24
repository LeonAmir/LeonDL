from __future__ import annotations

"""Dependency checker/installer for LeonDL.

This module deliberately uses only Python's standard library so it can run in a
fresh virtual environment before pywebview and yt-dlp are installed.
"""

import argparse
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

APP_DIR = Path(__file__).resolve().parent
REQUIREMENTS_FILE = APP_DIR / "requirements.txt"
SETUP_LOG = APP_DIR / "leon_setup.log"
MIN_PYTHON = (3, 10)
MIN_DENO = (2, 3, 0)

# distribution-name: import-name (None means distribution metadata is enough)
PYTHON_REQUIREMENTS: dict[str, str | None] = {
    "pywebview": "webview",
    "yt-dlp": "yt_dlp",
    "yt-dlp-ejs": None,
    "curl-cffi": "curl_cffi",
    "packaging": "packaging",
}

MIN_DISTRIBUTION_VERSIONS: dict[str, tuple[int, ...]] = {
    "pywebview": (6, 0),
    "yt-dlp": (2026, 6, 9),
    "curl-cffi": (0, 13),
    "packaging": (24,),
}


@dataclass
class SetupReport:
    python_ok: bool = True
    python_packages_ok: bool = True
    external_tools_ok: bool = True
    installed: list[str] = field(default_factory=list)
    available: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.python_ok and self.python_packages_ok and self.external_tools_ok

    def to_json(self) -> str:
        return json.dumps(asdict(self) | {"ok": self.ok}, ensure_ascii=False)


def _append_log(message: str) -> None:
    try:
        with SETUP_LOG.open("a", encoding="utf-8") as stream:
            stream.write(message.rstrip() + "\n")
    except OSError:
        pass


def _print(message: str, verbose: bool = True) -> None:
    _append_log(message)
    if verbose:
        print(message, flush=True)


def _run(
    command: Sequence[str],
    *,
    verbose: bool,
    timeout: int = 1800,
    capture: bool = False,
) -> tuple[bool, str]:
    display = "$ " + subprocess.list2cmdline(list(command))
    _print(display, verbose)
    try:
        result = subprocess.run(
            list(command),
            cwd=str(APP_DIR),
            check=False,
            timeout=timeout,
            text=True,
            errors="replace",
            capture_output=capture,
        )
    except subprocess.TimeoutExpired as exc:
        message = f"Command timed out after {timeout} seconds: {display}"
        _print(message, verbose)
        return False, message
    except (OSError, subprocess.SubprocessError) as exc:
        message = f"Command failed: {exc}"
        _print(message, verbose)
        return False, message

    output = ""
    if capture:
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        if output:
            _append_log(output)
    _append_log(f"Exit code: {result.returncode}")
    return result.returncode == 0, output


def _distribution_available(distribution_name: str) -> bool:
    try:
        importlib.metadata.version(distribution_name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False
    except Exception:
        return False


def _numeric_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:4])


def _distribution_version_ok(distribution_name: str) -> bool:
    minimum = MIN_DISTRIBUTION_VERSIONS.get(distribution_name)
    if minimum is None:
        return True
    try:
        installed = importlib.metadata.version(distribution_name)
    except Exception:
        return False
    current = _numeric_version(installed)
    return current >= minimum


def _module_available(module_name: str | None) -> bool:
    if not module_name:
        return True
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _requirement_available(distribution_name: str, module_name: str | None) -> bool:
    return (
        _distribution_available(distribution_name)
        and _module_available(module_name)
        and _distribution_version_ok(distribution_name)
    )


def _ensure_pip(verbose: bool) -> bool:
    ok, _ = _run([sys.executable, "-m", "pip", "--version"], verbose=False, timeout=30, capture=True)
    if ok:
        return True
    _print("pip is missing; trying ensurepip...", verbose)
    ok, _ = _run([sys.executable, "-m", "ensurepip", "--upgrade"], verbose=verbose, timeout=300)
    return ok


def ensure_python_packages(report: SetupReport, *, install: bool, verbose: bool) -> None:
    report.details["python"] = sys.version.replace("\n", " ")
    report.details["python_executable"] = sys.executable

    if sys.version_info < MIN_PYTHON:
        report.python_ok = False
        report.python_packages_ok = False
        report.missing.append(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+")
        report.warnings.append("Python 3.10 or newer is required.")
        return

    if getattr(sys, "frozen", False):
        for label, module in PYTHON_REQUIREMENTS.items():
            if _module_available(module):
                report.available.append(label)
            else:
                report.missing.append(label)
                report.python_packages_ok = False
        return

    missing = [
        distribution
        for distribution, module in PYTHON_REQUIREMENTS.items()
        if not _requirement_available(distribution, module)
    ]
    for distribution in missing:
        if _distribution_available(distribution) and not _distribution_version_ok(distribution):
            current = importlib.metadata.version(distribution)
            minimum = ".".join(map(str, MIN_DISTRIBUTION_VERSIONS.get(distribution, ())))
            report.warnings.append(f"{distribution} {current} is too old; {minimum}+ is required.")

    if missing and install:
        _print("Installing/updating Python requirements...", verbose)
        if not _ensure_pip(verbose):
            report.python_packages_ok = False
            report.missing.extend(missing)
            report.warnings.append("pip could not be installed or started.")
            return
        ok, _ = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--disable-pip-version-check",
                "--prefer-binary",
                "--progress-bar",
                "off",
                "--timeout",
                "45",
                "--retries",
                "2",
                "-r",
                str(REQUIREMENTS_FILE),
            ],
            verbose=verbose,
            timeout=900,
        )
        if ok:
            importlib.invalidate_caches()
            report.installed.extend(missing)
        else:
            report.warnings.append(f"Python package installation failed. See {SETUP_LOG.name}.")

    for distribution, module in PYTHON_REQUIREMENTS.items():
        if _requirement_available(distribution, module):
            try:
                version = importlib.metadata.version(distribution)
            except Exception:
                version = "unknown"
            report.details[distribution] = version
            if distribution not in report.installed:
                report.available.append(f"{distribution} {version}")
        else:
            report.python_packages_ok = False
            if distribution not in report.missing:
                report.missing.append(distribution)

    if report.python_packages_ok and _ensure_pip(False):
        ok, output = _run(
            [sys.executable, "-m", "pip", "check"],
            verbose=verbose,
            timeout=180,
            capture=True,
        )
        if not ok:
            report.python_packages_ok = False
            report.warnings.append("pip check reported an inconsistent Python environment.")
            if output:
                report.details["pip_check"] = output


def _prepend_path(path: Path) -> None:
    if not path.is_dir():
        return
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    resolved = str(path.resolve())
    if all(entry.casefold() != resolved.casefold() for entry in entries):
        os.environ["PATH"] = resolved + os.pathsep + current


def _refresh_tool_paths() -> None:
    # Portable/local tool locations are checked before the system PATH.
    _prepend_path(APP_DIR / "tools")
    _prepend_path(APP_DIR / "tools" / "ffmpeg" / "bin")
    _prepend_path(APP_DIR / "tools" / "deno")
    _prepend_path(Path.home() / ".deno" / "bin")

    if os.name != "nt":
        _prepend_path(Path.home() / ".local" / "bin")
        return

    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    _prepend_path(local / "Microsoft" / "WinGet" / "Links")
    package_root = local / "Microsoft" / "WinGet" / "Packages"
    if package_root.is_dir():
        for filename in ("deno.exe", "ffmpeg.exe", "ffprobe.exe"):
            try:
                executable = next(package_root.rglob(filename), None)
            except OSError:
                executable = None
            if executable:
                _prepend_path(executable.parent)


def _which(name: str) -> str | None:
    _refresh_tool_paths()
    return shutil.which(name)


def _version_tuple(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        return ()
    return tuple(int(part) for part in match.groups())


def _executable_status(name: str, version_args: Sequence[str]) -> tuple[bool, str]:
    path = _which(name)
    if not path:
        return False, "not found"
    ok, output = _run([path, *version_args], verbose=False, timeout=30, capture=True)
    first_line = next((line.strip() for line in output.splitlines() if line.strip()), "")
    detail = f"{path}" + (f" ({first_line})" if first_line else "")
    return ok, detail


def _deno_is_supported() -> tuple[bool, str]:
    ok, detail = _executable_status("deno", ["--version"])
    if not ok:
        return False, detail
    version = _version_tuple(detail)
    return bool(version and version >= MIN_DENO), detail


def _ffmpeg_status() -> tuple[bool, str, str]:
    ffmpeg_ok, ffmpeg_detail = _executable_status("ffmpeg", ["-version"])
    ffprobe_ok, ffprobe_detail = _executable_status("ffprobe", ["-version"])
    return ffmpeg_ok and ffprobe_ok, ffmpeg_detail, ffprobe_detail


def _install_windows(package_id: str, *, verbose: bool) -> bool:
    winget = _which("winget")
    if not winget:
        _print("WinGet was not found.", verbose)
        return False

    base = [
        winget,
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]
    ok, _ = _run(
        [winget, "install", "--id", package_id, "-e", "--source", "winget", *base[1:]],
        verbose=verbose,
        timeout=3600,
    )
    if not ok:
        ok, _ = _run(
            [winget, "upgrade", "--id", package_id, "-e", "--source", "winget", *base[1:]],
            verbose=verbose,
            timeout=3600,
        )
    _refresh_tool_paths()
    return ok


def _install_macos(package: str, *, verbose: bool) -> bool:
    brew = _which("brew")
    if not brew:
        return False
    ok, _ = _run([brew, "install", package], verbose=verbose, timeout=3600)
    return ok


def _sudo_prefix() -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    return ["sudo"] if _which("sudo") else []


def _install_linux_ffmpeg(*, verbose: bool) -> bool:
    sudo = _sudo_prefix()
    if _which("apt-get"):
        ok, _ = _run([*sudo, "apt-get", "update"], verbose=verbose, timeout=3600)
        if not ok:
            return False
        ok, _ = _run([*sudo, "apt-get", "install", "-y", "ffmpeg"], verbose=verbose, timeout=3600)
        return ok
    if _which("dnf"):
        ok, _ = _run([*sudo, "dnf", "install", "-y", "ffmpeg"], verbose=verbose, timeout=3600)
        return ok
    if _which("pacman"):
        ok, _ = _run([*sudo, "pacman", "-S", "--noconfirm", "ffmpeg"], verbose=verbose, timeout=3600)
        return ok
    if _which("zypper"):
        ok, _ = _run([*sudo, "zypper", "--non-interactive", "install", "ffmpeg"], verbose=verbose, timeout=3600)
        return ok
    return False


def _install_linux_deno(*, verbose: bool) -> bool:
    curl = _which("curl")
    shell = _which("sh")
    if not curl or not shell:
        return False
    command = f'"{curl}" -fsSL https://deno.land/install.sh | "{shell}"'
    _print("$ " + command, verbose)
    try:
        result = subprocess.run(command, shell=True, cwd=str(APP_DIR), timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    _refresh_tool_paths()
    return result.returncode == 0


def _install_or_upgrade_deno(*, verbose: bool) -> bool:
    existing = _which("deno")
    if existing:
        ok, _ = _run([existing, "upgrade"], verbose=verbose, timeout=1800)
        if ok:
            _refresh_tool_paths()
            return True

    system = platform.system()
    if system == "Windows":
        installed = _install_windows("DenoLand.Deno", verbose=verbose)
    elif system == "Darwin":
        installed = _install_macos("deno", verbose=verbose)
    else:
        installed = _install_linux_deno(verbose=verbose)
    _refresh_tool_paths()
    return installed


def _install_ffmpeg(*, verbose: bool) -> bool:
    system = platform.system()
    if system == "Windows":
        installed = _install_windows("Gyan.FFmpeg", verbose=verbose)
    elif system == "Darwin":
        installed = _install_macos("ffmpeg", verbose=verbose)
    else:
        installed = _install_linux_ffmpeg(verbose=verbose)
    _refresh_tool_paths()
    return installed


def ensure_external_tools(report: SetupReport, *, install: bool, verbose: bool) -> None:
    _refresh_tool_paths()

    # Do not merely check PATH: both executables must start successfully.
    ffmpeg_ok, ffmpeg_detail, ffprobe_detail = _ffmpeg_status()
    if not ffmpeg_ok and install:
        _print("FFmpeg/FFprobe are missing or unusable; attempting installation...", verbose)
        if _install_ffmpeg(verbose=verbose):
            report.installed.append("FFmpeg + FFprobe")
        ffmpeg_ok, ffmpeg_detail, ffprobe_detail = _ffmpeg_status()

    report.details["ffmpeg"] = ffmpeg_detail
    report.details["ffprobe"] = ffprobe_detail
    if ffmpeg_ok:
        if "FFmpeg + FFprobe" not in report.installed:
            report.available.append("FFmpeg + FFprobe")
    else:
        report.external_tools_ok = False
        report.missing.append("FFmpeg + FFprobe")
        report.warnings.append(
            "FFmpeg and FFprobe must both be installed and executable; merging video/audio and conversion will fail without them."
        )

    deno_ok, deno_detail = _deno_is_supported()
    if not deno_ok and install:
        _print(f"Deno {'.'.join(map(str, MIN_DENO))}+ is missing or old; attempting installation/update...", verbose)
        if _install_or_upgrade_deno(verbose=verbose):
            report.installed.append("Deno")
        deno_ok, deno_detail = _deno_is_supported()

    report.details["deno"] = deno_detail
    if deno_ok:
        if "Deno" not in report.installed:
            report.available.append("Deno")
    else:
        report.external_tools_ok = False
        report.missing.append(f"Deno {'.'.join(map(str, MIN_DENO))}+")
        report.warnings.append("A supported JavaScript runtime is required for complete YouTube format extraction.")


def ensure_environment(*, install: bool = True, include_external: bool = True, verbose: bool = True) -> SetupReport:
    report = SetupReport()
    ensure_python_packages(report, install=install, verbose=verbose)
    if include_external:
        ensure_external_tools(report, install=install, verbose=verbose)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check and install LeonDL requirements")
    parser.add_argument("--check", action="store_true", help="Only check; do not install missing items")
    parser.add_argument("--skip-external", action="store_true", help="Skip FFmpeg and Deno checks")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    parser.add_argument("--strict", action="store_true", help="Return failure when FFmpeg/FFprobe or Deno remain missing")
    args = parser.parse_args()

    if not args.check:
        try:
            SETUP_LOG.write_text(
                f"LeonDL setup log — {datetime.now().isoformat(timespec='seconds')}\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    report = ensure_environment(
        install=not args.check,
        include_external=not args.skip_external,
        verbose=not args.quiet and not args.json,
    )

    if args.json:
        print(report.to_json())
    elif not args.quiet:
        print("\n=== LeonDL requirements ===")
        print("Available:", ", ".join(report.available) or "—")
        print("Installed now:", ", ".join(report.installed) or "—")
        print("Still missing:", ", ".join(report.missing) or "—")
        for key, value in report.details.items():
            print(f"{key}: {value}")
        for warning in report.warnings:
            print("Warning:", warning)
        print(f"Log: {SETUP_LOG}")

    if not report.python_ok or not report.python_packages_ok:
        return 2
    if args.strict and not report.external_tools_ok:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
