from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import shutil
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SERVICE_DOMAIN_ALIASES = {
    "youtu.be": "youtube.com",
    "youtube-nocookie.com": "youtube.com",
    "x.com": "twitter.com",
}

KNOWN_SERVICE_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "instagram.com",
    "facebook.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "vimeo.com",
    "twitch.tv",
    "reddit.com",
    "soundcloud.com",
    "pornhub.com",
)


class AuthStoreError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(data: bytes) -> tuple[_DataBlob, Any]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise AuthStoreError("Windows DPAPI is only available on Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    input_blob, input_buffer = _blob_from_bytes(data)
    output_blob = _DataBlob()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "LeonDL authentication",
        None,
        None,
        None,
        flags,
        ctypes.byref(output_blob),
    ):
        raise AuthStoreError(f"DPAPI encryption failed with Windows error {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
        _ = input_buffer


def _dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise AuthStoreError("Windows DPAPI is only available on Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    input_blob, input_buffer = _blob_from_bytes(data)
    output_blob = _DataBlob()
    flags = 0x01  # CRYPTPROTECT_UI_FORBIDDEN
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        flags,
        ctypes.byref(output_blob),
    ):
        raise AuthStoreError(f"DPAPI decryption failed with Windows error {ctypes.get_last_error()}.")
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
        _ = input_buffer


def service_domain(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw.lstrip(".")
    try:
        host = (urlparse(raw).hostname or "").lower().strip().rstrip(".")
    except ValueError:
        return ""
    for prefix in ("www.", "m.", "music.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix):]
            break
    for known in KNOWN_SERVICE_DOMAINS:
        if host == known or host.endswith("." + known):
            return SERVICE_DOMAIN_ALIASES.get(known, known)
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    # Preserve common two-level public suffixes.
    if ".".join(parts[-2:]) in {"co.uk", "com.au", "co.jp", "co.in", "com.br", "com.tr"} and len(parts) >= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def domains_for_urls(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        domain = service_domain(url)
        if domain and domain not in seen:
            seen.add(domain)
            result.append(domain)
    return result


class AuthProfileStore:
    """Stores reusable authentication profiles under the user's profile.

    Browser settings and managed cookie paths are plain metadata. Pasted cookie
    data is protected with the current Windows user's DPAPI key and is not
    readable by another Windows account.
    """

    def __init__(self, config_dir: Path) -> None:
        self.root = Path(config_dir) / "auth"
        self.cookie_dir = self.root / "cookies"
        self.secret_dir = self.root / "secrets"
        self.index_file = self.root / "profiles.json"
        self._data: dict[str, Any] = {"version": 1, "profiles": {}}
        self._index_signature: tuple[int, int] | None = None
        self._load()

    def _signature(self) -> tuple[int, int] | None:
        try:
            stat = self.index_file.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _load(self) -> None:
        try:
            loaded = json.loads(self.index_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                profiles = loaded.get("profiles")
                if isinstance(profiles, dict):
                    self._data = {"version": 1, "profiles": profiles}
                else:
                    self._data = {"version": 1, "profiles": {}}
            else:
                self._data = {"version": 1, "profiles": {}}
        except (OSError, json.JSONDecodeError):
            self._data = {"version": 1, "profiles": {}}
        self._index_signature = self._signature()

    def refresh(self, *, force: bool = False) -> bool:
        """Reload profiles written by another Leon process.

        The Chrome native host stores extension cookies in a short-lived process
        while the GUI keeps an AuthProfileStore instance alive.  This method
        prevents that GUI instance from serving stale profile data or
        overwriting a newly received extension profile.
        """
        current = self._signature()
        if not force and current == self._index_signature:
            return False
        self._load()
        return True

    def _save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(prefix="profiles_", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.index_file)
            self._index_signature = self._signature()
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass

    def profile(self, domain: str, *, valid_only: bool = True) -> dict[str, Any] | None:
        self.refresh()
        key = service_domain(domain)
        if not key:
            return None
        value = self._data.get("profiles", {}).get(key)
        if not isinstance(value, dict):
            return None
        if valid_only and not bool(value.get("valid", False)):
            return None
        return dict(value)

    def profile_for_urls(self, urls: Iterable[str], *, valid_only: bool = True) -> tuple[str, dict[str, Any]] | None:
        domains = domains_for_urls(urls)
        if len(domains) != 1:
            return None
        profile = self.profile(domains[0], valid_only=valid_only)
        return (domains[0], profile) if profile else None

    def remember_browser(self, domains: Iterable[str], browser: str, profile: str | None) -> None:
        self.refresh()
        record = {
            "method": "browser",
            "browser": browser,
            "browser_profile": profile or "",
            "valid": False,
        }
        self._set_profiles(domains, record)

    def remember_cookie_file(self, domains: Iterable[str], source_path: Path, *, method: str = "file") -> Path:
        self.refresh()
        source = Path(source_path).expanduser().resolve()
        if not source.is_file():
            raise AuthStoreError("The selected cookies.txt file was not found.")
        domain_list = [item for item in domains if item]
        seed = "|".join(sorted(domain_list)) or source.name
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        self.cookie_dir.mkdir(parents=True, exist_ok=True)
        target = self.cookie_dir / f"cookies-{digest}.txt"
        if source != target.resolve():
            shutil.copy2(source, target)
        try:
            target.chmod(0o600)
        except OSError:
            pass
        record = {
            "method": method if method in {"file", "extension"} else "file",
            "cookie_file": str(target),
            "valid": False,
        }
        self._set_profiles(domain_list, record)
        return target

    def remember_manual(
        self,
        domains: Iterable[str],
        raw_text: str,
        cookie_domain: str,
        *,
        method: str = "manual",
    ) -> None:
        self.refresh()
        if not raw_text.strip():
            raise AuthStoreError("Cookie data is empty.")
        if os.name != "nt":
            raise AuthStoreError("Saving pasted cookies securely requires Windows DPAPI.")
        domain_list = [item for item in domains if item]
        seed = "|".join(sorted(domain_list)) or cookie_domain or "manual"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        self.secret_dir.mkdir(parents=True, exist_ok=True)
        secret_path = self.secret_dir / f"cookie-{digest}.bin"
        protected = _dpapi_protect(raw_text.encode("utf-8"))
        secret_path.write_bytes(base64.b64encode(protected))
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
        record = {
            "method": method if method in {"manual", "extension"} else "manual",
            "cookie_domain": cookie_domain,
            "secret_file": str(secret_path),
            "valid": False,
        }
        self._set_profiles(domain_list, record)

    def read_manual_secret(self, profile: dict[str, Any]) -> str:
        path = Path(str(profile.get("secret_file") or "")).expanduser()
        if not path.is_file():
            raise AuthStoreError("The saved encrypted cookie could not be found.")
        if os.name != "nt":
            raise AuthStoreError("Saved cookies can only be decrypted on Windows.")
        try:
            protected = base64.b64decode(path.read_bytes(), validate=True)
            return _dpapi_unprotect(protected).decode("utf-8")
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise AuthStoreError("The saved encrypted cookie could not be read.") from exc

    def mark_valid(self, domains: Iterable[str]) -> None:
        self.refresh()
        changed = False
        profiles = self._data.setdefault("profiles", {})
        for domain in domains:
            key = service_domain(domain)
            record = profiles.get(key)
            if isinstance(record, dict):
                record["valid"] = True
                changed = True
        if changed:
            self._save()

    def mark_invalid(self, domains: Iterable[str]) -> None:
        self.refresh()
        changed = False
        profiles = self._data.setdefault("profiles", {})
        for domain in domains:
            key = service_domain(domain)
            record = profiles.get(key)
            if isinstance(record, dict):
                record["valid"] = False
                changed = True
        if changed:
            self._save()

    def remove(self, domain: str) -> bool:
        self.refresh()
        key = service_domain(domain)
        profiles = self._data.setdefault("profiles", {})
        record = profiles.pop(key, None)
        if not isinstance(record, dict):
            return False
        remaining_paths = {
            str(other.get(field) or "")
            for other in profiles.values()
            if isinstance(other, dict)
            for field in ("cookie_file", "secret_file")
            if str(other.get(field) or "")
        }
        for field in ("cookie_file", "secret_file"):
            path_text = str(record.get(field) or "")
            if path_text and path_text not in remaining_paths:
                try:
                    path = Path(path_text)
                    if self.root in path.resolve().parents:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        self._save()
        return True

    def clear(self) -> None:
        self.refresh()
        try:
            shutil.rmtree(self.root)
        except FileNotFoundError:
            pass
        except OSError:
            self._data = {"version": 1, "profiles": {}}
            self._save()
            return
        self._data = {"version": 1, "profiles": {}}
        self._index_signature = None

    def _set_profiles(self, domains: Iterable[str], record: dict[str, Any]) -> None:
        self.refresh()
        profiles = self._data.setdefault("profiles", {})
        changed = False
        for domain in domains:
            key = service_domain(domain)
            if not key:
                continue
            profiles[key] = dict(record)
            changed = True
        if changed:
            self._save()
