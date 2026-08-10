from __future__ import annotations

import importlib.metadata
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

try:
    import yt_dlp
except Exception:  # optional during source bootstrap
    yt_dlp = None

CONFIG_DIR = Path.home() / ".yt_dlp_liquid"
TOOLS_DIR = CONFIG_DIR / "tools"
APKEEP_PATH = TOOLS_DIR / ("apkeep.exe" if os.name == "nt" else "apkeep")


def _local_tool(pattern: str) -> str:
    if not TOOLS_DIR.exists():
        return ""
    matches = sorted(TOOLS_DIR.glob(pattern))
    return str(matches[0]) if matches else ""


class OptionalEngineError(RuntimeError):
    def __init__(self, message: str, *, output: list[str] | None = None) -> None:
        super().__init__(message)
        self.output = list(output or [])



def distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except Exception:
        return ""


def gallery_dl_executable() -> str:
    return _local_tool("gallery-dl*.exe") or shutil.which("gallery-dl") or ""


def gallery_dl_available() -> bool:
    return bool(distribution_version("gallery-dl") or gallery_dl_executable())


def spotdl_executable() -> str:
    return _local_tool("spotdl*.exe") or shutil.which("spotdl") or ""


def spotdl_available() -> bool:
    return bool(distribution_version("spotdl") or spotdl_executable())


def apkeep_executable() -> str:
    if APKEEP_PATH.exists():
        return str(APKEEP_PATH)
    return shutil.which("apkeep") or ""


def apkeep_available() -> bool:
    return bool(apkeep_executable())


def domain_for_url(url: str) -> str:
    raw = str(url or "").strip()
    if "://" not in raw:
        return ""
    try:
        return (urlparse(raw).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def is_spotify_url(url: str) -> bool:
    return domain_for_url(url) in {"open.spotify.com", "spotify.link"}


def is_reddit_url(url: str) -> bool:
    domain = domain_for_url(url)
    return domain in {"reddit.com", "old.reddit.com", "redd.it", "v.redd.it", "i.redd.it"} or domain.endswith(".reddit.com")


def is_instagram_url(url: str) -> bool:
    domain = domain_for_url(url)
    return domain in {"instagram.com", "www.instagram.com"} or domain.endswith(".instagram.com")


def app_store_source(url: str) -> str:
    domain = domain_for_url(url)
    lower = str(url or "").lower().strip()
    if domain == "play.google.com" or lower.startswith("googleplay:"):
        return "google-play"
    if domain.endswith("f-droid.org") or lower.startswith("fdroid:"):
        return "f-droid"
    if domain.endswith("apkpure.com") or lower.startswith("apkpure:"):
        return "apk-pure"
    if "appgallery.huawei.com" in domain or lower.startswith("appgallery:"):
        return "huawei-app-gallery"
    return ""


def is_app_store_url(url: str) -> bool:
    return bool(app_store_source(url))


_PACKAGE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")


def _candidate_package_id(parts: list[str]) -> str:
    for value in reversed(parts):
        value = value.strip().strip("/")
        if _PACKAGE_RE.fullmatch(value):
            return value
    return ""


def parse_package_id(url_or_id: str) -> str:
    raw = str(url_or_id or "").strip()
    if not raw:
        return ""
    if _PACKAGE_RE.fullmatch(raw):
        return raw
    for prefix in ("googleplay:", "fdroid:", "apkpure:", "appgallery:"):
        if raw.lower().startswith(prefix):
            value = raw[len(prefix):].strip().strip("/")
            return value if _PACKAGE_RE.fullmatch(value) else ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    query = parse_qs(parsed.query)
    for key in ("id", "package", "package_name", "pkg"):
        values = query.get(key) or []
        for value in values:
            if _PACKAGE_RE.fullmatch(value):
                return value
    parts = [part for part in parsed.path.split("/") if part]
    return _candidate_package_id(parts)


def _safe_command_text(command: list[str]) -> str:
    """Return a log-safe command line with secrets masked."""
    safe = list(command)
    secret_flags = {"-t", "--token", "--password", "--client-secret", "--aas-token"}
    for index, argument in enumerate(safe[:-1]):
        flag = str(argument).strip().lower()
        if flag in secret_flags:
            safe[index + 1] = "********"
        elif flag == "--proxy":
            safe[index + 1] = re.sub(
                r"(://[^/@:\s]+):([^/@\s]+)@",
                r"\1:********@",
                str(safe[index + 1]),
                count=1,
            )
    return subprocess.list2cmdline(safe)


def _stop_process(process: subprocess.Popen[str]) -> None:
    """Stop an optional-engine process, including its Windows child tree."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception:
            pass
    else:
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _run_process(
    command: list[str],
    log: Callable[[str], None],
    cancel_event: threading.Event,
    *,
    cwd: str | None = None,
) -> list[str]:
    """Run an optional engine while preserving output and polling cancellation.

    stdout is read on a daemon reader thread. The controlling thread therefore
    never blocks indefinitely in ``readline()`` and can react to Cancel even
    when spotDL/gallery-dl/apkeep are silent or waiting on the network.
    """
    log("$ " + _safe_command_text(command))
    output: list[str] = []
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except Exception as exc:
        raise OptionalEngineError(str(exc) or exc.__class__.__name__) from exc

    assert process.stdout is not None
    lines: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            for line in iter(process.stdout.readline, ""):
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, name="leon-optional-engine-output", daemon=True)
    reader.start()
    reader_finished = False
    try:
        while True:
            if cancel_event.is_set():
                _stop_process(process)
                raise OptionalEngineError("Download cancelled", output=output)
            try:
                line = lines.get(timeout=0.10)
            except queue.Empty:
                if process.poll() is not None and not reader.is_alive():
                    break
                continue
            if line is None:
                reader_finished = True
                if process.poll() is not None:
                    break
                continue
            clean = line.rstrip()
            if clean:
                output.append(clean)
                if len(output) > 240:
                    del output[:40]
                log(clean)

        # Drain any final lines already queued after process exit.
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            try:
                line = lines.get_nowait()
            except queue.Empty:
                break
            if line is None:
                reader_finished = True
                continue
            clean = line.rstrip()
            if clean:
                output.append(clean)
                log(clean)
        code = process.wait(timeout=2.0)
    finally:
        if process.poll() is None:
            _stop_process(process)
        if not reader_finished:
            reader.join(timeout=0.25)

    if code != 0:
        detail = next(
            (line for line in reversed(output) if line and not line.startswith(("+---", "| ", "+---"))),
            "",
        )
        message = f"Optional engine exited with code {code}."
        if detail and detail.lower() not in {"an error occurred", "error"}:
            message += f" {detail}"
        raise OptionalEngineError(message, output=output)
    return output


def gallery_dl_command(
    url: str,
    output_dir: str,
    *,
    cookiefile: str = "",
    browser: str = "",
    browser_profile: str = "",
) -> list[str]:
    executable = gallery_dl_executable()
    command = [executable] if executable else [sys.executable, "-m", "gallery_dl"]
    command += ["--destination", output_dir, "--windows-filenames"]
    if cookiefile:
        command += ["--cookies", cookiefile]
    elif browser:
        source = browser.lower()
        if browser_profile:
            source += ":" + browser_profile
        command += ["--cookies-from-browser", source]
    command.append(url)
    return command


def run_gallery_dl(
    url: str,
    output_dir: str,
    log: Callable[[str], None],
    cancel_event: threading.Event,
    *,
    cookiefile: str = "",
    browser: str = "",
    browser_profile: str = "",
) -> None:
    if not gallery_dl_available():
        raise OptionalEngineError("gallery-dl is not installed. Install it from Package Manager.")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    _run_process(
        gallery_dl_command(
            url,
            output_dir,
            cookiefile=cookiefile,
            browser=browser,
            browser_profile=browser_profile,
        ),
        log,
        cancel_event,
    )


def _is_spotify_track_url(url: str) -> bool:
    try:
        parts = [part for part in urlparse(url).path.split("/") if part]
    except Exception:
        return False
    return len(parts) >= 2 and parts[0].lower() == "track"


def _spotify_oembed(url: str, proxy: str = "") -> dict[str, object]:
    endpoint = "https://open.spotify.com/oembed?" + urlencode({"url": url})
    request = Request(
        endpoint,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36",
            "Accept": "application/json",
        },
    )
    if proxy:
        opener = build_opener(ProxyHandler({"http": proxy, "https": proxy}))
        response_context = opener.open(request, timeout=25)
    else:
        response_context = urlopen(request, timeout=25)
    with response_context as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def spotify_preview_metadata(url: str, proxy: str = "") -> dict[str, object]:
    """Return lightweight public Spotify metadata for previews and queue labels."""
    return _spotify_oembed(url, proxy)


def _spotify_track_fallback(
    url: str,
    output_dir: str,
    log: Callable[[str], None],
    cancel_event: threading.Event,
    *,
    output_format: str,
    cookiefile: str = "",
    proxy: str = "",
) -> None:
    """Best-effort single-track fallback using Spotify oEmbed and yt-dlp search."""
    try:
        metadata = _spotify_oembed(url, proxy)
        title = str(metadata.get("title") or "").strip()
    except Exception as exc:
        raise OptionalEngineError(
            "Spotify metadata could not be read through either spotDL or the public oEmbed endpoint."
        ) from exc
    if not title:
        raise OptionalEngineError("Spotify oEmbed did not return a track title.")

    log("spotDL could not reach its default Spotify metadata service.")
    log("Trying the official Spotify oEmbed title with a YouTube audio search fallback.")
    log("Fallback matching is best-effort and is available only for individual Spotify tracks.")

    if yt_dlp is None:
        raise OptionalEngineError("yt-dlp is unavailable for the Spotify fallback.")

    class _FallbackLogger:
        def debug(self, message: str) -> None:
            if message and not str(message).startswith("[debug]"):
                log(str(message))

        info = debug
        warning = debug

        def error(self, message: str) -> None:
            if message:
                log(str(message))

    def _progress_hook(data: dict[str, object]) -> None:
        if cancel_event.is_set():
            raise OptionalEngineError("Download cancelled")
        status = str(data.get("status") or "")
        if status == "downloading":
            percent = str(data.get("_percent_str") or "").strip()
            speed = str(data.get("_speed_str") or "").strip()
            eta = str(data.get("_eta_str") or "").strip()
            summary = " ".join(part for part in (percent, speed, eta) if part)
            if summary:
                log(summary)

    template = str(Path(output_dir) / "%(artist,channel,uploader)s - %(title)s.%(ext)s")
    query = f"ytsearch1:{title} official audio"
    ydl_options: dict[str, object] = {
        "format": "bestaudio/best",
        "outtmpl": template,
        "noplaylist": True,
        "windowsfilenames": os.name == "nt",
        "continuedl": True,
        "retries": 5,
        "fragment_retries": 5,
        "writethumbnail": True,
        "logger": _FallbackLogger(),
        "progress_hooks": [_progress_hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": output_format, "preferredquality": "0"},
            {"key": "FFmpegMetadata"},
            {"key": "EmbedThumbnail"},
        ],
    }
    if cookiefile:
        ydl_options["cookiefile"] = cookiefile
    if proxy:
        ydl_options["proxy"] = proxy
    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            code = ydl.download([query])
        if code:
            raise OptionalEngineError(f"Spotify fallback exited with code {code}.")
    except OptionalEngineError:
        raise
    except Exception as exc:
        raise OptionalEngineError(str(exc) or exc.__class__.__name__) from exc


def _looks_like_spotify_metadata_failure(lines: list[str]) -> bool:
    joined = "\n".join(lines).lower()
    markers = (
        "spotifyfree",
        "spotipyfree",
        "spotapi",
        "requesterror: failed to complete request",
        "could not get session",
        "could not get playlist hashes",
    )
    return any(marker in joined for marker in markers)


def _looks_like_youtube_music_connection_failure(lines: list[str]) -> bool:
    """Detect the startup probe failure emitted when music.youtube.com is unreachable."""
    joined = "\n".join(lines).lower()
    if "music.youtube.com" not in joined:
        return False
    markers = (
        "connecttimeout",
        "connecttimeouterror",
        "connection to music.youtube.com timed out",
        "max retries exceeded",
        "winerror 10060",
        "check_ytmusic_connection",
    )
    return any(marker in joined for marker in markers)


def run_spotdl(
    url: str,
    output_dir: str,
    log: Callable[[str], None],
    cancel_event: threading.Event,
    *,
    output_format: str = "mp3",
    cookiefile: str = "",
    spotify_client_id: str = "",
    spotify_client_secret: str = "",
    use_official_api: bool = False,
    proxy: str = "",
) -> None:
    if not spotdl_available():
        raise OptionalEngineError("spotDL is not installed. Install it from Package Manager.")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    executable = spotdl_executable()
    command = [executable] if executable else [sys.executable, "-m", "spotdl"]
    template = str(Path(output_dir) / "{artists} - {title}.{output-ext}")
    command += [
        "download", url,
        "--output", template,
        "--format", output_format,
        "--simple-tui",
        "--print-errors",
        "--max-retries", "3",
    ]
    if cookiefile:
        command += ["--cookie-file", cookiefile]
    if proxy:
        command += ["--proxy", proxy]
    official_ready = bool(use_official_api and spotify_client_id and spotify_client_secret)
    if use_official_api and not official_ready:
        raise OptionalEngineError(
            "Official Spotify API mode is enabled, but the Client ID or Client Secret is empty. "
            "Enter both values in Packages & Tools."
        )
    if official_ready:
        command += [
            "--use-official-api",
            "--client-id", spotify_client_id,
            "--client-secret", spotify_client_secret,
            "--no-cache",
        ]
        log("Using the official Spotify Web API for metadata.")

    try:
        _run_process(command, log, cancel_event)
    except OptionalEngineError as exc:
        if _looks_like_youtube_music_connection_failure(exc.output):
            log(
                "YouTube Music is unreachable. Retrying spotDL with the standard YouTube audio provider."
            )
            retry_command = [*command, "--audio", "youtube"]
            try:
                _run_process(retry_command, log, cancel_event)
                return
            except OptionalEngineError as retry_exc:
                combined_output = [
                    *exc.output,
                    "--- Leon retry with --audio youtube ---",
                    *retry_exc.output,
                ]
                if not official_ready and _is_spotify_track_url(url):
                    log(
                        "The standard YouTube provider also failed. Trying Leon's single-track search fallback."
                    )
                    try:
                        _spotify_track_fallback(
                            url, output_dir, log, cancel_event,
                            output_format=output_format, cookiefile=cookiefile, proxy=proxy,
                        )
                        return
                    except OptionalEngineError as fallback_exc:
                        combined_output.extend([
                            "--- Leon single-track fallback ---",
                            *fallback_exc.output,
                        ])
                raise OptionalEngineError(
                    "spotDL could not reach music.youtube.com, and its standard YouTube retry also failed. "
                    "Enter a working HTTP(S) proxy in Packages & Tools if YouTube is restricted on your network, "
                    "then retry. The proxy is applied to spotDL and Leon's single-track fallback.",
                    output=combined_output,
                ) from retry_exc
        if (
            not official_ready
            and _is_spotify_track_url(url)
            and _looks_like_spotify_metadata_failure(exc.output)
        ):
            _spotify_track_fallback(
                url, output_dir, log, cancel_event,
                output_format=output_format, cookiefile=cookiefile, proxy=proxy,
            )
            return
        if _looks_like_spotify_metadata_failure(exc.output):
            raise OptionalEngineError(
                "spotDL could not reach Spotify's default metadata service. "
                "Update spotDL, configure a proxy if Spotify is blocked on your network, "
                "or enable the official Spotify API and enter a Client ID and Client Secret in Packages & Tools.",
                output=exc.output,
            ) from exc
        raise


def _resolve_package_id_from_page(url: str) -> str:
    """Best-effort extraction for store pages that expose only an internal app ID."""
    if "://" not in str(url or ""):
        return ""
    try:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/136 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urlopen(request, timeout=20) as response:
            body = response.read(2 * 1024 * 1024).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    patterns = (
        r'"packageName"\s*:\s*"([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)"',
        r'"pkgName"\s*:\s*"([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)"',
        r'packageName=([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)',
        r"package-name[\"'=:\s]+([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)",
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def run_apkeep(
    url_or_id: str,
    output_dir: str,
    log: Callable[[str], None],
    cancel_event: threading.Event,
    *,
    source: str = "",
    google_email: str = "",
    google_aas_token: str = "",
) -> None:
    executable = apkeep_executable()
    if not executable:
        raise OptionalEngineError("apkeep is not installed. Install it from Package Manager.")
    source = source or app_store_source(url_or_id) or "apk-pure"
    package_id = parse_package_id(url_or_id)
    if not package_id and source == "huawei-app-gallery":
        package_id = _resolve_package_id_from_page(url_or_id)
    if not package_id:
        raise OptionalEngineError(
            "Could not determine the Android package ID. Paste a store URL containing the package name or use a prefix such as fdroid:org.example.app. AppGallery links that expose only a C-number may require the explicit appgallery:package.name form."
        )
    if source == "google-play" and (not google_email or not google_aas_token):
        raise OptionalEngineError(
            "Google Play requires an account email and AAS token. Enter them in Package Manager before downloading."
        )
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    command = [executable, "-a", package_id, "-d", source]
    if source == "google-play":
        command += ["-e", google_email, "-t", google_aas_token]
    command.append(output_dir)
    _run_process(command, log, cancel_event)
