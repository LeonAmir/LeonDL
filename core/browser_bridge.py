from __future__ import annotations

"""Chrome extension bridge for LeonDL.

The bridge uses Chrome Native Messaging. Messages are accepted only from the
bundled extension ID and only when the per-install pairing token matches. Cookie
values never enter the persistent inbox: they are converted to Netscape format
inside the short-lived native host process and stored through AuthProfileStore.
"""

import hmac
import json
import os
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

from core.auth_store import AuthProfileStore, service_domain

APP_NAME = "LeonDL"
HOST_NAME = "com.leon_downloader.bridge"
EXTENSION_ID = "cilmnmiidbeningdcggocddbpjmmclmn"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}/"
CONFIG_DIR = Path.home() / ".yt_dlp_liquid"
BRIDGE_DIR = CONFIG_DIR / "browser_bridge"
REQUESTS_DIR = BRIDGE_DIR / "requests"
PAIRING_FILE = BRIDGE_DIR / "pairing.json"
HOST_MANIFEST_FILE = BRIDGE_DIR / f"{HOST_NAME}.json"
HOST_WRAPPER_FILE = BRIDGE_DIR / "leon-native-host.cmd"
EXTENSION_INSTALL_DIR = BRIDGE_DIR / "chrome_extension"
HEARTBEAT_FILE = BRIDGE_DIR / "app-heartbeat.json"
START_LOCK_FILE = BRIDGE_DIR / "app-starting.lock"
MAX_NATIVE_MESSAGE = 8 * 1024 * 1024
MAX_COOKIES = 500


class BrowserBridgeError(RuntimeError):
    pass


def _project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def bundled_extension_dir() -> Path:
    return _project_root() / "chrome_extension"


def installed_extension_dir() -> Path:
    return EXTENSION_INSTALL_DIR


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass


def ensure_pairing_token() -> str:
    try:
        payload = json.loads(PAIRING_FILE.read_text(encoding="utf-8"))
        token = str(payload.get("token") or "").strip()
        if len(token) >= 24:
            return token
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    token = secrets.token_urlsafe(24)
    _atomic_json(
        PAIRING_FILE,
        {
            "version": 1,
            "token": token,
            "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        },
    )
    try:
        PAIRING_FILE.chmod(0o600)
    except OSError:
        pass
    return token


def pairing_token() -> str:
    return ensure_pairing_token()


def _registry_manifest_path() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _kind = winreg.QueryValueEx(key, None)
        return str(value or "")
    except (OSError, ImportError):
        return ""


def bridge_status() -> dict[str, Any]:
    manifest_path = _registry_manifest_path()
    manifest_ok = bool(manifest_path) and Path(manifest_path).resolve() == HOST_MANIFEST_FILE.resolve() and HOST_MANIFEST_FILE.is_file()
    extension_ok = (EXTENSION_INSTALL_DIR / "manifest.json").is_file()
    token_ok = False
    try:
        token_ok = len(pairing_token()) >= 24
    except OSError:
        pass
    host_target = ""
    try:
        data = json.loads(HOST_MANIFEST_FILE.read_text(encoding="utf-8"))
        host_target = str(data.get("path") or "")
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return {
        "supported": os.name == "nt",
        "registered": manifest_ok,
        "extension_ready": extension_ok,
        "pairing_ready": token_ok,
        "manifest_path": str(HOST_MANIFEST_FILE),
        "host_path": host_target,
        "extension_path": str(EXTENSION_INSTALL_DIR),
        "extension_id": EXTENSION_ID,
    }


def _source_python() -> Path:
    root = _project_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise BrowserBridgeError("Python executable for the native host was not found.")


def _prepare_host_path() -> Path:
    if getattr(sys, "frozen", False):
        release_dir = Path(sys.executable).resolve().parent
        candidates = sorted(release_dir.glob("LeonDL-Native-Host-*.exe"), reverse=True)
        if not candidates:
            candidate = release_dir / "LeonDL-Native-Host.exe"
            if candidate.is_file():
                candidates = [candidate]
        if not candidates:
            raise BrowserBridgeError(
                "The dedicated Leon Native Host executable is missing beside the main EXE."
            )
        return candidates[0].resolve()
    python_exe = _source_python()
    app_path = (_project_root() / "app.py").resolve()
    wrapper = (
        "@echo off\r\n"
        f'"{python_exe}" "{app_path}" --native-messaging-host %*\r\n'
    )
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    HOST_WRAPPER_FILE.write_text(wrapper, encoding="utf-8", newline="")
    return HOST_WRAPPER_FILE.resolve()


def install_browser_bridge() -> dict[str, Any]:
    if os.name != "nt":
        raise BrowserBridgeError("Automatic Chrome bridge installation is currently available on Windows only.")
    source = bundled_extension_dir()
    if not (source / "manifest.json").is_file():
        raise BrowserBridgeError("The bundled Chrome extension files were not found.")

    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    if EXTENSION_INSTALL_DIR.exists():
        shutil.rmtree(EXTENSION_INSTALL_DIR)
    shutil.copytree(source, EXTENSION_INSTALL_DIR)
    ensure_pairing_token()
    host_path = _prepare_host_path()
    manifest = {
        "name": HOST_NAME,
        "description": "LeonDL Chrome bridge",
        "path": str(host_path),
        "type": "stdio",
        "allowed_origins": [EXTENSION_ORIGIN],
    }
    _atomic_json(HOST_MANIFEST_FILE, manifest)

    try:
        import winreg

        key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(HOST_MANIFEST_FILE.resolve()))
    except (OSError, ImportError) as exc:
        raise BrowserBridgeError(f"Could not register the Chrome native messaging host: {exc}") from exc
    return bridge_status()


def uninstall_browser_bridge(*, remove_pairing: bool = False) -> None:
    if os.name == "nt":
        try:
            import winreg

            key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
        except (OSError, ImportError):
            pass
    for path in (HOST_MANIFEST_FILE, HOST_WRAPPER_FILE):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    if remove_pairing:
        try:
            PAIRING_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def _read_exact(stream: BinaryIO, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_native_message(stream: BinaryIO) -> dict[str, Any]:
    raw_length = _read_exact(stream, 4)
    (length,) = struct.unpack("@I", raw_length)
    if length <= 0 or length > MAX_NATIVE_MESSAGE:
        raise BrowserBridgeError("Native message size is invalid.")
    payload = json.loads(_read_exact(stream, length).decode("utf-8"))
    if not isinstance(payload, dict):
        raise BrowserBridgeError("Native message must be a JSON object.")
    return payload


def _write_native_message(stream: BinaryIO, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > 900_000:
        data = b'{"ok":false,"error":"Response too large"}'
    stream.write(struct.pack("@I", len(data)))
    stream.write(data)
    stream.flush()


def _calling_origin(argv: list[str]) -> str:
    for argument in argv[1:]:
        value = str(argument or "").strip()
        if value.startswith("chrome-extension://"):
            return value if value.endswith("/") else value + "/"
    return ""


def _valid_url(value: object) -> str:
    url = str(value or "").strip()
    if not url or len(url) > 8192:
        raise BrowserBridgeError("The browser URL is empty or too long.")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BrowserBridgeError("Only HTTP and HTTPS URLs can be sent to LeonDL.")
    return url


def _clean_cookie_field(value: object, *, limit: int) -> str:
    text = str(value or "")[:limit]
    return text.replace("\r", "%0D").replace("\n", "%0A").replace("\t", "%09")


def _cookie_matches_host(cookie_domain: str, target_host: str) -> bool:
    domain = cookie_domain.lower().lstrip(".").rstrip(".")
    host = target_host.lower().rstrip(".")
    return bool(domain) and (host == domain or host.endswith("." + domain))


def _cookies_to_netscape(url: str, cookies: object) -> tuple[str, int, int]:
    parsed = urlparse(url)
    target_host = (parsed.hostname or "").lower()
    if not isinstance(cookies, list):
        return "", 0, 0
    lines = ["# Netscape HTTP Cookie File", "# Generated locally by LeonDL Chrome Bridge"]
    accepted = 0
    skipped_partitioned = 0
    for raw in cookies[:MAX_COOKIES]:
        if not isinstance(raw, dict):
            continue
        if raw.get("partitionKey"):
            skipped_partitioned += 1
            continue
        name = _clean_cookie_field(raw.get("name"), limit=512).strip()
        value = _clean_cookie_field(raw.get("value"), limit=8192)
        domain_raw = _clean_cookie_field(raw.get("domain"), limit=512).strip()
        if not name or not _cookie_matches_host(domain_raw, target_host):
            continue
        host_only = bool(raw.get("hostOnly", False))
        domain = domain_raw.lstrip(".") if host_only else "." + domain_raw.lstrip(".")
        if bool(raw.get("httpOnly", False)):
            domain = "#HttpOnly_" + domain
        include_subdomains = "FALSE" if host_only else "TRUE"
        path = _clean_cookie_field(raw.get("path") or "/", limit=2048) or "/"
        secure = "TRUE" if bool(raw.get("secure", False)) else "FALSE"
        try:
            expiry = max(0, int(float(raw.get("expirationDate") or 0)))
        except (TypeError, ValueError):
            expiry = 0
        lines.append("\t".join((domain, include_subdomains, path, secure, str(expiry), name, value)))
        accepted += 1
    return ("\n".join(lines) + "\n" if accepted else ""), accepted, skipped_partitioned


def _store_browser_cookies(url: str, cookies: object) -> dict[str, Any]:
    text, accepted, skipped_partitioned = _cookies_to_netscape(url, cookies)
    if not text:
        return {"saved": 0, "skipped_partitioned": skipped_partitioned, "domains": []}
    domain = service_domain(url)
    if not domain:
        return {"saved": 0, "skipped_partitioned": skipped_partitioned, "domains": []}
    store = AuthProfileStore(CONFIG_DIR)
    if os.name == "nt":
        store.remember_manual([domain], text, "." + domain, method="extension")
    else:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        temporary = BRIDGE_DIR / f"cookies-{uuid.uuid4().hex}.txt"
        temporary.write_text(text, encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        try:
            store.remember_cookie_file([domain], temporary, method="extension")
        finally:
            temporary.unlink(missing_ok=True)
    return {"saved": accepted, "skipped_partitioned": skipped_partitioned, "domains": [domain]}


def _write_request(payload: dict[str, Any]) -> str:
    request_id = uuid.uuid4().hex
    request = {
        "version": 1,
        "id": request_id,
        "action": str(payload.get("action") or "open"),
        "url": str(payload.get("url") or ""),
        "title": str(payload.get("title") or "")[:1000],
        "received_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "source": "chrome_extension",
        "cookie_domains": list(payload.get("cookie_domains") or []),
        "cookie_count": int(payload.get("cookie_count") or 0),
    }
    REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_json(REQUESTS_DIR / f"{time.time_ns()}-{request_id}.json", request)
    return request_id


def consume_browser_requests(*, limit: int = 25) -> list[dict[str, Any]]:
    if not REQUESTS_DIR.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted(REQUESTS_DIR.glob("*.json"))[: max(1, int(limit))]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                url = _valid_url(payload.get("url"))
                action = str(payload.get("action") or "open")
                if action not in {"open", "queue"}:
                    action = "open"
                payload["url"] = url
                payload["action"] = action
                result.append(payload)
        except (OSError, json.JSONDecodeError, BrowserBridgeError):
            pass
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return result


def touch_app_heartbeat() -> None:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        HEARTBEAT_FILE.touch()
    except OSError:
        pass
    try:
        START_LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def clear_app_heartbeat() -> None:
    try:
        HEARTBEAT_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _app_is_active() -> bool:
    try:
        return time.time() - HEARTBEAT_FILE.stat().st_mtime < 8.0
    except OSError:
        return False


def _acquire_start_lock() -> bool:
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if START_LOCK_FILE.exists() and time.time() - START_LOCK_FILE.stat().st_mtime < 20:
            return False
    except OSError:
        pass
    try:
        fd = os.open(str(START_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            START_LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            return False
        try:
            fd = os.open(str(START_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(time.time()))
    return True


def _main_gui_executable() -> Path:
    """Resolve the GUI executable from a dedicated frozen native host."""
    release_dir = Path(sys.executable).resolve().parent
    version = ""
    try:
        version = (release_dir / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    candidates: list[Path] = []
    if version:
        candidates.append(release_dir / f"LeonDL-{version}.exe")
    candidates.append(release_dir / "LeonDL.exe")
    candidates.extend(
        sorted(
            (
                path
                for path in release_dir.glob("LeonDL-*.exe")
                if "native-host" not in path.name.lower()
            ),
            key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
            reverse=True,
        )
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise BrowserBridgeError("The LeonDL GUI executable is missing beside the Native Host.")


def _start_gui_if_needed() -> bool:
    if _app_is_active() or not _acquire_start_lock():
        return False
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    root = _project_root()
    env = os.environ.copy()
    env["LEON_BOOTSTRAP_DONE"] = "1"
    try:
        if getattr(sys, "frozen", False):
            command = [str(_main_gui_executable()), "--from-browser"]
        else:
            candidates = [
                root / ".venv" / "Scripts" / "pythonw.exe",
                Path(sys.executable).resolve().with_name("pythonw.exe"),
                Path(sys.executable).resolve(),
            ]
            executable = next((candidate for candidate in candidates if candidate.is_file()), candidates[-1])
            command = [str(executable), str(root / "app.py"), "--from-browser"]
        subprocess.Popen(
            command,
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=os.name != "nt",
        )
        return True
    except OSError:
        try:
            START_LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _handle_native_message(message: dict[str, Any]) -> dict[str, Any]:
    supplied_token = str(message.get("pairingToken") or "")
    expected_token = pairing_token()
    if not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        raise BrowserBridgeError("Pairing code is missing or invalid.")
    message_type = str(message.get("type") or "submit")
    if message_type == "ping":
        return {"ok": True, "version": 1, "app": APP_NAME}
    if message_type != "submit":
        raise BrowserBridgeError("Unsupported bridge message type.")
    action = str(message.get("action") or "open")
    if action not in {"open", "queue"}:
        raise BrowserBridgeError("Unsupported browser action.")
    url = _valid_url(message.get("url"))
    title = str(message.get("title") or "").strip()[:1000]
    cookie_result = _store_browser_cookies(url, message.get("cookies"))
    request_id = _write_request(
        {
            "action": action,
            "url": url,
            "title": title,
            "cookie_domains": cookie_result["domains"],
            "cookie_count": cookie_result["saved"],
        }
    )
    launched = _start_gui_if_needed()
    return {
        "ok": True,
        "requestId": request_id,
        "action": action,
        "cookiesSaved": cookie_result["saved"],
        "partitionedCookiesSkipped": cookie_result["skipped_partitioned"],
        "appLaunchRequested": launched,
    }


def run_native_host(argv: list[str] | None = None) -> int:
    arguments = list(argv or sys.argv)
    if os.name == "nt":
        try:
            import msvcrt

            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        except (OSError, AttributeError):
            pass
    stdin = getattr(sys.stdin, "buffer", sys.stdin)
    stdout = getattr(sys.stdout, "buffer", sys.stdout)
    try:
        origin = _calling_origin(arguments)
        if origin != EXTENSION_ORIGIN:
            raise BrowserBridgeError("This native host only accepts the bundled Leon extension.")
        message = _read_native_message(stdin)
        response = _handle_native_message(message)
        _write_native_message(stdout, response)
        return 0
    except EOFError:
        return 1
    except Exception as exc:
        try:
            _write_native_message(stdout, {"ok": False, "error": str(exc)[:1200]})
        except Exception:
            pass
        return 1
