# Changelog

All notable Leon Downloader changes are recorded here. The technical architecture and current behavior belong in `AI_DEVELOPER_GUIDE.md`; release history must not be duplicated there.

## 2.6.3 — 2026-08-10

### Added

- **In-app update from GitHub Releases** (Settings → Update tab). The app silently checks `LeonAmir/LeonDL` for a newer published release at startup (EXE builds only), compares versions, and lets the user download and install the Windows build in one step with full SHA-256 verification (GitHub's per-asset digest). Applying waits for the app to exit, replaces the main and native-host executables beside the EXE, refreshes the bundled docs/extension and relaunches automatically. Source runs can check but update via `git pull`.
- MIT license (repository is now public on GitHub).

### Changed

- The internal developer guide is no longer shipped or published — release folders/ZIPs contain README, CHANGELOG, VERSION and LICENSE only.

## 2.6.2 — 2026-08-09

### Changed

- Project renamed to **LeonDL** across branding, UI copy, EXE/archive names, release titles, docs, and the Chrome extension display name.
- New naming pattern: `LeonDL-<version>.exe`, `LeonDL-Native-Host-<version>.exe`, `LeonDL-v<version>.zip`, `LeonDL-v<version>-Windows.zip`.
- Intentionally unchanged for compatibility: the per-user data directory `~/.yt_dlp_liquid/`, the Chrome extension ID (key-derived), and the Native Messaging host identifier `com.leon_downloader.bridge` — settings, history, auth profiles, and existing extension pairing survive the rename.

## 2.6.1 — 2026-08-09

### Added

- Windows EXE build packaging for end users: the release ZIP now ships a ready-to-run `LeonDL-2.6.1.exe` (PyInstaller one-file, windowed) together with `Leon-Native-Host-2.6.1.exe`, the `chrome_extension/` folder, and the release documents (`README.md`, `AI_DEVELOPER_GUIDE.md`, `CHANGELOG.md`, `VERSION`) beside it.
- Users extract the ZIP and run `LeonDL-2.6.1.exe` directly — no source launch, `.bat`, or `.vbs` step is required.
- The frozen EXE now verifies its external prerequisites on startup (FFmpeg + FFprobe, and Deno) and installs any missing tool automatically through WinGet in the background, without blocking the window. Results are streamed to the Log page and summarized in a toast. The Packages & Tools page remains authoritative for manual management.
- This automatic prerequisite path exists only for frozen/EXE builds; source-mode startup keeps the 2.5.1 policy of never installing optional external tools before the window opens.

### Changed

- The official Windows distribution now targets the frozen/EXE launcher path as the primary end-user mode; the source layout remains fully supported for development.
- Version bumped to 2.6.1 across all correlated locations (constants, badge, manifest, user agents, docs).

## 2.6.0 — 2026-08-08

### Added

- Added an inline **Quality / Format** selector to every persistent Queue row.
- Added per-row Queue size recalculation so changing a preset immediately updates the **Size** column when cached format metadata is available, or refreshes metadata in the background when needed.

### Changed

- Queue preset edits are persisted to `download_later.json` and are restored when the item is transferred back to Download.
- Added an in-memory compact-format cache for Queue size estimates to avoid redundant network extraction during repeated quality changes in the same session.
- Added `LaterStore.update_index()` for exact row mutations when the preset itself (part of the normal stable key) changes.

## 2.5.9 — 2026-08-08

### Changed

- Replaced the generated Leon Minimal/Soft/Digital notification packs with a single calmer **Gentle & Pleasant** default pack sourced from existing CC0 sounds on Wikimedia Commons.
- Gentle sounds are downloaded once in a background thread, validated, cached per user, and reused offline; application startup no longer depends on bundled generated tones.
- Added documented source and license provenance in `assets/sounds/SOURCES.md`.
- Expanded per-event custom sound overrides from WAV-only to WAV, OGG/OGA, MP3, M4A, AAC, and FLAC.
- Legacy 2.5.8 sound-theme values (`minimal`, `soft`, `digital`) automatically migrate to `gentle`; System Sounds remains available only as the explicit legacy choice.

### UX

- Reduced the default sound volume and applied gentler per-event gain/playback profiles so errors, cancellation, warnings, and completion cues are less harsh.
- Removed the automatic OS beep fallback while the Gentle pack is still being fetched.

## 2.5.8 — 2026-08-07

### Added

- Added three bundled Leon sound packs: Minimal, Soft, and Digital, with short original WAV cues for download completion, queue completion, errors, warnings, cancellation, and extension/app notifications.
- Added a Sound Pack selector, master volume control, six per-event toggles, per-event custom WAV overrides, individual Test buttons, and a one-click custom-sound reset in Settings → Language & Appearance.
- Added a separate queue-complete sound for multi-link batches while retaining per-download completion feedback for each finished URL.

### Changed

- Leon now uses preloaded `QSoundEffect` playback for its own sound packs instead of relying on Windows system sounds by default. The legacy System Sounds option remains available.
- Chrome-extension deliveries and selected warning prompts can now use their own notification/warning cues.
- Sound settings are preserved across language rebuilds and persisted as theme, volume, per-event enable state, and custom WAV paths.

## 2.5.7 — 2026-08-07

### Fixed

- Fixed multi-link cleanup so completing one URL no longer clears every URL from Download Links.
- A successful input now removes only its own Download Links line and only its matching Preview card; pending or failed links remain available for download/retry.
- Per-input cleanup also works for optional download engines because completion is emitted only after the routed download for that exact input returns successfully.

## 2.5.6 — 2026-08-07

### Added

- Added configurable application sounds for successful download completion, download errors, and user cancellation. Windows uses the user's configured system sounds; other platforms fall back to Qt's standard beep without bundling audio assets or QtMultimedia.
- Added a test-sound button and per-event sound toggles under Settings → Language & Appearance.

### Changed

- After a fully successful batch, the Download Links input and the Preview list are cleared automatically and the Preview area returns to its empty state. Failed or cancelled downloads keep their links and previews for retry/resume.
- Optional-engine subprocess output is now consumed on a reader thread so cancellation remains responsive even when spotDL, gallery-dl, or apkeep is silent or blocked on network I/O.

### Fixed

- Fixed the cancel-then-close lifecycle where Leon could still report an active download after the user had already cancelled it and then refuse to exit.
- Closing after a prior Cancel no longer asks the same active-download question again. Leon first waits for cooperative shutdown, then uses a bounded last-resort worker termination only during application exit if the worker is still stuck.

## 2.5.5 — 2026-08-05

### Fixed

- Fixed the GUI reporting that no extension cookies existed even after Chrome confirmed that cookies were saved. The long-lived GUI authentication store now reloads profiles written by the separate Native Messaging process.
- Prevented stale GUI state from overwriting newly received extension-cookie profiles during later validation, invalidation, removal, or save operations.
- Normalized current-site lookup through the same service-domain rules for incoming bridge requests and Settings.

### Changed

- Settings → Cookies and login now rechecks the external profile index before displaying extension-cookie status or starting Preview/Download.
- Added a **Recheck extension cookie status** action and domain-specific states for missing, received-pending, ready, and missing-protected-payload conditions.
- Extension-cookie status remains visible even when automatic reuse of remembered authentication is disabled.

### Tests

- Expanded authentication and browser-bridge smoke tests with a stale GUI-store scenario where the Native Messaging process writes cookies after the GUI store has already been created.
- Added `extension_cookie_sync_smoke.py` and included it in the Windows build verification path.

## 2.5.4 — 2026-08-05

### Fixed

- Fixed Chrome Popup sends failing with `Only permissions specified in the manifest may be requested`.
- Declared the optional runtime host-access envelope with the exact `*://*/*` match pattern while requesting only the current page scheme and service domain at runtime.
- Right-click sends now request per-site cookie permission during the explicit context-menu user action instead of silently sending the URL without cookies.
- Cookie permission and other non-pairing failures no longer reveal the Pairing panel or make a saved pairing code appear lost.

### Changed

- Cookie collection is URL-scoped before Leon performs its second domain and partition filter.
- The Popup reports when a link was sent successfully but Chrome returned no usable cookies for the page.

## 2.5.3 — 2026-08-05

### Fixed

- Fixed blank white `QMessageBox` windows caused by the application-wide light text color being rendered over the platform's default light dialog background.
- Added explicit theme-aware backgrounds, text colors, detail panels, and buttons for all Qt message boxes.
- Empty exception messages now display a localized fallback instead of opening an apparently empty dialog.

### Diagnostics

- Download-error dialogs now expose selectable text, a copy action, and the recent live log in the expandable details section.
- Handled download errors are appended to `~/.yt_dlp_liquid/leon_runtime.log` for later diagnosis.
- Added `message_dialog_smoke.py` to guard the error-dialog styling and fallback-message contract.

## 2.5.2 — 2026-08-05

### Added

- Added **Cookies received from Chrome extension** as a first-class authentication source in Settings → Cookies and login.
- Added current-domain status and guidance for extension-cookie profiles, plus a shortcut to the Chrome Extension page.
- Added `watched_preview_smoke.py` to cover Chrome-triggered YouTube preview behavior.

### Fixed

- Extension cookies are now stored with the explicit `extension` authentication method instead of appearing as generic manual or cookie-file authentication.
- Fixed Chrome **Send to Leon** previews not receiving yt-dlp's `mark_watched` option when watched marking is enabled and account cookies are available.
- Kept background Queue/title metadata lookups from marking videos watched; watched marking applies only to the main user-requested preview and actual download.

### Changed

- Clarified that YouTube watched marking is best-effort and may not appear immediately or reliably in YouTube history.

## 2.5.1 — 2026-08-05

### Fixed

- Fixed first-run startup getting stuck on the splash at “Installing and checking requirements”.
- Removed automatic FFmpeg and Deno installation from the startup-critical path; optional external tools are now handled only from Packages and Tools after the main window opens.
- Fixed `setup_windows.bat` so it no longer performs a mandatory pip/setuptools/wheel upgrade or a strict external-tool installation before Leon can start.
- Added bounded pip network retries and timeouts so an unavailable package index fails with a readable setup error instead of waiting for up to an hour.

### Changed

- The launcher and direct source startup now prepare only the core Python packages required to open the GUI.
- The launcher can reuse a compatible `.venv` from a nearby older Leon source release, avoiding a full PySide6/yt-dlp reinstall after every ZIP update.
- `setup_windows.bat` now prepares the core runtime, writes the startup fingerprint, and directs optional-tool installation to the in-app Package Manager.
- Added `startup_bootstrap_smoke.py` to prevent strict external setup from returning to the launch path.


## 2.5.0 — 2026-08-04

### Added

- Added a bundled Manifest V3 Chrome extension with toolbar popup and right-click actions for sending the current page, media URL, or link directly to Leon Downloads or Queue.
- Added a Chrome Native Messaging host, a Windows per-user installer/repair flow, stable extension ID, and one-time pairing code.
- Added optional per-site cookie transfer. Cookie values are filtered to the submitted URL domain, never written to the request inbox, and stored through Leon's existing authentication store with Windows DPAPI.
- Added a dedicated Chrome Extension page in the desktop app with bridge status, extension folder, pairing code, setup actions, and privacy guidance.
- Added persistent request inbox and heartbeat/start-lock handling so the extension can wake Leon when closed and deliver to the existing instance when open.
- Added `browser_bridge_smoke.py` covering extension ID stability, manifest permissions, cookie filtering, pairing, and inbox delivery.

### Changed

- Rebuilt both startup splash paths from the same theme tokens used by the main application. The splash now follows the user's saved theme, including the window gradient, ambient accent colors, glass surfaces, border, typography hierarchy, BrandMark, and progress styling.
- Added smooth fade-in/fade-out transitions and a continuous back-and-forth loading motion with no visible loop reset.
- Moved all palette definitions into `core/theme_tokens.py`, a Qt-free source of truth shared by `ui/theme.py`, `launcher.pyw`, and the Qt splash.
- Reworked Package Manager inventory so the page performs a full read-only scan of the active Python environment, importable modules, PATH, Leon local tools, the current Python Scripts directory, Deno user paths, and Windows WinGet locations before presenting actions.
- Package actions are now installation-state aware. Missing tools get an Install action; detected tools get an Update-only action. Update paths no longer fall back to a clean installation.
- FFmpeg is considered fully installed only when both `ffmpeg` and `ffprobe` are detected.

### Fixed

- Prevented already-detected tools from being routed through generic install-or-update commands that could attempt a redundant installation.
- Disabled automatic apkeep installation on unsupported non-Windows systems.

## 2.4.9 — 2026-08-04

### Changed

- Simplified the startup loader to a minimal theme-matched track and moving pill.
- Removed the over-decorated segmented and orb effects from both splash implementations.

## 2.4.8 — 2026-08-04

### Changed

- Refined the startup loading bar in the Windows launcher and internal Qt splash.
- Kept the progress visuals synchronized with the active Leon theme.

## 2.4.7 — 2026-08-04

### Changed

- Unified launcher, Qt splash, and main-window palettes through `core/theme_tokens.py`.
- Reworked Package Manager inventory so detected tools use Update actions while missing tools use Install actions.

## 2.4.6 — 2026-08-04

### Changed

- Reworked the Windows source-launch splash into a cleaner glass-style card with smoother loading motion and clearer status text.
- Refined the internal Qt startup splash so frozen and direct GUI launches used the same upgraded visual direction.

### UX

- Added smoother startup animation and improved splash readability while preserving console-free launch behavior.

## 2.4.5 — 2026-08-04

### Added

- Added a synchronized Quality / Format selector directly to the Download command bar, so users no longer need to open Settings for routine quality changes.
- Renamed the user-facing Download Later workflow to Queue and added direct multi-URL entry, Paste, Clear, and Add to Queue controls on the Queue page.
- Added title-aware Download queue rows that display both media title and source URL. Known preview, search, and persistent-queue metadata is reused, while missing titles are fetched in a background worker.
- Added lightweight Spotify oEmbed previews so Spotify queue items can display a title without asking yt-dlp to extract Spotify URLs.
- Added `launcher.pyw`, `LeonDL.vbs`, and a Qt startup splash for console-free Windows startup.

### Changed

- Deferred Package Manager probing, JavaScript runtime detection, History loading, and persistent Queue metadata enrichment until the related page is opened.
- Normal Windows launches now use a dependency fingerprint under `.venv`; pip/bootstrap work runs only when the environment or dependency definitions change.
- `run_windows.bat` is now a compatibility shim that starts the console-free launcher instead of running setup checks and smoke tests on every launch.
- Source and frozen launches skip redundant bootstrap probes when the launcher or bundled executable already prepared the runtime.

### Performance

- Removed repeated pip upgrades, strict bootstrap checks, Qt paint smoke tests, and persistence smoke tests from the normal startup path.
- Avoided applying the full application theme twice during `MainWindow` construction.

## 2.4.4 — 2026-08-04

### Fixed

- Detects spotDL startup failures caused by `music.youtube.com` connection timeouts.
- Automatically retries the same Spotify request with spotDL's standard `youtube` audio provider, which supports tracks, albums, and playlists.
- If both spotDL providers fail for a single track, Leon continues to its existing Spotify oEmbed plus in-process yt-dlp search fallback.
- Produces a focused user-facing message instead of exposing only the generic optional-engine exit code.

### Changed

- Clarified that the Package Manager proxy field applies to Spotify metadata, YouTube, YouTube Music, and the single-track fallback.
- Masks passwords embedded in authenticated proxy URLs before commands are written to the Log page.
- Expanded `spotify_engine_smoke.py` to cover metadata failure, YouTube Music timeout retry, proxy propagation, and final single-track fallback routing.

## 2.4.3 — 2026-08-04

### Fixed

- Prevented the Packages & Tools table from collapsing to an unusably thin strip.
- Added a page-level vertical scroll area, a practical minimum table height, minimum row and action-button heights, and dynamic table-height synchronization after status refresh.

## 2.4.2

- `OptionalEngineError` now carries recent subprocess output so the UI can report the underlying optional-engine failure rather than only an exit code.
- Spotify track downloads detect failures from spotDL's default `SpotifyFree`/`SpotAPI` metadata path.
- A single-track fallback reads the official Spotify oEmbed title and performs an in-process yt-dlp audio search. The in-process implementation works in both source and frozen EXE builds.
- Albums and playlists do not use the oEmbed fallback because oEmbed does not expose their full track lists.
- The Packages & Tools page now exposes an optional official-API toggle, Spotify Client ID, session-only Client Secret, and optional proxy.
- `_build_options()` passes `_leon_spotify_use_official_api`, `_leon_spotify_client_id`, `_leon_spotify_client_secret`, and `_leon_spotify_proxy` to `DownloadWorker`.
- `run_spotdl()` adds `--use-official-api`, `--client-id`, `--client-secret`, and `--no-cache` only when official mode is enabled and both credentials are present.
- `PackageActionWorker` updates spotDL with `--upgrade-strategy eager` so transitive metadata dependencies are refreshed.
- Added `spotify_engine_smoke.py` for secret masking and fallback-routing coverage.

## 2.4.1

- Unified all core and optional dependencies in the existing Packages & Tools table.
- Removed the standalone optional-engine card from `MainWindow._build_packages_page()`.
- Expanded `package_table` to six columns: tool, purpose, status, version, path, and action.
- Added a localized concise purpose for every row and a row-specific Install/Update button.
- Moved the Google Play email and AAS token controls beneath the unified table because they belong to the apkeep workflow.
- Added platform/deployment-aware button availability: bundled Python components are updated through a new app release in frozen builds, while Deno and FFmpeg auto-install actions remain Windows-only.

## 2.4.0

- Added `core/optional_engines.py` as the routing and subprocess layer for optional providers.
- Added user-installable `gallery-dl`, `spotDL`, and `apkeep` engines to Package Manager.
- Reddit and Instagram URLs still try yt-dlp first; when yt-dlp exposes no usable media, gallery-dl is used as a fallback for images, GIFs, and galleries.
- Spotify URLs are routed directly to spotDL. spotDL uses Spotify metadata to locate corresponding audio through its configured providers; it is not a direct Spotify stream extractor.
- APKPure, F-Droid, Google Play, and Huawei AppGallery inputs are routed to apkeep.
- Google Play credentials are passed only for the current process. The AAS token is never persisted in settings.
- Optional executables are stored under `~/.yt_dlp_liquid/tools/` when installed as standalone tools.

## 2.3.2

- `SpeedWaveWidget.paintEvent()` now uses separate left/right header rectangles and forces the numeric speed text to LTR, preventing overlap in Persian mode.
- Download Later entries now include `duration`, `size_bytes`, `size_confidence`, `metadata_status`, and an audio-language snapshot.
- `MainWindow` starts background metadata enrichment with `PreviewWorker` after queue insertion and for legacy entries missing metadata.
- `LaterStore.update_matching()` atomically merges metadata into the persistent item identified by URL, preset, and output directory.
- The Download Later table expanded from five to seven columns to show duration and size.

## 2.3.1

- `SpeedWaveWidget` now paints a localized caption and the current formatted transfer rate in its header while preserving the animated history wave.
- General download settings now include an opt-in `mark_watched_check`.
- When enabled, `_build_options()` passes `mark_watched=True` to the yt-dlp Python API.
- The setting is persisted in `settings.json` as `mark_watched` and is preserved when the interface is rebuilt for language changes.
- Watched marking is YouTube-only, requires authenticated account cookies, and must be treated as best-effort because YouTube-side behavior can change or be inconsistent.

## 2.3.0

- Moved the live log from the Download page to an independent sidebar Log page.
- Added `SpeedWaveWidget`, a themed animated sine/history visualization fed by normalized download speed.
- Changed the default theme to YouTube Studio and added a one-time migration for `ui_version < 4`.
- Added persistent IDM-style Download Later storage, sidebar page, command-bar action, and Search integration.
- Added `core/later_store.py` and `later_store_smoke.py`.
- Changed search extraction from flat entries to full metadata and added stable YouTube JPEG thumbnail fallback plus browser-like thumbnail request headers.
- Expanded sidebar page keys to include `later` and `log`; use `_set_main_page_by_key()` for navigation.

## 2.2.4

- Removed the extra helper labels from the sidebar so the navigation area is cleaner.
- Disabled the visible focus rectangle on the left navigation list and removed its inner item border styling.
- Updated visible version strings to `2.2.4`.

## 2.2.3

- Applied a compact/minimal UI pass without changing application workflows.
- Reduced global font size slightly, button padding/heights, card radii, sidebar width, page margins, and large empty-state heights.
- Preserved RTL/LTR behavior, accessibility, and Settings-based language/theme controls.
- No persistence schema, downloader, authentication, history, search, or package-manager contract changed.

## 2.2.2

- The title-bar version badge was simplified to show only the version number.
- Missing English translations were added for the left sidebar helper labels.
- The visible title-bar buttons for theme and language were removed; both actions remain available from Settings.

## 2.2.1

- Hotfix for a startup crash in `ui/theme.py`.
- The cause was literal CSS braces not escaped inside the stylesheet f-string.
- Sidebar navigation and larger high-DPI title-bar icons remain from 2.2.0.
- All version display locations were updated to `2.2.1`.

## 2.2.0

- Replaced top main tabs with a sidebar and `QStackedWidget` navigation.
- Added sidebar icons for Download, Search, History, Settings, and Package Manager.
- Increased internal icon rendering scale and title-bar utility button/icon sizes.
- Added sidebar-specific theme rules.

## 2.1.0

- Added direct Search page.
- Added persistent History page.
- Reorganized Settings into four sub-tabs.
- Added Package Manager page.

## 2.0.5

- Added remembered per-domain authentication.
- Added managed cookie-file copies.
- Added Windows DPAPI encryption for manual cookies.
- Added validity marking and auth-error invalidation.

## 2.0.4

- Fixed QPen/QPainter crash path.
- Added protected painter cleanup and offscreen paint smoke testing.

Earlier release history is summarized in `README.md`.

---
