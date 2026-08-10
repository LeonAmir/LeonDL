# LeonDL — v2.6.3

[فارسی](README.fa.md) | **English**

A multi-service, bilingual desktop downloader for **yt-dlp**, built with **PySide6 (Qt)**. It is not limited to YouTube — it accepts links from any service supported by the installed yt-dlp extractors: YouTube, Instagram, TikTok, X/Twitter, Vimeo, Twitch, SoundCloud, Facebook, Reddit, Dailymotion and more.

> Complete version history: [`CHANGELOG.md`](CHANGELOG.md)

## Key features

- **Simultaneous preview of all links** with independent cards (title, service, duration, thumbnail, status); an error on one link doesn't stop the rest
- **Quality/format selection**: auto, best quality, MP4, 8K down to 144p, MP3, M4A, original audio without conversion
- **Audio language and subtitle selection** per link (manual and auto subtitles)
- **Queue**: persistent download queue with background metadata fetching (title, duration, size, service, added time) and a per-row **Quality/Format selector** with live size recalculation
- **Automatic per-service folder organization**: `youtube.com/…`, `instagram.com/…`, `soundcloud.com/…`, etc. (can be disabled)
- **Protected authentication**: browser cookies, manual cookies and saved per-domain profiles; DPAPI encryption on Windows; remembers each service's last successful method
- **Chrome extension (Manifest V3) + Native Messaging**: send pages/links to Download or Queue, plus optional same-site cookies with explicit user permission
- **Package Manager**: environment checks and install/update for yt-dlp, FFmpeg, FFprobe, Deno and optional engines
- **Optional engines**: `gallery-dl` (Reddit/Instagram images & GIFs), `spotDL` (Spotify metadata), `apkeep` (Android APK downloads from Google Play, APKPure, F-Droid and AppGallery)
- **Bilingual UI — Persian (RTL) / English (LTR)** with the Vazir font
- **5 themes**: Midnight Aurora, Golden Obsidian, Royal Navy, Ivory Light and YouTube Studio (default)
- **Live speed graph** (Steam-style), sidebar log, splash screen and configurable sound events (CC0 sound pack)

## Requirements

- Python 3.10 or newer + pip
- `yt-dlp[default,curl-cffi]` version 2026.06.09 or newer (required for PornHub and services needing browser impersonation)
- `yt-dlp-ejs` and `curl_cffi` (JavaScript challenge support)
- PySide6, FFmpeg, FFprobe, Deno

## Install & run on Windows

1. Extract the ZIP completely.
2. Double-click `LeonDL.vbs` — the app runs without a visible CMD window.
3. On first run, `.venv` and the core packages are prepared automatically; auxiliary tools (FFmpeg, etc.) are installed later from the Packages and Tools section.

> **Windows EXE build (recommended for end users):** extract the ZIP and run `LeonDL-2.6.3.exe` directly — no source launch or `.bat`/`.vbs` step. On first run the EXE checks FFmpeg/FFprobe and Deno and installs any missing tool automatically in the background.

Helper files:

| File | Purpose |
|---|---|
| `setup_windows.bat` | Manual setup of core packages |
| `diagnose_windows.bat` | Full environment troubleshooting |
| `run_windows.bat` | Legacy compatibility only — runs the same hidden launcher |

Logs are saved to `leon_setup.log` and `leon_runtime.log`.

## Run manually from source

```bash
python bootstrap.py --skip-external
python app.py
```

## Chrome extension

1. Open the **Chrome Extension** page in the app and click **Install / Repair bridge** (registers Native Messaging for the current Windows account).
2. In Chrome, open `chrome://extensions`, enable **Developer mode** and click **Load unpacked**.
3. Select the folder shown in the app.
4. Copy the pairing code from the app and enter it once in the extension popup.

Then available:

- **Send to Leon** — send the page URL to Download and run Preview automatically
- **Add to Queue** — add directly to the queue (button or right-click)
- **Send site cookies** — only with explicit user permission, limited to the same page's domain; partitioned or unrelated cookies are rejected

## Build EXE on Windows

```text
BUILD-EXE.bat
```

PyInstaller output goes into the `dist` folder. The actual EXE build must be done on Windows.

## Responsible use

Only download content you own or have permission to download, and respect the terms of service of the relevant service.

---

📖 Persian version: [`README.fa.md`](README.fa.md)
