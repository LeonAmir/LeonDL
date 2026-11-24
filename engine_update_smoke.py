from io import BytesIO
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile

from core import engine_update

VERSION = "2099.1.1"
EJS_VERSION = "1.2.3"


def wheel(module: str, version: str, requires: str = "") -> bytes:
    data = BytesIO()
    with ZipFile(data, "w") as archive:
        archive.writestr(f"{module}/__init__.py", "")
        archive.writestr(
            f"{module}-{version}.dist-info/METADATA",
            f"Name: {module}\nVersion: {version}\n{requires}\n",
        )
    return data.getvalue()


def main() -> None:
    def fetch(project: str, pin: str = "") -> tuple[str, bytes]:
        if project == "yt-dlp":
            return VERSION, wheel("yt_dlp", VERSION, "Requires-Dist: yt-dlp-ejs==1.2.3; extra == 'default'")
        assert pin == EJS_VERSION
        return EJS_VERSION, wheel("yt_dlp_ejs", EJS_VERSION)

    with TemporaryDirectory() as directory:
        root = Path(directory)
        with (
            patch.object(engine_update, "ENGINE_ROOT", root),
            patch.object(engine_update, "_wheel", side_effect=fetch),
            patch.object(engine_update.subprocess, "run", return_value=CompletedProcess([], 0)) as probe,
        ):
            result = engine_update.update_engine("2026.7.4", print)
            assert "Restart LeonDL" in result
            marker = root / "active"
            generation = marker.read_text(encoding="ascii")
            assert (root / generation / "yt_dlp" / "__init__.py").is_file()
            assert (root / generation / "yt_dlp_ejs" / "__init__.py").is_file()

            probe.return_value = CompletedProcess([], 1)
            try:
                engine_update.update_engine("2026.7.4", print)
            except RuntimeError:
                pass
            else:
                raise AssertionError("A failed engine probe must reject the update")
            assert marker.read_text(encoding="ascii") == generation
            assert set(root.iterdir()) == {marker, root / generation}

            probe.reset_mock()
            assert "already up to date" in engine_update.update_engine(VERSION, print)
            probe.assert_not_called()

    print("Frozen engine update smoke test: OK")


if __name__ == "__main__":
    main()
