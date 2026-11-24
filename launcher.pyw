from __future__ import annotations

"""Console-free setup and launch for the Windows source distribution."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = Path.home() / ".yt_dlp_liquid" / "settings.json"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _runtime_paths(venv_dir: Path) -> tuple[Path, Path]:
    return venv_dir / "Scripts" / "python.exe", venv_dir / "Scripts" / "pythonw.exe"


def _core_runtime_usable(venv_dir: Path) -> bool:
    python_exe, pythonw_exe = _runtime_paths(venv_dir)
    if not python_exe.is_file() or not pythonw_exe.is_file():
        return False
    probe = (
        "import importlib.metadata as m, importlib.util as u, re;"
        "req={'pywebview':('webview',(6,0)),'yt-dlp':('yt_dlp',(2026,6,9)),"
        "'yt-dlp-ejs':(None,()),'curl-cffi':('curl_cffi',(0,13))};"
        "num=lambda s:tuple(int(x) for x in re.findall(r'\\d+',s)[:4]);"
        "[(None if (u.find_spec(mod) if mod else True) and num(m.version(dist))>=minimum "
        "else (_ for _ in ()).throw(RuntimeError(dist))) for dist,(mod,minimum) in req.items()]"
    )
    try:
        completed = subprocess.run(
            [str(python_exe), "-c", probe],
            cwd=str(APP_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _select_runtime_dir() -> Path:
    local = APP_DIR / ".venv"
    if _core_runtime_usable(local):
        return local

    try:
        siblings = sorted(
            (path for path in APP_DIR.parent.glob("LeonDL-v*") if path.is_dir() and path != APP_DIR),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        siblings = []

    for sibling in siblings[:12]:
        candidate = sibling / ".venv"
        if _core_runtime_usable(candidate):
            return candidate
    return local


VENV_DIR = _select_runtime_dir()
VENV_PYTHON, VENV_PYTHONW = _runtime_paths(VENV_DIR)
READY_STAMP = VENV_DIR / ".leon_environment_ready.json"


def _read_settings() -> dict[str, object]:
    try:
        value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def _environment_fingerprint() -> dict[str, object]:
    return {
        "schema": 2,
        "python": [sys.version_info.major, sys.version_info.minor],
        "requirements": _file_hash(APP_DIR / "requirements.txt"),
        "bootstrap": _file_hash(APP_DIR / "bootstrap.py"),
    }


def _environment_ready() -> bool:
    if not VENV_PYTHON.exists() or not VENV_PYTHONW.exists() or not READY_STAMP.exists():
        return False
    try:
        saved = json.loads(READY_STAMP.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return saved == _environment_fingerprint()


def _write_environment_stamp() -> None:
    READY_STAMP.parent.mkdir(parents=True, exist_ok=True)
    temporary = READY_STAMP.with_suffix(".tmp")
    temporary.write_text(json.dumps(_environment_fingerprint(), indent=2), encoding="utf-8")
    os.replace(temporary, READY_STAMP)


def _run_hidden(command: list[str], *, timeout: int | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=str(APP_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=CREATE_NO_WINDOW,
        )
        return completed.returncode, completed.stdout or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def main() -> int:
    if not _environment_ready():
        if not VENV_PYTHON.is_file():
            engine = Path(sys.executable).with_name("python.exe")
            code, output = _run_hidden([str(engine), "-m", "venv", str(VENV_DIR)], timeout=180)
            if code:
                return _report_error(output)
        code, output = _run_hidden([str(VENV_PYTHON), "bootstrap.py", "--skip-external", "--quiet"], timeout=900)
        if code:
            return _report_error(output)
        _write_environment_stamp()
    env = {**os.environ, "LEON_BOOTSTRAP_DONE": "1"}
    subprocess.Popen([str(VENV_PYTHONW), str(APP_DIR / "app.py")], cwd=APP_DIR, env=env,
                     creationflags=CREATE_NO_WINDOW)
    return 0


def _report_error(message: str) -> int:
    log = CONFIG_FILE.with_name("leon_runtime.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message[-3000:] + "\n\n" + str(log), "LeonDL", 0x10)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
