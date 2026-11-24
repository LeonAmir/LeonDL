"""Update download runtime packages in frozen Windows builds."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
import traceback
import urllib.request
import uuid
import zipfile
from importlib.machinery import PathFinder
from io import BytesIO
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import Version

ENGINE_ROOT = Path.home() / ".yt_dlp_liquid" / "engines"
PROJECTS = {"yt-dlp": "yt_dlp", "yt-dlp-ejs": "yt_dlp_ejs"}
MAX_WHEEL_BYTES = 20 * 1024 * 1024
EXTRA_PROJECTS = {"yt-dlp-ejs": "yt_dlp_ejs", "curl-cffi": "curl_cffi"}
_active_root: Path | None = None
_extra_roots: dict[str, Path] = {}


class EngineFinder:
    def __init__(self, root: Path, modules=PROJECTS.values()) -> None:
        self.root = str(root)
        self.modules = modules

    def find_spec(self, fullname, path=None, target=None):
        if fullname.partition(".")[0] in self.modules:
            return PathFinder.find_spec(fullname, [self.root] if path is None else path)
        return None


def activate_engine(root: Path | None = None) -> None:
    global _active_root
    if root is None:
        try:
            generation = (ENGINE_ROOT / "active").read_text(encoding="ascii").strip()
        except (OSError, UnicodeError):
            return
        if not re.fullmatch(r"[0-9a-f]{32}", generation):
            return
        root = ENGINE_ROOT / generation
    if all((root / module / "__init__.py").is_file() for module in PROJECTS.values()):
        sys.meta_path.insert(0, EngineFinder(root))
        _active_root = root


def engine_distribution(project: str):
    if project in _extra_roots:
        return next(iter(importlib.metadata.distributions(name=project, path=[str(_extra_roots[project])])), None)
    if _active_root is not None and project in PROJECTS:
        return next(iter(importlib.metadata.distributions(name=project, path=[str(_active_root)])), None)
    return None


def _wheel(project: str, pin: str = "") -> tuple[str, bytes]:
    release = "/" + str(Version(pin)) if pin else ""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{project}{release}/json", timeout=25) as response:
        metadata = json.load(response)
    python_version = ".".join(map(str, sys.version_info[:3]))
    tags = list(sys_tags())
    rank = {tag: index for index, tag in enumerate(tags)}
    choices = []
    for file in metadata["urls"]:
        try:
            name, _, _, wheel_tags = parse_wheel_filename(file["filename"])
        except InvalidWheelFilename:
            continue
        compatible = wheel_tags.intersection(rank)
        if file.get("yanked") or name != project or not compatible:
            continue
        if project != "curl-cffi" and not file["filename"].endswith("-py3-none-any.whl"):
            continue
        if not SpecifierSet(file.get("requires_python") or "").contains(python_version):
            continue
        if not file["url"].startswith("https://files.pythonhosted.org/"):
            continue
        choices.append((min(rank[tag] for tag in compatible), file))
    if choices:
        _, file = min(choices, key=lambda choice: choice[0])
        with urllib.request.urlopen(file["url"], timeout=30) as response:
            data = response.read(MAX_WHEEL_BYTES + 1)
        if len(data) != file["size"] or len(data) > MAX_WHEEL_BYTES:
            raise ValueError(f"Unexpected wheel size for {project}.")
        if hashlib.sha256(data).hexdigest() != file["digests"]["sha256"]:
            raise ValueError(f"SHA-256 mismatch for {project}.")
        return metadata["info"]["version"], data
    raise ValueError(f"No compatible wheel found for {project}.")


def _extract_wheel(project: str, data: bytes, destination: Path) -> None:
    module = (PROJECTS | EXTRA_PROJECTS)[project]
    with zipfile.ZipFile(BytesIO(data)) as wheel:
        if sum(entry.file_size for entry in wheel.infolist()) > 4 * MAX_WHEEL_BYTES:
            raise ValueError(f"Unpacked wheel is too large for {project}.")
        for entry in wheel.infolist():
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in entry.filename or ":" in entry.filename:
                raise ValueError(f"Invalid wheel path for {project}.")
            if name.parts and (name.parts[0] in {module, module + ".libs"} or name.parts[0].startswith(module + "-")
                               and name.parts[0].endswith(".dist-info")):
                wheel.extract(entry, destination)
    if not (destination / module / "__init__.py").is_file():
        raise ValueError(f"Wheel is missing the {module} package.")


def probe_engine(root: Path) -> int:
    try:
        return _check_engine(root)
    except Exception:
        (root.parent / "probe-error").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def _check_engine(root: Path) -> int:
    activate_engine(root)
    if _active_root != root:
        return 1
    from yt_dlp import YoutubeDL
    from yt_dlp.version import __version__
    from yt_dlp_ejs import __file__ as ejs_file

    if not Path(ejs_file).is_relative_to(root) or Version(__version__) != Version(engine_distribution("yt-dlp").version):
        return 1
    with YoutubeDL({"quiet": True, "cachedir": False}) as engine:
        engine.get_info_extractor("Youtube")
    return 0


def update_engine(current_version: str, log) -> str:
    version, wheel = _wheel("yt-dlp")
    if current_version and Version(version) <= Version(current_version):
        return f"yt-dlp {current_version} is already up to date."
    log(f"Preparing yt-dlp {version} and its JavaScript components...")
    ENGINE_ROOT.mkdir(parents=True, exist_ok=True)
    generation = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="staging-", dir=ENGINE_ROOT) as staging:
        stage = Path(staging)
        candidate = stage / generation
        candidate.mkdir()
        _extract_wheel("yt-dlp", wheel, candidate)
        package = next(importlib.metadata.distributions(name="yt-dlp", path=[str(candidate)]))
        constraints = _ejs_constraints(package)
        pin = _pinned_version(constraints)
        ejs_version, ejs_wheel = _wheel("yt-dlp-ejs", pin)
        if any(Version(ejs_version) not in constraint for constraint in constraints):
            raise ValueError(f"yt-dlp {version} requires a different yt-dlp-ejs version.")
        _extract_wheel("yt-dlp-ejs", ejs_wheel, candidate)
        _run_probe(candidate, log)
        candidate.rename(ENGINE_ROOT / generation)
        marker = stage / "active"
        marker.write_text(generation, encoding="ascii")
        os.replace(marker, ENGINE_ROOT / "active")
    return f"yt-dlp {version} is ready. Restart LeonDL to use the update."


def _ejs_constraints(package):
    return [
        req.specifier for req in map(Requirement, package.requires or [])
        if req.name.lower().replace("_", "-") == "yt-dlp-ejs"
        and (req.marker is None or req.marker.evaluate({"extra": "default"}))
    ]


def _pinned_version(constraints) -> str:
    return next((spec.version for constraint in constraints for spec in constraint
                 if spec.operator == "==" and "*" not in spec.version), "")


def _run_probe(candidate: Path, log, project: str = "") -> None:
    args = [sys.executable, "--leondl-engine-probe", str(candidate)]
    if project:
        args.append(project)
    result = subprocess.run(
        args, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"},
    )
    if result.returncode:
        diagnostic = candidate.parent / "probe-error"
        if diagnostic.is_file():
            log(diagnostic.read_text(encoding="utf-8"))
        raise RuntimeError("The new package could not start in this LeonDL build.")


def activate_extra_engines() -> None:
    for project in EXTRA_PROJECTS:
        try:
            generation = (ENGINE_ROOT / f"active-{project}").read_text(encoding="ascii").strip()
            if re.fullmatch(r"[0-9a-f]{32}", generation):
                _activate_extra(project, ENGINE_ROOT / generation)
        except (OSError, UnicodeError, ValueError, importlib.metadata.PackageNotFoundError):
            continue


def _activate_extra(project: str, root: Path) -> None:
    module = EXTRA_PROJECTS[project]
    if not (root / module / "__init__.py").is_file():
        raise ValueError(f"Missing package files for {project}.")
    distribution = next(iter(importlib.metadata.distributions(name=project, path=[str(root)])), None)
    if distribution is None:
        raise ValueError(f"Missing version metadata for {project}.")
    if project == "yt-dlp-ejs":
        engine = engine_distribution("yt-dlp") or importlib.metadata.distribution("yt-dlp")
        if any(Version(distribution.version) not in constraint for constraint in _ejs_constraints(engine)):
            raise ValueError(f"{project} {distribution.version} is incompatible with yt-dlp {engine.version}.")
    sys.meta_path.insert(0, EngineFinder(root, (module,)))
    _extra_roots[project] = root


def probe_extra(root: Path, project: str) -> int:
    try:
        import importlib

        activate_engine()
        _activate_extra(project, root)
        module = importlib.import_module(EXTRA_PROJECTS[project])
        if not Path(module.__file__).is_relative_to(root):
            raise RuntimeError(f"{project} did not load from the updated package.")
        if project == "curl-cffi":
            from curl_cffi.requests.impersonate import DEFAULT_CHROME

            with module.Session(impersonate="chrome"):
                curl = module.Curl()
                try:
                    if curl.impersonate(DEFAULT_CHROME):
                        raise RuntimeError("The curl library rejected the Chrome profile.")
                finally:
                    curl.close()
        else:
            from yt_dlp import YoutubeDL

            with YoutubeDL({"quiet": True, "cachedir": False}) as engine:
                engine.get_info_extractor("Youtube")
        return 0
    except Exception:
        (root.parent / "probe-error").write_text(traceback.format_exc(), encoding="utf-8")
        return 1


def update_extra_engine(project: str, current: str, log) -> str:
    constraints = []
    if project == "yt-dlp-ejs":
        engine = engine_distribution("yt-dlp") or importlib.metadata.distribution("yt-dlp")
        constraints = _ejs_constraints(engine)
    version, wheel = _wheel(project, _pinned_version(constraints))
    if any(Version(version) not in constraint for constraint in constraints):
        raise ValueError(f"No compatible {project} update for the active yt-dlp.")
    if current and Version(version) <= Version(current):
        return f"{project} {current} is already up to date for this build."
    log(f"Preparing {project} {version}...")
    ENGINE_ROOT.mkdir(parents=True, exist_ok=True)
    generation = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="staging-", dir=ENGINE_ROOT) as staging:
        stage = Path(staging)
        candidate = stage / generation
        candidate.mkdir()
        _extract_wheel(project, wheel, candidate)
        if project == "curl-cffi":
            package = next(importlib.metadata.distributions(name=project, path=[str(candidate)]))
            for req in map(Requirement, package.requires or []):
                if req.marker is not None and not req.marker.evaluate({"extra": ""}):
                    continue
                try:
                    present = importlib.metadata.version(req.name)
                except importlib.metadata.PackageNotFoundError:
                    present = ""
                if not present or Version(present) not in req.specifier:
                    raise RuntimeError(f"{project} {version} requires {req}; bundled version: {present or 'missing'}.")
        _run_probe(candidate, log, project)
        candidate.rename(ENGINE_ROOT / generation)
        marker = stage / "active"
        marker.write_text(generation, encoding="ascii")
        os.replace(marker, ENGINE_ROOT / f"active-{project}")
    return f"{project} {version} is ready. Restart LeonDL to use the update."
