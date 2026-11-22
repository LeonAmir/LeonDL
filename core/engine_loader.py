"""Updatable media-engine loader.

Frozen (EXE) builds bundle a fixed copy of ``yt_dlp`` / ``yt_dlp_ejs`` inside
the executable, so an in-app update could never replace them: the bundled
modules always won the import race, and a manual ``pip install -U yt-dlp``
landed in a different interpreter that LeonDL never saw.

This module fixes that by introducing an *engine directory* that lives next to
the executable and takes priority over the bundled copy:

- ``<exe_dir>/engines``            (frozen builds)
- ``<project_root>/engines``       (source runs)

The directory receives pure-python wheels downloaded straight from PyPI (no pip
required), and a meta-path finder makes it win over PyInstaller's frozen modules.
Because it sits beside the EXE, it survives LeonDL self-updates and now carries
the newest yt-dlp independently of the LeonDL release cadence.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# action key -> (PyPI project name, import package name)
ENGINE_PACKAGES: dict[str, tuple[str, str]] = {
    "yt_dlp": ("yt-dlp", "yt_dlp"),
    "yt_dlp_ejs": ("yt-dlp-ejs", "yt_dlp_ejs"),
}

USER_AGENT = "LeonDL-engine-loader/1.0 (+https://github.com/LeonAmir/LeonDL)"


def engines_root() -> Path:
    """Directory that holds the updatable engine copies."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "engines"
    return Path(__file__).resolve().parents[1] / "engines"


class _EngineFinder(importlib.abc.MetaPathFinder):
    """Prefer packages inside the engine directory over bundled copies."""

    def __init__(self, root: Path) -> None:
        self.root = str(root)
        self._top_levels: set[str] = set()
        try:
            for entry in Path(self.root).iterdir():
                if entry.is_dir() and (entry / "__init__.py").is_file():
                    self._top_levels.add(entry.name)
        except OSError:
            pass

    def find_spec(self, fullname, path=None, target=None):  # noqa: D102 - finder API
        if not self._top_levels:
            return None
        # Submodules resolve through the parent package's __path__ (which points
        # into the engine directory once the parent is loaded from here).
        if path is not None:
            return None
        if fullname.split(".")[0] not in self._top_levels:
            return None
        return importlib.machinery.PathFinder.find_spec(fullname, [self.root])


_ACTIVATED = False


def activate_engines() -> Path | None:
    """Put the engine directory ahead of bundled modules. Safe to call anytime."""
    global _ACTIVATED
    root = engines_root()
    try:
        if not root.is_dir():
            return None
        if _ACTIVATED:
            return root
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        # Meta-path finders run before PyInstaller's frozen importer; ours must
        # be first so the engine copy wins.
        if not any(isinstance(finder, _EngineFinder) for finder in sys.meta_path):
            sys.meta_path.insert(0, _EngineFinder(root))
        _ACTIVATED = True
        return root
    except OSError:
        return None


def engine_installed_version(key: str) -> str:
    """Version of an engine as currently importable (engine dir wins)."""
    if key not in ENGINE_PACKAGES:
        return ""
    project, _package = ENGINE_PACKAGES[key]
    try:
        return importlib.metadata.version(project)
    except Exception:
        pass
    try:
        module = importlib.import_module(ENGINE_PACKAGES[key][1])
        return str(getattr(getattr(module, "version", None), "__version__", "") or "")
    except Exception:
        return ""


def _pypi_json(project: str) -> dict:
    request = urllib.request.Request(
        f"https://pypi.org/pypi/{project}/json",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1 << 16)


def _normalized(name: str) -> str:
    return name.replace("-", "_").lower()


def _purge_stale_distinfo(root: Path, project: str) -> None:
    """Drop previous .dist-info dirs so importlib.metadata reports the new version."""
    wanted = _normalized(project)
    try:
        for entry in root.iterdir():
            if not entry.is_dir() or not entry.name.endswith(".dist-info"):
                continue
            base = entry.name[: -len(".dist-info")]
            base = base.rsplit("-", 1)[0] if "-" in base else base
            if _normalized(base) == wanted:
                shutil.rmtree(entry, ignore_errors=True)
    except OSError:
        pass


def install_engine(key: str, log=None) -> tuple[bool, str]:
    """Download the newest wheel for *key* from PyPI and install it into engines/.

    Returns ``(ok, message)`` where *message* carries the installed version on
    success. Pure-python wheels only — no pip, no compiler, no interpreter
    mutation, so this works from inside a frozen EXE.
    """
    if key not in ENGINE_PACKAGES:
        return False, f"Unknown engine: {key}"
    project, _package = ENGINE_PACKAGES[key]

    def emit(text: str) -> None:
        if log is not None:
            try:
                log(text)
            except Exception:
                pass

    try:
        emit(f"Querying PyPI for {project}…")
        data = _pypi_json(project)
        version = str(data.get("info", {}).get("version") or "").strip()
        wheel = next(
            (item for item in data.get("urls", []) if item.get("packagetype") == "bdist_wheel" and str(item.get("filename", "")).endswith(".whl")),
            None,
        )
        if wheel is None:
            return False, f"No wheel published for {project}."
        url = str(wheel["url"])
        filename = str(wheel["filename"])
        emit(f"Newest {project} is {version} ({filename}).")

        root = engines_root()
        root.mkdir(parents=True, exist_ok=True)
        _purge_stale_distinfo(root, project)

        with tempfile.TemporaryDirectory(prefix="leon_engine_") as temp_dir:
            archive = Path(temp_dir) / filename
            emit(f"Downloading {filename}…")
            _download(url, archive)
            emit("Extracting…")
            with zipfile.ZipFile(archive) as bundle:
                for name in bundle.namelist():
                    # Skip paths that could escape the engine directory.
                    if name.startswith("/") or ".." in Path(name).parts:
                        continue
                    bundle.extract(name, root)
        emit(f"{project} {version} installed into {root}.")
        return True, version
    except Exception as exc:  # network / zip / permission issues
        return False, str(exc) or exc.__class__.__name__
