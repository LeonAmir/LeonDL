from __future__ import annotations

"""Console-free Windows source launcher using Leon's actual saved theme.

The launcher has no Qt dependency, so it can display immediately even before
``.venv`` exists. Its palette comes from the same pure-Python theme tokens used
by ``ui.theme``; this prevents visual drift between splash and main window.
"""

import hashlib
import json
import math
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox
except Exception as exc:  # pragma: no cover - Windows Python normally includes Tk
    raise SystemExit(f"Tkinter is required by the source launcher: {exc}")

from core.theme_tokens import theme_tokens


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
        "req={'PySide6':('PySide6',(6,7)),'yt-dlp':('yt_dlp',(2026,6,9)),"
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


def _rgba(value: str) -> tuple[int, int, int, int]:
    text = str(value or "").strip()
    if text.startswith("#") and len(text) in {7, 9}:
        return (
            int(text[1:3], 16),
            int(text[3:5], 16),
            int(text[5:7], 16),
            int(text[7:9], 16) if len(text) == 9 else 255,
        )
    if text.lower().startswith("rgba(") and text.endswith(")"):
        parts = [part.strip() for part in text[5:-1].split(",")]
        if len(parts) == 4:
            try:
                return tuple(max(0, min(255, int(float(part)))) for part in parts)  # type: ignore[return-value]
            except ValueError:
                pass
    if text.lower().startswith("rgb(") and text.endswith(")"):
        parts = [part.strip() for part in text[4:-1].split(",")]
        if len(parts) == 3:
            try:
                return (*tuple(max(0, min(255, int(float(part)))) for part in parts), 255)  # type: ignore[return-value]
            except ValueError:
                pass
    return 0, 0, 0, 255


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(round(a[i] + (b[i] - a[i]) * amount) for i in range(3))  # type: ignore[return-value]


def _flatten(value: str, background: str) -> str:
    r, g, b, alpha = _rgba(value)
    br, bg, bb, _ = _rgba(background)
    ratio = alpha / 255.0
    return _hex((round(br + (r - br) * ratio), round(bg + (g - bg) * ratio), round(bb + (b - bb) * ratio)))


class LauncherSplash(tk.Tk):
    WIDTH = 720
    HEIGHT = 408

    def __init__(self) -> None:
        super().__init__()
        settings = _read_settings()
        self.language = "en" if str(settings.get("language") or "fa").lower() == "en" else "fa"
        self.theme = theme_tokens(str(settings.get("theme") or "youtube"))
        self.version = (APP_DIR / "VERSION").read_text(encoding="utf-8").strip() if (APP_DIR / "VERSION").exists() else ""

        self.title("LeonDL")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.resizable(False, False)
        x = max(0, (self.winfo_screenwidth() - self.WIDTH) // 2)
        y = max(0, (self.winfo_screenheight() - self.HEIGHT) // 2)
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        self._events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._child: subprocess.Popen[str] | None = None
        self._ready_file: Path | None = None
        self._start_time = time.perf_counter()
        self._status_base = self._tr("Starting LeonDL", "در حال شروع LeonDL")
        self._closing = False
        self._alpha = 0.0

        base = _flatten(str(self.theme["background_a"]), "#000000")
        self._transparent_key = "#010203"
        try:
            if os.name == "nt":
                self.wm_attributes("-transparentcolor", self._transparent_key)
        except tk.TclError:
            self._transparent_key = base
        self.configure(bg=self._transparent_key)
        self.canvas = tk.Canvas(self, width=self.WIDTH, height=self.HEIGHT, highlightthickness=0, bd=0, bg=self._transparent_key)
        self.canvas.pack(fill="both", expand=True)
        self._draw_static()

        self.after(0, self._fade_in)
        self.after(16, self._animate)
        self.after(40, self._poll_events)
        threading.Thread(target=self._prepare_and_launch, daemon=True).start()

    def _tr(self, en: str, fa: str) -> str:
        return en if self.language == "en" else fa

    def _rounded_rect(self, x1: float, y1: float, x2: float, y2: float, radius: float, **kwargs: object) -> int:
        points = [
            x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1,
        ]
        return int(self.canvas.create_polygon(points, smooth=True, splinesteps=30, **kwargs))

    def _gradient(self, y1: int, y2: int, left: str, middle: str, right: str) -> None:
        a = _rgba(left)[:3]
        b = _rgba(middle)[:3]
        c = _rgba(right)[:3]
        for y in range(y1, y2):
            ratio = (y - y1) / max(1, y2 - y1 - 1)
            color = _mix(a, b, ratio / 0.53) if ratio <= 0.53 else _mix(b, c, (ratio - 0.53) / 0.47)
            self.canvas.create_line(0, y, self.WIDTH, y, fill=_hex(color))

    def _radial_orb(self, cx: float, cy: float, radius: float, color: str, background: str, strength: float) -> None:
        foreground = _rgba(color)[:3]
        base = _rgba(background)[:3]
        layers = 28
        for index in range(layers, 0, -1):
            ratio = index / layers
            current = radius * ratio
            opacity = strength * (1.0 - ratio) ** 1.8
            fill = _hex(_mix(base, foreground, opacity))
            self.canvas.create_oval(cx - current, cy - current, cx + current, cy + current, fill=fill, outline="")

    def _draw_brand(self, x: int, y: int, size: int = 48) -> None:
        start = _rgba(str(self.theme["primary_end"]))[:3]
        end = _rgba(str(self.theme["primary_start"]))[:3]
        steps = 14
        for index in range(steps):
            ratio = index / max(1, steps - 1)
            inset = index * 0.45
            self._rounded_rect(
                x + inset,
                y + inset,
                x + size - inset,
                y + size - inset,
                max(8, 14 - inset / 3),
                fill=_hex(_mix(start, end, ratio)),
                outline="",
            )
        glyph = str(self.theme["accent_text"])
        self.canvas.create_line(x + 15, y + 13, x + 15, y + 34, fill=glyph, width=3, capstyle=tk.ROUND)
        self.canvas.create_line(x + 15, y + 34, x + 28, y + 34, fill=glyph, width=3, capstyle=tk.ROUND)
        self.canvas.create_line(x + 33, y + 13, x + 33, y + 28, fill=glyph, width=3, capstyle=tk.ROUND)
        self.canvas.create_line(x + 28, y + 23, x + 33, y + 29, fill=glyph, width=3, capstyle=tk.ROUND)
        self.canvas.create_line(x + 38, y + 23, x + 33, y + 29, fill=glyph, width=3, capstyle=tk.ROUND)

    def _mask_rounded_corners(self, x1: int, y1: int, x2: int, y2: int, radius: int) -> None:
        key = self._transparent_key
        for y in range(self.HEIGHT):
            if y < y1 or y > y2:
                self.canvas.create_line(0, y, self.WIDTH, y, fill=key)
                continue
            if y < y1 + radius:
                dy = y - (y1 + radius)
                offset = radius - math.sqrt(max(0.0, radius * radius - dy * dy))
            elif y > y2 - radius:
                dy = y - (y2 - radius)
                offset = radius - math.sqrt(max(0.0, radius * radius - dy * dy))
            else:
                offset = 0.0
            left = int(x1 + offset)
            right = int(x2 - offset)
            if left > 0:
                self.canvas.create_line(0, y, left - 1, y, fill=key)
            if right < self.WIDTH:
                self.canvas.create_line(right + 1, y, self.WIDTH, y, fill=key)

    def _draw_static(self) -> None:
        t = self.theme
        bg_a = _flatten(str(t["background_a"]), "#000000")
        bg_b = _flatten(str(t["background_b"]), bg_a)
        bg_c = _flatten(str(t["background_c"]), bg_a)
        self._gradient(0, self.HEIGHT, bg_a, bg_b, bg_c)

        # Same three ambient colors and positioning family as AuroraSurface.
        self._radial_orb(118, 70, 210, str(t["accent"]), bg_a, 0.20 if t["dark"] else 0.10)
        self._radial_orb(626, 126, 186, str(t["primary_start"]), bg_b, 0.17 if t["dark"] else 0.09)
        self._radial_orb(404, 396, 230, str(t["primary_end"]), bg_c, 0.13 if t["dark"] else 0.07)

        surface = _flatten(str(t["surface"]), bg_b)
        glass = _flatten(str(t["glass_strong"]), surface)
        border = _flatten(str(t["border"]), surface)
        input_bg = _flatten(str(t["input_bg"]), surface)
        control = _flatten(str(t["control_hover"]), surface)
        progress_bg = _flatten(str(t["progress_bg"]), input_bg)
        self._control_color = control
        self._accent_color = str(t["accent"])

        # WindowSurface and the same strong glass hierarchy used by the app.
        self._rounded_rect(10, 10, self.WIDTH - 10, self.HEIGHT - 10, 26, fill="", outline=border, width=1)
        self._rounded_rect(28, 26, self.WIDTH - 28, self.HEIGHT - 26, 22, fill=glass, outline=border, width=1)

        self._draw_brand(54, 50)
        self.canvas.create_text(116, 62, text="LeonDL", anchor="w", fill=str(t["accent_soft"]), font=("Segoe UI", 19, "bold"))
        self.canvas.create_text(116, 91, text=self._tr("Universal media workspace", "فضای هوشمند دانلود رسانه"), anchor="w", fill=str(t["muted"]), font=("Tahoma", 9))

        badge_x1, badge_y1, badge_x2, badge_y2 = 596, 58, 662, 86
        self._rounded_rect(badge_x1, badge_y1, badge_x2, badge_y2, 10, fill=control, outline=border, width=1)
        self.canvas.create_text((badge_x1 + badge_x2) / 2, (badge_y1 + badge_y2) / 2, text=self.version, fill=str(t["accent"]), font=("Segoe UI", 8, "bold"))

        # Command-bar-like loading card mirrors the home page rather than inventing a new UI.
        self._rounded_rect(54, 130, 666, 318, 17, fill=input_bg, outline=border, width=1)
        self.canvas.create_text(80, 161, text=self._tr("Preparing your workspace", "در حال آماده‌سازی فضای کار"), anchor="w", fill=str(t["text"]), font=("Tahoma", 13, "bold"))
        self.canvas.create_text(
            80,
            191,
            text=self._tr("Loading the interface and required environment without opening CMD.", "رابط و محیط موردنیاز بدون نمایش پنجره CMD بارگذاری می‌شوند."),
            anchor="w",
            fill=str(t["muted"]),
            font=("Tahoma", 9),
        )

        self.canvas.create_text(80, 232, text=self._tr("STARTUP", "راه‌اندازی"), anchor="w", fill=str(t["accent"]), font=("Segoe UI", 8, "bold"))
        self._progress_left = 82
        self._progress_right = 638
        self._progress_center_y = 262
        self._progress_width = self._progress_right - self._progress_left
        self._progress_segment = 118.0
        track_fill = _flatten(str(t["progress_bg"]), input_bg)
        self.canvas.create_line(self._progress_left, self._progress_center_y, self._progress_right, self._progress_center_y, fill=track_fill, width=7, capstyle=tk.ROUND)
        self.canvas.create_line(self._progress_left, self._progress_center_y - 2, self._progress_right, self._progress_center_y - 2, fill=control, width=1, capstyle=tk.ROUND)
        self.progress_glow = self.canvas.create_line(self._progress_left + 10, self._progress_center_y, self._progress_left + 110, self._progress_center_y, fill=str(t["accent_hover"]), width=10, capstyle=tk.ROUND)
        self.progress_fill = self.canvas.create_line(self._progress_left + 10, self._progress_center_y, self._progress_left + 110, self._progress_center_y, fill=str(t["accent"]), width=6, capstyle=tk.ROUND)

        self.status_item = self.canvas.create_text(80, 294, text=self._status_base, anchor="w", fill=str(t["text"]), font=("Tahoma", 9))
        self.canvas.create_text(54, 354, text=self._tr("The splash closes when the main window is ready.", "با آماده‌شدن پنجره اصلی، اسپلش خودکار بسته می‌شود."), anchor="w", fill=str(t["muted"]), font=("Tahoma", 8))

        self.dot_items = [self.canvas.create_oval(596 + i * 18, 348, 604 + i * 18, 356, fill=control, outline="") for i in range(3)]
        self._mask_rounded_corners(10, 10, self.WIDTH - 10, self.HEIGHT - 10, 26)

    def _fade_in(self) -> None:
        if not self.winfo_exists() or self._closing:
            return
        self._alpha = min(1.0, self._alpha + 0.09)
        self.attributes("-alpha", self._alpha)
        if self._alpha < 1.0:
            self.after(16, self._fade_in)

    def _fade_out(self) -> None:
        if not self.winfo_exists():
            return
        self._closing = True
        self._alpha = max(0.0, self._alpha - 0.12)
        self.attributes("-alpha", self._alpha)
        if self._alpha <= 0.0:
            self.destroy()
        else:
            self.after(16, self._fade_out)

    def _status(self, text: str) -> None:
        self._events.put(("status", text))

    def _prepare_and_launch(self) -> None:
        if not _environment_ready():
            self._status(self._tr("Preparing the Python environment", "در حال آماده‌سازی محیط Python"))
            if not VENV_PYTHON.exists():
                code, output = _run_hidden([sys.executable, "-m", "venv", str(VENV_DIR)], timeout=600)
                if code != 0:
                    self._events.put(("error", self._tr("Creating the virtual environment failed.", "ساخت محیط مجازی ناموفق بود.") + "\n\n" + output[-2000:]))
                    return

            self._status(self._tr("Preparing core application packages", "در حال آماده‌سازی بسته‌های اصلی برنامه"))
            code, output = _run_hidden([str(VENV_PYTHON), "bootstrap.py", "--skip-external", "--quiet"], timeout=900)
            if code != 0:
                self._events.put(("error", self._tr("Preparing the core application packages failed.", "آماده‌سازی بسته‌های اصلی برنامه ناموفق بود.") + "\n\n" + output[-3000:]))
                return
            try:
                _write_environment_stamp()
            except OSError:
                pass
        else:
            self._status(self._tr("Environment ready; loading the interface", "محیط آماده است؛ در حال بارگذاری رابط"))

        ready_path = Path(tempfile.gettempdir()) / f"leon-ready-{os.getpid()}-{time.time_ns()}.txt"
        ready_path.unlink(missing_ok=True)
        env = os.environ.copy()
        env["LEON_BOOTSTRAP_DONE"] = "1"
        env["LEON_EXTERNAL_SPLASH"] = "1"
        env["LEON_READY_FILE"] = str(ready_path)
        try:
            self._child = subprocess.Popen(
                [str(VENV_PYTHONW), str(APP_DIR / "app.py")],
                cwd=str(APP_DIR),
                env=env,
                text=True,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            self._events.put(("error", self._tr("Launching the application failed:", "اجرای برنامه ناموفق بود:") + f"\n\n{exc}"))
            return
        self._ready_file = ready_path
        self._events.put(("watch", ""))

    def _animate(self) -> None:
        if not self.winfo_exists() or self._closing:
            return
        elapsed = time.perf_counter() - self._start_time
        cycle = 3.1
        phase = (elapsed % cycle) / cycle
        sweep = 0.5 - 0.5 * math.cos(phase * math.tau)
        segment = self._progress_segment + 6.0 * math.sin(elapsed * 0.9)
        travel = self._progress_width - segment - 16
        start = self._progress_left + 8 + sweep * travel
        end = start + segment
        center_y = self._progress_center_y
        self.canvas.coords(self.progress_glow, start - 2, center_y, end + 2, center_y)
        self.canvas.coords(self.progress_fill, start, center_y, end, center_y)

        dots = "." * (int(elapsed * 2.2) % 4)
        self.canvas.itemconfigure(self.status_item, text=self._status_base + dots)
        for index, item in enumerate(self.dot_items):
            active = (int(elapsed * 3.0) + index) % 3 == 0
            self.canvas.itemconfigure(item, fill=self._accent_color if active else self._control_color)
        self.after(16, self._animate)

    def _poll_events(self) -> None:
        try:
            while True:
                kind, text = self._events.get_nowait()
                if kind == "status":
                    self._status_base = text.strip().rstrip(".…") or self._tr("Loading", "در حال بارگذاری")
                elif kind == "error":
                    self.attributes("-topmost", False)
                    messagebox.showerror("LeonDL", text, parent=self)
                    self.destroy()
                    return
                elif kind == "watch":
                    self.after(80, self._watch_child)
        except queue.Empty:
            pass
        if self.winfo_exists() and not self._closing:
            self.after(40, self._poll_events)

    def _watch_child(self) -> None:
        if not self.winfo_exists() or self._closing:
            return
        if self._ready_file and self._ready_file.exists():
            self._ready_file.unlink(missing_ok=True)
            self._fade_out()
            return
        if self._child and self._child.poll() is not None:
            log_path = Path.home() / ".yt_dlp_liquid" / "leon_runtime.log"
            self._events.put(("error", self._tr("The app closed before showing its interface.", "برنامه پیش از نمایش رابط بسته شد.") + f"\n\n{log_path}"))
            return
        self.after(80, self._watch_child)


if __name__ == "__main__":
    LauncherSplash().mainloop()
