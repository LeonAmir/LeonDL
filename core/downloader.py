from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.workers import Worker, Signal

from core.optional_engines import (
    OptionalEngineError,
    app_store_source,
    gallery_dl_available,
    is_app_store_url,
    is_instagram_url,
    is_reddit_url,
    is_spotify_url,
    run_apkeep,
    run_gallery_dl,
    run_spotdl,
    spotify_preview_metadata,
)

try:
    import yt_dlp
except ImportError:  # handled in the UI with a friendly message
    yt_dlp = None


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


class DownloadCancelled(Exception):
    """Raised from a yt-dlp hook when the user cancels the active job."""


class InvalidCookieText(ValueError):
    """Raised when pasted cookie data cannot be converted to a cookie file."""


@dataclass(frozen=True)
class DownloadPreset:
    key: str
    label_fa: str
    label_en: str
    format_selector: str
    merge_output_format: str | None = None
    audio_codec: str | None = None
    format_sort: tuple[str, ...] = ()

    def label(self, language: str = "fa") -> str:
        return self.label_en if language == "en" else self.label_fa


def _quality_preset(key: str, label_fa: str, label_en: str, height: int) -> DownloadPreset:
    # Prefer MP4/M4A when available, then fall back to any compatible stream at
    # or below the selected resolution. The selector never intentionally picks
    # a resolution above the user's cap.
    selector = (
        f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
        f"b[height<={height}][ext=mp4]/"
        f"bv*[height<={height}]+ba/b[height<={height}]/ba"
    )
    return DownloadPreset(
        key,
        label_fa,
        label_en,
        selector,
        format_sort=(f"res:{height}", "vext:mp4", "aext:m4a"),
    )


PRESETS: dict[str, DownloadPreset] = {
    "auto": DownloadPreset(
        "auto",
        "انتخاب خودکار (پیشنهادی)",
        "Automatic (recommended)",
        "bv*+ba/b",
    ),
    "best": DownloadPreset("best", "بهترین کیفیت", "Best quality", "bv*+ba/b"),
    "mp4_best": DownloadPreset(
        "mp4_best",
        "MP4 با بهترین کیفیت",
        "Best quality MP4",
        "bv*+ba/b",
        merge_output_format="mp4",
        format_sort=("vext:mp4", "aext:m4a"),
    ),
    "video_4320": _quality_preset("video_4320", "ویدئو تا 4320p (8K)", "Video up to 4320p (8K)", 4320),
    "video_2160": _quality_preset("video_2160", "ویدئو تا 2160p (4K)", "Video up to 2160p (4K)", 2160),
    "video_1440": _quality_preset("video_1440", "ویدئو تا 1440p (2K)", "Video up to 1440p (2K)", 1440),
    "video_1080": _quality_preset("video_1080", "ویدئو تا 1080p", "Video up to 1080p", 1080),
    "video_720": _quality_preset("video_720", "ویدئو تا 720p", "Video up to 720p", 720),
    "video_480": _quality_preset("video_480", "ویدئو تا 480p", "Video up to 480p", 480),
    "video_360": _quality_preset("video_360", "ویدئو تا 360p", "Video up to 360p", 360),
    "video_240": _quality_preset("video_240", "ویدئو تا 240p", "Video up to 240p", 240),
    "video_144": _quality_preset("video_144", "ویدئو تا 144p", "Video up to 144p", 144),
    "audio_mp3": DownloadPreset("audio_mp3", "صدا MP3", "MP3 audio", "bestaudio/best", audio_codec="mp3"),
    "audio_m4a": DownloadPreset(
        "audio_m4a",
        "صدا M4A",
        "M4A audio",
        "bestaudio/best",
        audio_codec="m4a",
        format_sort=("aext:m4a",),
    ),
    "audio_original": DownloadPreset(
        "audio_original",
        "صدای اصلی بدون تبدیل",
        "Original audio without conversion",
        "bestaudio/best",
    ),
}

BROWSERS: dict[str, str | None] = {
    "Chrome": "chrome",
    "Firefox": "firefox",
    "Edge": "edge",
    "Brave": "brave",
    "Chromium": "chromium",
    "Opera": "opera",
    "Vivaldi": "vivaldi",
    "Safari": "safari",
}

AUTH_SOURCES = (
    "بدون کوکی",
    "خواندن از مرورگر",
    "انتخاب فایل cookies.txt",
    "ورود دستی اطلاعات کوکی",
)

JS_RUNTIME_CHOICES: dict[str, str] = {
    "خودکار (Deno پیشنهادی)": "auto",
    "Deno": "deno",
    "Node.js": "node",
    "QuickJS": "quickjs",
}

JS_RUNTIME_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "deno": ("deno.exe", "deno"),
    "node": ("node.exe", "node"),
    "quickjs": ("qjs.exe", "qjs", "quickjs.exe", "quickjs"),
}

JS_RUNTIME_ORDER = ("deno", "node", "quickjs")


MIN_PORNHUB_YTDLP_VERSION = (2026, 6, 9)


def _numeric_version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:4])


def installed_yt_dlp_version() -> str:
    try:
        from yt_dlp.version import __version__
        return str(__version__)
    except ImportError:
        return ""


def browser_impersonation_available() -> bool:
    return importlib.util.find_spec("curl_cffi") is not None


def pornhub_support_ready() -> tuple[bool, str]:
    version = installed_yt_dlp_version()
    version_ok = bool(version) and _numeric_version(version) >= MIN_PORNHUB_YTDLP_VERSION
    impersonation_ok = browser_impersonation_available()
    details = f"yt-dlp {version or 'unknown'}; curl_cffi={'yes' if impersonation_ok else 'no'}"
    return version_ok and impersonation_ok, details


AUDIO_LANGUAGE_NAMES: dict[str, tuple[str, str]] = {
    "fa": ("فارسی", "Persian"),
    "en": ("انگلیسی", "English"),
    "ar": ("عربی", "Arabic"),
    "de": ("آلمانی", "German"),
    "es": ("اسپانیایی", "Spanish"),
    "fr": ("فرانسوی", "French"),
    "it": ("ایتالیایی", "Italian"),
    "pt": ("پرتغالی", "Portuguese"),
    "ru": ("روسی", "Russian"),
    "tr": ("ترکی", "Turkish"),
    "hi": ("هندی", "Hindi"),
    "ur": ("اردو", "Urdu"),
    "ja": ("ژاپنی", "Japanese"),
    "ko": ("کره‌ای", "Korean"),
    "zh": ("چینی", "Chinese"),
    "id": ("اندونزیایی", "Indonesian"),
    "nl": ("هلندی", "Dutch"),
    "pl": ("لهستانی", "Polish"),
    "uk": ("اوکراینی", "Ukrainian"),
}


def audio_language_name(code: str, language: str = "fa") -> str:
    normalized = str(code or "").strip()
    if not normalized:
        return ""
    base = re.split(r"[-_]", normalized, maxsplit=1)[0].lower()
    names = AUDIO_LANGUAGE_NAMES.get(base)
    if not names:
        return normalized
    name = names[1] if language == "en" else names[0]
    return f"{name} ({normalized})"


def extract_audio_languages(info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return unique audio-track languages exposed by an extractor.

    yt-dlp places the track language on individual formats. Some services only
    expose a top-level language, so that is included as a fallback.
    """
    data = info or {}
    collected: dict[str, dict[str, Any]] = {}

    formats = data.get("formats") or []
    for fmt in formats:
        if not isinstance(fmt, dict):
            continue
        acodec = str(fmt.get("acodec") or "none").lower()
        if acodec == "none":
            continue
        code = str(fmt.get("language") or "").strip()
        if not code:
            continue
        key = code.lower()
        try:
            preference = float(fmt.get("language_preference"))
        except (TypeError, ValueError):
            preference = -1000.0
        note = clean_message(fmt.get("format_note") or fmt.get("format") or "")
        current = collected.get(key)
        if current is None or preference > float(current.get("preference", -1000.0)):
            collected[key] = {
                "code": code,
                "note": note,
                "preference": preference,
                "is_default": preference >= 0 or any(
                    marker in note.lower()
                    for marker in ("original", "default", "اصلی", "پیش‌فرض")
                ),
            }

    top_level = str(data.get("language") or "").strip()
    if top_level and top_level.lower() not in collected:
        collected[top_level.lower()] = {
            "code": top_level,
            "note": "",
            "preference": -999.0,
            "is_default": True,
        }

    return sorted(
        collected.values(),
        key=lambda item: (not bool(item.get("is_default")), -float(item.get("preference", -1000.0)), str(item.get("code"))),
    )


def subtitle_language_name(code: str, language: str = "fa") -> str:
    """Return a localized display name for a subtitle language tag."""
    return audio_language_name(code, language)


def extract_subtitle_languages(info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return subtitle languages exposed by the extractor.

    Manual subtitles and automatic captions are kept as separate availability
    flags so the UI can tell the user exactly what each link offers.
    """
    data = info or {}
    collected: dict[str, dict[str, Any]] = {}

    def collect(mapping: Any, source: str) -> None:
        if not isinstance(mapping, dict):
            return
        for raw_code, raw_formats in mapping.items():
            code = str(raw_code or "").strip()
            if not code or code.lower() in {"live_chat", "comments"}:
                continue
            formats = raw_formats if isinstance(raw_formats, list) else []
            # Some extractors expose the language key before filling format
            # details. The key itself is still useful availability metadata.
            extensions = sorted({
                str(item.get("ext") or "").strip().lower()
                for item in formats
                if isinstance(item, dict) and str(item.get("ext") or "").strip()
            })
            key = code.lower()
            entry = collected.setdefault(
                key,
                {
                    "code": code,
                    "manual": False,
                    "automatic": False,
                    "manual_formats": [],
                    "automatic_formats": [],
                },
            )
            entry[source] = True
            entry[f"{source}_formats"] = extensions

    collect(data.get("subtitles"), "manual")
    collect(data.get("automatic_captions"), "automatic")

    return sorted(
        collected.values(),
        key=lambda item: (
            not bool(item.get("manual")),
            not bool(item.get("automatic")),
            str(item.get("code") or "").lower(),
        ),
    )


def _language_filter_selector(selector: str, audio_language: str) -> str:
    """Prefer one audio language while preserving the original fallback.

    Any extractor-provided field can be used in a format filter. We add an
    exact language filter to audio-only selectors and combined-format fallbacks,
    then append the original selector so unsupported services still download.
    """
    code = str(audio_language or "").strip()
    if not selector or not code or code.lower() in {"auto", "default", "original"}:
        return selector
    # Language tags returned by extractors are conservative (e.g. en, en-US).
    # Remove characters that could break yt-dlp's selector grammar.
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", code)
    if not safe:
        return selector

    def add_filter(match: re.Match[str]) -> str:
        token = match.group(1)
        return f"{token}[language={safe}]"

    language_specific = re.sub(
        r"(?<![A-Za-z0-9_])(bestaudio|ba|best|b)(?=(?:\[|/|\+|$))",
        add_filter,
        selector,
    )
    if language_specific == selector:
        return selector
    return f"{language_specific}/{selector}"


SERVICE_NAME_BY_DOMAIN: dict[str, str] = {
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "instagram.com": "Instagram",
    "tiktok.com": "TikTok",
    "twitter.com": "X / Twitter",
    "x.com": "X",
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "vimeo.com": "Vimeo",
    "twitch.tv": "Twitch",
    "soundcloud.com": "SoundCloud",
    "reddit.com": "Reddit",
    "pinterest.com": "Pinterest",
    "dailymotion.com": "Dailymotion",
    "bilibili.com": "Bilibili",
    "bandcamp.com": "Bandcamp",
    "mixcloud.com": "Mixcloud",
    "pornhub.com": "PornHub",
    "pornhub.net": "PornHub",
    "pornhub.org": "PornHub",
    "pornhubpremium.com": "PornHub Premium",
}


def url_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").strip().lower().rstrip(".")
    except ValueError:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def service_identity(info: dict[str, Any] | None = None, fallback_url: str = "") -> dict[str, str]:
    data = info or {}
    domain = str(data.get("webpage_url_domain") or "").strip().lower().rstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        domain = url_domain(str(data.get("webpage_url") or data.get("original_url") or fallback_url))

    extractor_key = str(data.get("extractor_key") or "").strip()
    extractor = str(data.get("extractor") or "").strip()
    display = ""
    for known_domain, known_name in SERVICE_NAME_BY_DOMAIN.items():
        if domain == known_domain or domain.endswith("." + known_domain):
            display = known_name
            break
    if not display and extractor_key and extractor_key.lower() not in {"generic", "unsupported"}:
        display = re.sub(r"(?<!^)(?=[A-Z])", " ", extractor_key).replace(" Ie", "").strip()
    if not display:
        display = domain or extractor_key or extractor or "Other"
    return {
        "service": display,
        "domain": domain,
        "extractor_key": extractor_key,
        "extractor": extractor,
    }


def normalize_cookie_domain(value: str, fallback_url: str = "") -> str:
    domain = value.strip() or url_domain(fallback_url)
    domain = domain.removeprefix("https://").removeprefix("http://").split("/", 1)[0].strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        domain = "example.com"
    return domain if domain.startswith(".") else "." + domain


def _runtime_candidate_paths(runtime: str) -> list[Path]:
    names = JS_RUNTIME_EXECUTABLES.get(runtime, ())
    candidates: list[Path] = []
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    # GUI apps launched before installation may not inherit the refreshed PATH.
    # Check common Windows locations and the application folder explicitly.
    roots = [Path.cwd(), Path(sys.executable).resolve().parent, Path(__file__).resolve().parents[1]]
    if os.name == "nt":
        home = Path.home()
        local_app_data = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roots.extend([
            home / ".deno" / "bin",
            local_app_data / "Microsoft" / "WinGet" / "Links",
            local_app_data / "Programs" / "Deno",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Deno",
        ])
    for root in roots:
        for name in names:
            candidate = root / name
            if candidate.is_file():
                candidates.append(candidate)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()).lower() if candidate.exists() else str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _runtime_version(path: Path) -> str:
    try:
        result = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = clean_message((result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else "")
    return output


def resolve_javascript_runtime(
    selected: str = "auto",
    custom_path: str = "",
) -> dict[str, str] | None:
    selected = selected if selected in {*JS_RUNTIME_ORDER, "auto"} else "auto"
    custom = Path(custom_path).expanduser() if custom_path.strip() else None

    if custom:
        if custom.is_dir():
            names = JS_RUNTIME_EXECUTABLES.get(selected if selected != "auto" else "deno", ())
            custom = next((custom / name for name in names if (custom / name).is_file()), custom)
        if custom.is_file():
            runtime = selected
            if runtime == "auto":
                lowered = custom.name.lower()
                runtime = "node" if "node" in lowered else "quickjs" if "qjs" in lowered or "quickjs" in lowered else "deno"
            version = _runtime_version(custom)
            if version:
                return {"name": runtime, "path": str(custom.resolve()), "version": version}

    order = JS_RUNTIME_ORDER if selected == "auto" else (selected,)
    for runtime in order:
        for path in _runtime_candidate_paths(runtime):
            version = _runtime_version(path)
            if version:
                return {"name": runtime, "path": str(path.resolve()), "version": version}
    return None


def ejs_package_available() -> bool:
    return importlib.util.find_spec("yt_dlp_ejs") is not None


def javascript_runtime_options(
    selected: str = "auto",
    custom_path: str = "",
    *,
    require_runtime: bool = False,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    runtime = resolve_javascript_runtime(selected, custom_path)
    if not runtime:
        if require_runtime:
            raise RuntimeError(
                "موتور JavaScript سازگار پیدا نشد. Deno را نصب کنید یا مسیر deno.exe را در برنامه انتخاب کنید."
            )
        return {}, None

    options: dict[str, Any] = {
        "js_runtimes": {runtime["name"]: {"path": runtime["path"]}},
    }
    # The requirements file installs yt-dlp-ejs. If it is missing for any reason,
    # use yt-dlp's official remote component fallback instead of silently failing.
    if not ejs_package_available():
        options["remote_components"] = {"ejs:github"}
    return options, runtime


def clean_message(message: object) -> str:
    return ANSI_ESCAPE_RE.sub("", str(message)).strip()


def human_bytes(value: float | int | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if abs(size) < 1024.0 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def human_seconds(value: float | int | None) -> str:
    if value is None:
        return "—"
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


SIZE_CONFIDENCE_ORDER = {
    "exact": 0,
    "approximate": 1,
    "estimated": 2,
    "unknown": 3,
}


VIDEO_CODECS = {
    "h264": ("H.264 (AVC)", r"^(avc[13]|h264)(\.|$)"),
    "hevc": ("H.265 (HEVC)", r"^(hevc|h265|hev1|hvc1)(\.|$)"),
    "vp9": ("VP9", r"^(vp9|vp09)(\.|$)"),
    "av1": ("AV1", r"^(av1|av01)(\.|$)"),
    "vp8": ("VP8", r"^(vp8|vp08)(\.|$)"),
    "mpeg4": ("MPEG-4", r"^(mp4v|mpeg4)(\.|$)"),
}


def available_video_codecs(info: dict[str, Any]) -> list[str]:
    formats = compact_media_formats(info)
    return [key for key, (_, pattern) in VIDEO_CODECS.items()
            if any(re.search(pattern, str(fmt.get("vcodec") or ""), re.IGNORECASE) for fmt in formats)]


def _codec_selector(selector: str, codec: str) -> str:
    pattern = VIDEO_CODECS[codec][1]
    # Drop audio-only fallback branches and constrain every video candidate.
    video = re.compile(r"^(?:bv\*?|bestvideo\*?|b|best)(?=\[|\+|$)")
    return "/".join(video.sub(lambda match: f"{match[0]}[vcodec~='{pattern}']", branch)
                    for branch in selector.split("/") if video.match(branch))


def compact_media_formats(info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keep only format fields needed for offline size recalculation in the UI."""
    fields = (
        "format_id", "format", "format_note", "ext", "protocol",
        "vcodec", "acodec", "width", "height", "fps", "quality",
        "tbr", "vbr", "abr", "filesize", "filesize_approx",
        "language", "language_preference", "preference", "source_preference",
    )
    compact: list[dict[str, Any]] = []
    for raw in (info or {}).get("formats") or []:
        if not isinstance(raw, dict):
            continue
        item = {key: raw.get(key) for key in fields if raw.get(key) is not None}
        vcodec = str(item.get("vcodec") or "none").lower()
        acodec = str(item.get("acodec") or "none").lower()
        if vcodec == "none" and acodec == "none":
            continue
        compact.append(item)
    return compact


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_size_estimate(fmt: dict[str, Any], duration: float | int | None) -> tuple[int | None, str]:
    exact = _number(fmt.get("filesize"))
    if exact > 0:
        return int(exact), "exact"
    approximate = _number(fmt.get("filesize_approx"))
    if approximate > 0:
        return int(approximate), "approximate"
    seconds = _number(duration)
    bitrate = _number(fmt.get("tbr"))
    if bitrate <= 0:
        bitrate = _number(fmt.get("vbr")) + _number(fmt.get("abr"))
    if seconds > 0 and bitrate > 0:
        # tbr/vbr/abr are expressed in kilobits per second by yt-dlp.
        return int(seconds * bitrate * 1000 / 8), "estimated"
    return None, "unknown"


def _language_matches(fmt: dict[str, Any], requested: str) -> bool:
    requested = str(requested or "").strip().lower()
    if not requested:
        return False
    actual = str(fmt.get("language") or "").strip().lower()
    if not actual:
        return False
    return actual == requested or actual.split("-", 1)[0] == requested.split("-", 1)[0]


def _audio_score(fmt: dict[str, Any], requested_language: str, prefer_m4a: bool = False) -> tuple[float, ...]:
    ext = str(fmt.get("ext") or "").lower()
    return (
        1.0 if _language_matches(fmt, requested_language) else 0.0,
        _number(fmt.get("language_preference"), -1000.0),
        1.0 if prefer_m4a and ext in {"m4a", "mp4"} else 0.0,
        _number(fmt.get("abr")),
        _number(fmt.get("tbr")),
        _number(fmt.get("quality"), -1.0),
        _number(fmt.get("preference"), -1000.0),
        _number(fmt.get("filesize")) or _number(fmt.get("filesize_approx")),
    )


def _video_score(fmt: dict[str, Any], prefer_mp4: bool = False) -> tuple[float, ...]:
    ext = str(fmt.get("ext") or "").lower()
    return (
        _number(fmt.get("height")),
        _number(fmt.get("width")),
        _number(fmt.get("fps")),
        1.0 if prefer_mp4 and ext == "mp4" else 0.0,
        _number(fmt.get("tbr")),
        _number(fmt.get("quality"), -1.0),
        _number(fmt.get("preference"), -1000.0),
        _number(fmt.get("filesize")) or _number(fmt.get("filesize_approx")),
    )


def _preset_height_cap(preset_key: str) -> int | None:
    match = re.fullmatch(r"video_(\d+)", str(preset_key or ""))
    return int(match.group(1)) if match else None


def estimate_selected_media_size(
    info: dict[str, Any] | None,
    preset_key: str = "auto",
    audio_language: str = "",
) -> dict[str, Any]:
    """Estimate bytes downloaded for the current preset without network access.

    The result is intentionally conservative. It uses exact sizes first,
    extractor approximations second, and duration × bitrate only as a final
    fallback. The final container can differ slightly after FFmpeg processing.
    """
    data = info or {}
    formats = [dict(item) for item in data.get("formats") or [] if isinstance(item, dict)]
    duration = data.get("duration")
    if not formats:
        return {"bytes": None, "confidence": "unknown", "components": [], "selected_ids": []}

    def has_video(fmt: dict[str, Any]) -> bool:
        return str(fmt.get("vcodec") or "none").lower() != "none"

    def has_audio(fmt: dict[str, Any]) -> bool:
        return str(fmt.get("acodec") or "none").lower() != "none"

    cap = _preset_height_cap(preset_key)
    audio_only_mode = preset_key.startswith("audio_")
    prefer_mp4 = preset_key == "mp4_best" or cap is not None
    prefer_m4a = preset_key == "audio_m4a" or prefer_mp4

    audio_formats = [fmt for fmt in formats if has_audio(fmt) and not has_video(fmt)]
    combined_formats = [fmt for fmt in formats if has_audio(fmt) and has_video(fmt)]
    video_only_formats = [fmt for fmt in formats if has_video(fmt) and not has_audio(fmt)]

    if cap is not None:
        video_only_formats = [fmt for fmt in video_only_formats if not fmt.get("height") or _number(fmt.get("height")) <= cap]
        combined_formats = [fmt for fmt in combined_formats if not fmt.get("height") or _number(fmt.get("height")) <= cap]

    def choose_audio(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not candidates:
            return None
        language_matches = [fmt for fmt in candidates if _language_matches(fmt, audio_language)]
        pool = language_matches or candidates
        return max(pool, key=lambda fmt: _audio_score(fmt, audio_language, prefer_m4a))

    selected: list[dict[str, Any]] = []
    if audio_only_mode:
        audio = choose_audio(audio_formats)
        if audio is None:
            audio = choose_audio(combined_formats)
        if audio is not None:
            selected = [audio]
    else:
        video = max(video_only_formats, key=lambda fmt: _video_score(fmt, prefer_mp4), default=None)
        audio = choose_audio(audio_formats)
        if video is not None and audio is not None:
            selected = [video, audio]
        else:
            combined = max(combined_formats, key=lambda fmt: _video_score(fmt, prefer_mp4), default=None)
            if combined is not None:
                selected = [combined]
            elif video is not None:
                selected = [video]
            elif audio is not None:
                selected = [audio]

    if not selected:
        return {"bytes": None, "confidence": "unknown", "components": [], "selected_ids": []}

    total = 0
    confidences: list[str] = []
    components: list[dict[str, Any]] = []
    for fmt in selected:
        size, confidence = _format_size_estimate(fmt, duration)
        component_type = "video" if has_video(fmt) and not has_audio(fmt) else "audio" if has_audio(fmt) and not has_video(fmt) else "combined"
        components.append({
            "type": component_type,
            "bytes": size,
            "confidence": confidence,
            "format_id": str(fmt.get("format_id") or ""),
            "height": fmt.get("height"),
            "language": fmt.get("language"),
            "ext": fmt.get("ext"),
        })
        if size is None:
            return {
                "bytes": None,
                "confidence": "unknown",
                "components": components,
                "selected_ids": [str(item.get("format_id") or "") for item in selected],
            }
        total += size
        confidences.append(confidence)

    confidence = max(confidences, key=lambda item: SIZE_CONFIDENCE_ORDER.get(item, 3)) if confidences else "unknown"
    return {
        "bytes": total,
        "confidence": confidence,
        "components": components,
        "selected_ids": [str(item.get("format_id") or "") for item in selected],
    }


def _netscape_line(
    domain: str,
    path: str,
    secure: bool,
    expires: int,
    name: str,
    value: str,
    *,
    http_only: bool = False,
) -> str:
    domain = normalize_cookie_domain(domain)
    include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
    domain_field = f"#HttpOnly_{domain}" if http_only else domain
    return "\t".join(
        (
            domain_field,
            include_subdomains,
            path or "/",
            "TRUE" if secure else "FALSE",
            str(max(0, int(expires or 0))),
            name,
            value,
        )
    )


def cookie_text_to_netscape(raw_text: str, default_domain: str = "") -> str:
    """Accept Netscape, JSON-export, or a raw Cookie header and return Netscape text."""
    text = raw_text.strip().lstrip("\ufeff")
    if not text:
        raise InvalidCookieText("کادر اطلاعات کوکی خالی است.")

    # Native Netscape cookies.txt content.
    if "# Netscape HTTP Cookie File" in text or "# HTTP Cookie File" in text:
        lines = [line.rstrip() for line in text.splitlines() if line.strip()]
        data_lines = [line for line in lines if not line.startswith("#") or line.startswith("#HttpOnly_")]
        if not any(len(line.split("\t")) >= 7 for line in data_lines):
            raise InvalidCookieText("محتوای cookies.txt معتبر نیست یا ستون‌های لازم را ندارد.")
        if not lines[0].startswith("#"):
            lines.insert(0, "# Netscape HTTP Cookie File")
        return "\n".join(lines) + "\n"

    # JSON exported by common browser cookie extensions.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if parsed is not None:
        if isinstance(parsed, dict):
            parsed = parsed.get("cookies", parsed.get("data", parsed))
        if not isinstance(parsed, list):
            raise InvalidCookieText("ساختار JSON کوکی باید یک فهرست از کوکی‌ها باشد.")
        lines = ["# Netscape HTTP Cookie File"]
        for item in parsed:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            value = str(item.get("value") or "")
            domain = str(item.get("domain") or item.get("host") or default_domain or "example.com")
            path = str(item.get("path") or "/")
            secure = bool(item.get("secure", True))
            expiry_raw = (
                item.get("expirationDate")
                or item.get("expires")
                or item.get("expiration")
                or item.get("expiry")
                or 0
            )
            try:
                expires = int(float(expiry_raw))
            except (TypeError, ValueError):
                expires = 0
            lines.append(
                _netscape_line(
                    domain,
                    path,
                    secure,
                    expires,
                    name,
                    value,
                    http_only=bool(item.get("httpOnly", False)),
                )
            )
        if len(lines) == 1:
            raise InvalidCookieText("هیچ کوکی قابل‌استفاده‌ای در JSON پیدا نشد.")
        return "\n".join(lines) + "\n"

    # Raw request header, e.g. Cookie: SID=...; HSID=...
    header = text
    if header.lower().startswith("cookie:"):
        header = header.split(":", 1)[1].strip()
    # DevTools may copy a whole header block. Prefer the Cookie line.
    for line in text.splitlines():
        if line.lower().startswith("cookie:"):
            header = line.split(":", 1)[1].strip()
            break

    pairs: list[tuple[str, str]] = []
    for part in header.replace("\r", "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        if name:
            pairs.append((name, value.strip()))
    if not pairs:
        raise InvalidCookieText(
            "فرمت کوکی شناخته نشد. متن Cookie، خروجی JSON یا محتوای cookies.txt را وارد کنید."
        )

    lines = ["# Netscape HTTP Cookie File"]
    lines.extend(
        _netscape_line(default_domain or "example.com", "/", True, 0, name, value)
        for name, value in pairs
    )
    return "\n".join(lines) + "\n"


def create_temporary_cookie_file(raw_text: str, default_domain: str = "") -> Path:
    content = cookie_text_to_netscape(raw_text, default_domain)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix="yt_dlp_liquid_cookie_",
        suffix=".txt",
        delete=False,
    )
    try:
        handle.write(content)
        path = Path(handle.name)
    finally:
        handle.close()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _is_format_unavailable(message: object) -> bool:
    lowered = clean_message(message).lower()
    return "requested format is not available" in lowered or "only images are available" in lowered


def _has_javascript_runtime() -> bool:
    return resolve_javascript_runtime() is not None


def _iter_media_formats(info: dict[str, Any] | None):
    if not info:
        return
    if info.get("_type") in {"playlist", "multi_video"}:
        for entry in info.get("entries") or []:
            if isinstance(entry, dict):
                yield from _iter_media_formats(entry)
        return
    for fmt in info.get("formats") or []:
        if not isinstance(fmt, dict):
            continue
        has_video = fmt.get("vcodec") not in (None, "none")
        has_audio = fmt.get("acodec") not in (None, "none")
        if has_video or has_audio:
            yield fmt


def _friendly_error(exc: Exception, language: str = "fa") -> str:
    message = clean_message(exc)
    lowered = message.lower()
    if (
        "spotdl could not reach spotify" in lowered
        or "spotdl could not reach music.youtube.com" in lowered
        or "spotify metadata could not be read" in lowered
        or "official spotify api mode is enabled" in lowered
    ):
        if language == "en":
            return message
        if "music.youtube.com" in lowered:
            return (
                "اتصال spotDL به YouTube Music برقرار نشد. Leon یک‌بار با ارائه‌دهندهٔ معمولی YouTube و برای تک‌آهنگ‌ها "
                "با جست‌وجوی داخلی خودش تلاش می‌کند؛ اگر هر دو مسیر شکست بخورند، در بخش «Packages & Tools» یک پروکسی "
                "HTTP(S) فعال وارد کنید و دوباره امتحان کنید. این پروکسی برای Spotify، YouTube و مسیر جایگزین استفاده می‌شود.\n\n"
                f"جزئیات فنی: {message}"
            )
        return (
            "spotDL نتوانست اطلاعات آهنگ را از سرویس متادیتای Spotify دریافت کند. "
            "در بخش «Packages & Tools» ابتدا spotDL را به‌روزرسانی کنید. اگر Spotify در شبکه شما مسدود است، "
            "پروکسی وارد کنید؛ برای آلبوم‌ها و پلی‌لیست‌ها نیز می‌توانید API رسمی را با Client ID و Client Secret فعال کنید.\n\n"
            f"جزئیات فنی: {message}"
        )
    if ("pornhub" in lowered or "[pornhub]" in lowered) and ("http error 410" in lowered or "410: gone" in lowered):
        ready, details = pornhub_support_ready()
        if language == "en":
            return (
                "PornHub now requires browser-request impersonation. LeonDL needs yt-dlp 2026.06.09 or newer "
                "and the curl_cffi networking backend. Run setup_windows.bat (or reinstall requirements), then restart the app. "
                "If both are already available, open the URL in your browser first and use browser cookies when the page "
                "requires login, age verification, or regional access. A 410 can also mean the item was removed.\n\n"
                f"Environment: {details}\n\nTechnical details: {message}"
            )
        return (
            "PornHub برای درخواست‌های جدید به شبیه‌سازی مرورگر نیاز دارد. LeonDL باید yt-dlp نسخهٔ "
            "2026.06.09 یا جدیدتر و کتابخانهٔ curl_cffi را داشته باشد. فایل setup_windows.bat را اجرا کن و بعد برنامه را "
            "کامل ببند و دوباره باز کن. اگر هر دو مورد نصب هستند، لینک را ابتدا در مرورگر باز کن و برای محتوای نیازمند "
            "ورود، تأیید سن یا محدودیت منطقه‌ای از کوکی همان مرورگر استفاده کن. خطای 410 ممکن است به معنی حذف‌شدن محتوا هم باشد.\n\n"
            f"وضعیت محیط: {details}\n\nجزئیات فنی: {message}"
        )
    if "sign in to confirm you’re not a bot" in lowered or "sign in to confirm you're not a bot" in lowered:
        if language == "en":
            return (
                "YouTube requires a valid signed-in session for this link. Choose browser cookies, "
                "a cookies.txt file, or pasted cookie data in Authentication.\n\n"
                f"Technical details: {message}"
            )
        return (
            "یوتیوب برای این لینک ورود معتبر می‌خواهد. از بخش «احراز هویت» کوکی مرورگر، "
            "فایل cookies.txt یا اطلاعات کوکی دستی را انتخاب کنید.\n\n"
            f"جزئیات فنی: {message}"
        )
    if _is_format_unavailable(message):
        is_youtube = "youtube" in lowered or "youtu.be" in lowered
        if language == "en":
            if is_youtube:
                runtime_note = (
                    "No compatible JavaScript runtime was found. Install Deno and keep yt-dlp[default] up to date."
                    if not _has_javascript_runtime()
                    else "A JavaScript runtime was found. Update yt-dlp and yt-dlp-ejs together."
                )
                return (
                    "YouTube did not expose a usable media format. LeonDL tried compatible fallbacks. "
                    "This can be caused by an outdated yt-dlp build, unavailable JavaScript challenge solving, "
                    "or an account/IP restriction.\n\n"
                    f"{runtime_note}\n\n"
                    "Update command: python -m pip install -U \"yt-dlp[default]\"\n\n"
                    f"Technical details: {message}"
                )
            return (
                "This service did not expose a media format compatible with the selected quality. "
                "Try Automatic quality, update yt-dlp, or provide authentication if the service requires it.\n\n"
                "Update command: python -m pip install -U \"yt-dlp[default]\"\n\n"
                f"Technical details: {message}"
            )
        if is_youtube:
            runtime_note = (
                "هیچ اجرای جاوااسکریپت سازگاری روی سیستم پیدا نشد. Deno را نصب کنید و "
                "بستهٔ yt-dlp[default] را به‌روز نگه دارید."
                if not _has_javascript_runtime()
                else "اجرای جاوااسکریپت پیدا شد؛ yt-dlp و بستهٔ yt-dlp-ejs را با هم به‌روز کنید."
            )
            return (
                "یوتیوب قالب رسانهٔ قابل‌استفاده‌ای برنگرداند و حالت‌های جایگزین نیز نتیجه ندادند. "
                "علت می‌تواند نسخهٔ قدیمی yt-dlp، چالش JavaScript یا محدودیت حساب/IP باشد.\n\n"
                f"{runtime_note}\n\n"
                "دستور به‌روزرسانی: python -m pip install -U \"yt-dlp[default]\"\n\n"
                f"جزئیات فنی: {message}"
            )
        return (
            "این سرویس قالب رسانه‌ای سازگار با کیفیت انتخاب‌شده برنگرداند. کیفیت را روی «خودکار» بگذارید، "
            "yt-dlp را به‌روز کنید یا در صورت نیاز سرویس، اطلاعات احراز هویت بدهید.\n\n"
            "دستور به‌روزرسانی: python -m pip install -U \"yt-dlp[default]\"\n\n"
            f"جزئیات فنی: {message}"
        )
    return message


class SignalLogger:
    def __init__(self, signal: Signal, language: str = "fa") -> None:
        self.signal = signal
        self.language = language

    def debug(self, message: str) -> None:
        message = clean_message(message)
        if message and not message.startswith("[debug]"):
            self.signal.emit(message)

    def info(self, message: str) -> None:
        message = clean_message(message)
        if message:
            self.signal.emit(message)

    def warning(self, message: str) -> None:
        prefix = "Warning: " if self.language == "en" else "هشدار: "
        self.signal.emit(prefix + clean_message(message))

    def error(self, message: str) -> None:
        prefix = "Error: " if self.language == "en" else "خطا: "
        self.signal.emit(prefix + clean_message(message))


class DownloadWorker(Worker):
    log = Signal(str)
    progress = Signal(dict)
    postprocess = Signal(str)
    item_finished = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        urls: list[str],
        options: dict[str, Any],
        manual_cookie_text: str = "",
        manual_cookie_domain: str = "",
        language: str = "fa",
    ) -> None:
        super().__init__()
        self.urls = urls
        self.options = dict(options)
        self.manual_cookie_text = manual_cookie_text
        self.manual_cookie_domain = manual_cookie_domain
        self.language = "en" if language == "en" else "fa"
        self._cancel_event = threading.Event()
        self._progress_samples: dict[str, tuple[float, int]] = {}
        self.received_by_url: dict[str, int] = {}
        self._transfer_samples: dict[str, int] = {}
        self._transfer_url = ""

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        if yt_dlp is None:
            self.failed.emit("yt-dlp is not installed." if self.language == "en" else "کتابخانه yt-dlp نصب نشده است.")
            return

        options = dict(self.options)
        self.video_codecs = dict(options.pop("_leon_video_codecs", {}))
        self.audio_language = str(options.pop("_leon_audio_language", "") or "").strip()
        self.spotify_format = str(options.pop("_leon_spotify_format", "mp3") or "mp3").strip()
        self.spotify_client_id = str(options.pop("_leon_spotify_client_id", "") or "").strip()
        self.spotify_client_secret = str(options.pop("_leon_spotify_client_secret", "") or "").strip()
        self.spotify_use_official_api = bool(options.pop("_leon_spotify_use_official_api", False))
        self.spotify_proxy = str(options.pop("_leon_spotify_proxy", "") or "").strip()
        self.google_play_email = str(options.pop("_leon_google_play_email", "") or "").strip()
        self.google_play_aas_token = str(options.pop("_leon_google_play_aas_token", "") or "").strip()
        self.optional_gallery_fallback = bool(options.pop("_leon_optional_gallery_fallback", True))
        self.output_root = str(options.pop("_leon_output_root", "") or "").strip()
        options["logger"] = SignalLogger(self.log, self.language)
        options["progress_hooks"] = [self._progress_hook]
        options["postprocessor_hooks"] = [self._postprocessor_hook]
        temporary_cookie_file: Path | None = None

        try:
            if self.manual_cookie_text.strip():
                temporary_cookie_file = create_temporary_cookie_file(self.manual_cookie_text, self.manual_cookie_domain or (self.urls[0] if self.urls else ""))
                options["cookiefile"] = str(temporary_cookie_file)
            self.log.emit((f"Processing {len(self.urls)} link(s)" if self.language == "en" else f"شروع پردازش {len(self.urls)} لینک"))
            for index, url in enumerate(self.urls, start=1):
                if self._cancel_event.is_set():
                    raise DownloadCancelled
                self.log.emit((f"Processing link {index} of {len(self.urls)}" if self.language == "en" else f"پردازش لینک {index} از {len(self.urls)}"))
                if url_domain(url).startswith("pornhub"):
                    ready, details = pornhub_support_ready()
                    self.log.emit(("PornHub compatibility: " if self.language == "en" else "سازگاری PornHub: ") + details)
                    if not ready:
                        raise RuntimeError(
                            "[PornHub] HTTP Error 410: Gone. Browser impersonation support is not ready. " + details
                        )
                self._transfer_url = url
                self._transfer_samples.clear()
                self._download_routed(url, options)
                if self._cancel_event.is_set():
                    raise DownloadCancelled
                self.item_finished.emit(url)
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.finished_ok.emit()
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as exc:  # yt-dlp exposes multiple runtime exception types
            if self._cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(_friendly_error(exc, self.language))
        finally:
            if temporary_cookie_file:
                temporary_cookie_file.unlink(missing_ok=True)

    def _output_directory_for_optional_engine(self, url: str, options: dict[str, Any]) -> str:
        if self.output_root:
            root = Path(self.output_root)
        else:
            template = str(options.get("outtmpl") or "")
            root = Path(template).parent if template else Path.cwd()
        if "%(webpage_url_domain" in str(options.get("outtmpl") or ""):
            identity = service_identity(None, url)
            folder = str(identity.get("service") or identity.get("domain") or "Other").strip() or "Other"
            root = root / re.sub(r"[<>:\"/\\|?*]+", "_", folder)
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

    def _download_routed(self, url: str, options: dict[str, Any]) -> None:
        output_dir = self._output_directory_for_optional_engine(url, options)
        cookiefile = str(options.get("cookiefile") or "")
        browser = ""
        browser_profile = ""
        browser_value = options.get("cookiesfrombrowser")
        if isinstance(browser_value, (tuple, list)) and browser_value:
            browser = str(browser_value[0] or "")
            if len(browser_value) > 1:
                browser_profile = str(browser_value[1] or "")

        if is_spotify_url(url):
            self.log.emit("Using optional spotDL engine" if self.language == "en" else "استفاده از هستهٔ اختیاری spotDL")
            run_spotdl(
                url, output_dir, self.log.emit, self._cancel_event,
                output_format=self.spotify_format,
                cookiefile=cookiefile,
                spotify_client_id=self.spotify_client_id,
                spotify_client_secret=self.spotify_client_secret,
                use_official_api=self.spotify_use_official_api,
                proxy=self.spotify_proxy,
            )
            self.progress.emit({
                "status": "finished", "service": "Spotify", "domain": "open.spotify.com",
                "title": url, "webpage_url": url, "percent": 100.0,
            })
            return

        if is_app_store_url(url):
            source = app_store_source(url)
            self.log.emit((f"Using optional apkeep engine: {source}" if self.language == "en" else f"استفاده از هستهٔ اختیاری apkeep: {source}"))
            run_apkeep(
                url, output_dir, self.log.emit, self._cancel_event,
                source=source, google_email=self.google_play_email,
                google_aas_token=self.google_play_aas_token,
            )
            self.progress.emit({
                "status": "finished", "service": source, "domain": url_domain(url) or source,
                "title": url, "webpage_url": url, "percent": 100.0,
            })
            return

        try:
            self._download_with_fallback(url, options)
        except Exception as exc:
            if not getattr(self, "video_codecs", {}).get(url) and self.optional_gallery_fallback and gallery_dl_available() and (is_reddit_url(url) or is_instagram_url(url)):
                self.log.emit(
                    "yt-dlp could not expose a downloadable media format; trying gallery-dl"
                    if self.language == "en" else
                    "yt-dlp فرمت قابل دانلودی پیدا نکرد؛ تلاش با gallery-dl"
                )
                run_gallery_dl(
                    url, output_dir, self.log.emit, self._cancel_event,
                    cookiefile=cookiefile, browser=browser, browser_profile=browser_profile,
                )
                service = "Reddit" if is_reddit_url(url) else "Instagram"
                self.progress.emit({
                    "status": "finished", "service": service, "domain": url_domain(url),
                    "title": url, "webpage_url": url, "percent": 100.0,
                })
                return
            raise exc

    def _download_with_fallback(self, url: str, options: dict[str, Any]) -> None:
        selected_selector = str(options.get("format") or "")
        requested_language = str(getattr(self, "audio_language", "") or "").strip()
        if requested_language:
            selected_selector = _language_filter_selector(selected_selector, requested_language)
            self.log.emit(
                f"Preferred audio language: {requested_language}; automatic fallback is enabled"
                if self.language == "en"
                else f"زبان صوتی ترجیحی: {requested_language}؛ بازگشت خودکار فعال است"
            )
        height_matches = [int(value) for value in re.findall(r"height<=([0-9]+)", selected_selector)]
        height_cap = min(height_matches) if height_matches else None
        if height_cap is not None:
            # Keep every fallback at or below the user-selected resolution cap.
            attempts: list[tuple[str, str | None]] = [
                ("selected", selected_selector),
                ("single_capped", f"best[height<={height_cap}]/bestaudio"),
                ("general_capped", f"bestvideo*[height<={height_cap}]+bestaudio/best[height<={height_cap}]/bestaudio"),
            ]
        else:
            attempts = [
                ("selected", selected_selector),
                ("single", "best[ext=mp4]/best"),
                ("general", "bestvideo*+bestaudio/best"),
            ]
        codec = getattr(self, "video_codecs", {}).get(url)
        if codec in VIDEO_CODECS:
            attempts = [(label, filtered) for label, selector in attempts
                        if (filtered := _codec_selector(selector or "", codec))]
        seen: set[str | None] = set()
        last_error: Exception | None = None

        for label, selector in attempts:
            if selector in seen:
                continue
            seen.add(selector)
            attempt_options = dict(options)
            if selector:
                attempt_options["format"] = selector
            else:
                attempt_options.pop("format", None)
            if label != "selected":
                attempt_options.pop("format_sort", None)
                labels_fa = {
                    "single_capped": "قالب تک‌فایلی زیر سقف کیفیت",
                    "general_capped": "قالب عمومی زیر سقف کیفیت",
                    "single": "قالب سازگار تک‌فایلی",
                    "general": "بهترین قالب عمومی",
                }
                labels_en = {
                    "single_capped": "a single-file format under the quality cap",
                    "general_capped": "a general format under the quality cap",
                    "single": "a compatible single-file format",
                    "general": "the best general format",
                }
                label_text = labels_en.get(label, label) if self.language == "en" else labels_fa.get(label, label)
                self.log.emit(
                    f"The previous format was unavailable; retrying with {label_text}"
                    if self.language == "en"
                    else f"قالب قبلی موجود نبود؛ تلاش دوباره با «{label_text}»"
                )
            try:
                with yt_dlp.YoutubeDL(attempt_options) as ydl:
                    code = ydl.download([url])
                if code:
                    raise RuntimeError(f"yt-dlp exited with code {code}." if self.language == "en" else f"yt-dlp با کد {code} پایان یافت.")
                return
            except DownloadCancelled:
                raise
            except Exception as exc:
                last_error = exc
                if not _is_format_unavailable(exc):
                    raise

        if codec in VIDEO_CODECS:
            label = VIDEO_CODECS[codec][0]
            raise RuntimeError(
                f"No downloadable video uses {label} with the selected quality."
                if self.language == "en" else f"ویدئویی با کدک {label} و کیفیت انتخاب‌شده موجود نیست."
            ) from last_error

        diagnostics = self._inspect_available_media(url, options)
        if diagnostics == 0:
            if url_domain(url) in {"youtube.com", "youtu.be"} or url_domain(url).endswith(".youtube.com"):
                raise RuntimeError(
                    "Requested format is not available. Only images are available or YouTube did not expose media formats. "
                    "Ensure a supported JavaScript runtime and yt-dlp-ejs are installed."
                ) from last_error
            raise RuntimeError(
                "Requested format is not available. The service did not expose a usable audio or video format for this URL."
            ) from last_error
        raise last_error or RuntimeError("Requested format is not available")

    def _inspect_available_media(self, url: str, options: dict[str, Any]) -> int | None:
        inspect_options = {
            key: value
            for key, value in options.items()
            if key not in {
                "format", "format_sort", "merge_output_format", "postprocessors",
                "progress_hooks", "postprocessor_hooks", "outtmpl",
            }
        }
        inspect_options.update({"quiet": True, "no_warnings": True, "skip_download": True})
        try:
            with yt_dlp.YoutubeDL(inspect_options) as ydl:
                info = ydl.extract_info(url, download=False, process=False)
            count = sum(1 for _ in _iter_media_formats(info if isinstance(info, dict) else None))
            self.log.emit((f"Detected media formats: {count}" if self.language == "en" else f"تعداد قالب‌های رسانه‌ای شناسایی‌شده: {count}"))
            return count
        except Exception as exc:
            self.log.emit(("Technical format inspection failed: " if self.language == "en" else "بررسی فنی فرمت‌ها ناموفق بود: ") + clean_message(exc))
            return None

    def _progress_hook(self, data: dict[str, Any]) -> None:
        status = data.get("status")
        info = data.get("info_dict") or {}
        received = data.get("downloaded_bytes")
        if status in {"downloading", "finished"} and self._transfer_url and isinstance(received, (int, float)):
            key = str(data.get("filename") or info.get("format_id") or "active")
            previous = self._transfer_samples.get(key, 0)
            if status == "downloading" or key in self._transfer_samples:
                self._transfer_samples[key] = int(received)
                delta = max(0, int(received) - previous)
                self.received_by_url[self._transfer_url] = self.received_by_url.get(self._transfer_url, 0) + delta
        if self._cancel_event.is_set():
            raise DownloadCancelled

        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            percent = (downloaded / total * 100.0) if total else None

            speed = data.get("speed")
            try:
                speed = float(speed) if speed is not None else None
            except (TypeError, ValueError):
                speed = None
            if not speed or speed <= 0:
                elapsed = data.get("elapsed")
                try:
                    elapsed_value = float(elapsed) if elapsed is not None else 0.0
                except (TypeError, ValueError):
                    elapsed_value = 0.0
                if elapsed_value > 0 and downloaded > 0:
                    speed = downloaded / elapsed_value

            filename = str(data.get("filename") or info.get("id") or "active")
            now = time.monotonic()
            previous = self._progress_samples.get(filename)
            if (not speed or speed <= 0) and previous:
                previous_time, previous_bytes = previous
                delta_time = now - previous_time
                delta_bytes = downloaded - previous_bytes
                if delta_time > 0.15 and delta_bytes > 0:
                    speed = delta_bytes / delta_time
            self._progress_samples[filename] = (now, int(downloaded))

            eta = data.get("eta")
            try:
                eta = float(eta) if eta is not None else None
            except (TypeError, ValueError):
                eta = None
            if (eta is None or eta < 0) and speed and speed > 0 and total and total >= downloaded:
                eta = (total - downloaded) / speed

            speed_text = clean_message(data.get("_speed_str") or "")
            eta_text = clean_message(data.get("_eta_str") or "")
            if speed_text in {"N/A", "Unknown", "—"}:
                speed_text = ""
            if eta_text in {"N/A", "Unknown", "—"}:
                eta_text = ""

            source = service_identity(info, str(info.get("webpage_url") or info.get("original_url") or ""))
            self.progress.emit(
                {
                    "status": "downloading",
                    **source,
                    "title": info.get("title") or Path(data.get("filename", "File" if self.language == "en" else "فایل")).name,
                    "webpage_url": info.get("webpage_url") or info.get("original_url") or "",
                    "percent": percent,
                    "downloaded": downloaded,
                    "total": total,
                    "speed": speed,
                    "eta": eta,
                    "speed_text": speed_text,
                    "eta_text": eta_text,
                }
            )
        elif status == "finished":
            source = service_identity(info, str(info.get("webpage_url") or info.get("original_url") or ""))
            raw_filename = str(data.get("filename") or info.get("filepath") or "")
            self.progress.emit(
                {
                    "status": "finished",
                    **source,
                    "title": info.get("title") or Path(raw_filename or ("File" if self.language == "en" else "فایل")).name,
                    "filename": Path(raw_filename or ("File" if self.language == "en" else "فایل")).name,
                    "filepath": raw_filename,
                    "webpage_url": info.get("webpage_url") or info.get("original_url") or "",
                    "id": info.get("id") or "",
                    "percent": 100.0,
                }
            )

    def _postprocessor_hook(self, data: dict[str, Any]) -> None:
        if self._cancel_event.is_set():
            raise DownloadCancelled
        name = data.get("postprocessor") or ("Post-processing" if self.language == "en" else "پردازش نهایی")
        status = data.get("status")
        if status == "started":
            self.postprocess.emit((f"Processing: {name}" if self.language == "en" else f"در حال پردازش: {name}"))
        elif status == "finished":
            self.log.emit((f"Post-processing finished: {name}" if self.language == "en" else f"پردازش نهایی شد: {name}"))


class PreviewWorker(Worker):
    """Fetch previews for every supplied URL without blocking the GUI.

    One worker and one YoutubeDL context are shared across the whole batch. This
    avoids repeatedly opening/copying browser cookie databases and keeps the
    cards in the same order as the input links.
    """

    item_started = Signal(int, int, str)
    ready = Signal(int, dict)
    failed = Signal(int, str, str)

    def __init__(
        self,
        urls: list[str] | tuple[str, ...] | str,
        auth_options: dict[str, Any] | None = None,
        manual_cookie_text: str = "",
        manual_cookie_domain: str = "",
        language: str = "fa",
    ) -> None:
        super().__init__()
        if isinstance(urls, str):
            self.urls = [urls]
        else:
            self.urls = [str(url).strip() for url in urls if str(url).strip()]
        self.auth_options = dict(auth_options or {})
        self.manual_cookie_text = manual_cookie_text
        self.manual_cookie_domain = manual_cookie_domain
        self.language = "en" if language == "en" else "fa"

    def run(self) -> None:
        if yt_dlp is None:
            message = "yt-dlp is not installed." if self.language == "en" else "کتابخانه yt-dlp نصب نشده است."
            for index, url in enumerate(self.urls):
                self.failed.emit(index, message, url)
            return

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "playlist_items": "1",
            **self.auth_options,
        }
        spotify_proxy = str(options.pop("_leon_spotify_proxy", "") or "").strip()
        temporary_cookie_file: Path | None = None
        completed_indexes: set[int] = set()

        try:
            if self.manual_cookie_text.strip():
                temporary_cookie_file = create_temporary_cookie_file(
                    self.manual_cookie_text,
                    self.manual_cookie_domain or (self.urls[0] if self.urls else ""),
                )
                options["cookiefile"] = str(temporary_cookie_file)

            with yt_dlp.YoutubeDL(options) as ydl:
                total = len(self.urls)
                for index, url in enumerate(self.urls):
                    if self.isInterruptionRequested():
                        break
                    self.item_started.emit(index, total, url)
                    try:
                        if is_spotify_url(url):
                            metadata = spotify_preview_metadata(url, spotify_proxy)
                            title = str(metadata.get("title") or "").strip()
                            if not title:
                                raise RuntimeError("Spotify did not return a preview title.")
                            self.ready.emit(
                                index,
                                {
                                    "service": "Spotify",
                                    "domain": "open.spotify.com",
                                    "title": title,
                                    "uploader": str(metadata.get("provider_name") or "Spotify"),
                                    "duration": None,
                                    "thumbnail": str(metadata.get("thumbnail_url") or ""),
                                    "audio_languages": [],
                                    "subtitle_languages": [],
                                    "formats": [],
                                    "webpage_url": url,
                                    "input_url": url,
                                },
                            )
                            completed_indexes.add(index)
                            continue
                        info = ydl.extract_info(url, download=False)
                        if info and info.get("_type") == "playlist":
                            entries = info.get("entries") or []
                            info = next((entry for entry in entries if entry), info)
                        source = service_identity(info if isinstance(info, dict) else None, url)
                        self.ready.emit(
                            index,
                            {
                                **source,
                                "title": (info or {}).get("title") or ("Untitled" if self.language == "en" else "بدون عنوان"),
                                "uploader": (info or {}).get("uploader") or (info or {}).get("channel") or "—",
                                "duration": (info or {}).get("duration"),
                                "thumbnail": (info or {}).get("thumbnail") or "",
                                "audio_languages": extract_audio_languages(info if isinstance(info, dict) else None),
                                "subtitle_languages": extract_subtitle_languages(info if isinstance(info, dict) else None),
                                "formats": compact_media_formats(info if isinstance(info, dict) else None),
                                "webpage_url": (info or {}).get("webpage_url") or url,
                                "input_url": url,
                            },
                        )
                        completed_indexes.add(index)
                    except Exception as exc:
                        self.failed.emit(index, _friendly_error(exc, self.language), url)
                        completed_indexes.add(index)
        except Exception as exc:
            message = _friendly_error(exc, self.language)
            for index, url in enumerate(self.urls):
                if index not in completed_indexes:
                    self.failed.emit(index, message, url)
        finally:
            if temporary_cookie_file:
                temporary_cookie_file.unlink(missing_ok=True)

