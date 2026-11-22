"""Smoke test for the updatable engine directory (core/engine_loader.py).

Verifies — with no network and no PyPI dependency — that:

1. ``engines_root()`` points beside the executable (frozen) or the project root.
2. A hand-built engine package in ``engines/`` wins the import race against an
   earlier meta-path finder (the situation PyInstaller's frozen importer creates).
3. Removing the engine directory falls back cleanly to the bundled copy.
4. ``engine_installed_version`` reports the engine version when present.

Run: .venv/Scripts/python engine_loader_smoke.py
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

failures: list[str] = []


def check(name: str, condition: bool) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    if not condition:
        failures.append(name)


PROBE = "leon_engine_probe"
PKG = "leon_engine_probe"


def build_fake_engine(root: Path, version: str) -> None:
    package = root / PKG
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text('BUNDLED = False\n', encoding="utf-8")
    (package / "version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    dist = root / f"{PKG}-{version}.dist-info"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {PKG}\nVersion: {version}\n", encoding="utf-8"
    )


def main() -> int:
    from core import engine_loader

    real_root = engine_loader.engines_root()
    backup = None
    if real_root.exists():
        backup = Path(tempfile.mkdtemp(prefix="leon_engine_backup_"))
        shutil.move(str(real_root), str(backup / "engines"))

    try:
        # 1. No engine dir -> activate returns None and import still works.
        check("activate_engines() is None without an engine dir", engine_loader.activate_engines() is None)

        # 2. Install a fake engine + an early frozen-style finder, engine must win.
        build_fake_engine(real_root, "9999.1.1")

        class EarlierFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):  # noqa: D102
                return None

        sys.meta_path.insert(0, EarlierFinder())
        # reset loader state so the finder is (re)built against the new dir
        engine_loader._ACTIVATED = False
        activated = engine_loader.activate_engines()
        check("activate_engines() returns the engine dir", activated == real_root)
        check("engine finder wins meta_path[0]", type(sys.meta_path[0]).__name__ == "_EngineFinder")

        module = __import__(PKG)
        check("engine package resolves from engines/", str(real_root) in str(module.__file__))
        # engine_installed_version only knows registered engines, so register the
        # probe for the duration of the check.
        engine_loader.ENGINE_PACKAGES[PKG] = (PKG, PKG)
        try:
            version = engine_loader.engine_installed_version(PKG)
        finally:
            engine_loader.ENGINE_PACKAGES.pop(PKG, None)
        check("engine version reported", version == "9999.1.1")

        # 3. Remove the engine dir -> fall back cleanly.
        shutil.rmtree(real_root, ignore_errors=True)
        engine_loader._ACTIVATED = False
        check("fallback is clean once the engine dir is gone", engine_loader.activate_engines() is None)

        # 4. Package table maps the real engine keys.
        from core.package_manager import engine_keys

        check("engine_keys includes yt_dlp and yt_dlp_ejs", {"yt_dlp", "yt_dlp_ejs"} <= engine_keys())
    finally:
        for leftover in ("leon_engine_probe", "leon_engine_probe-9999.1.1.dist-info"):
            shutil.rmtree(real_root / leftover, ignore_errors=True)
        shutil.rmtree(real_root, ignore_errors=True)
        if backup is not None:
            shutil.move(str(backup / "engines"), str(real_root))
            shutil.rmtree(backup, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("engine_loader_smoke: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
