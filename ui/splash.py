from __future__ import annotations

import math
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui.theme import Theme


class StartupSplash(QWidget):
    """Animated startup surface built from the exact active Leon theme."""

    def __init__(self, version: str, language: str, theme: Theme) -> None:
        super().__init__(None)
        self.version = str(version or "").strip()
        self.language = "en" if language == "en" else "fa"
        self.theme = theme
        self.status = self._tr("Starting LeonDL", "در حال شروع LeonDL")
        self._started = time.monotonic()
        self._closing = False
        self._fade: QPropertyAnimation | None = None
        self._static: QPixmap | None = None
        self._static_at = 0.0
        self._logo: QPixmap | None = None
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        icon = root / "assets" / "splash_logo.png"
        pre_trimmed = True
        if not icon.is_file():
            icon = root / "assets" / "app_icon.png"
            pre_trimmed = False
        if icon.is_file():
            raw = QPixmap(str(icon))
            if not raw.isNull():
                if pre_trimmed:
                    self._logo = raw.scaled(
                        240,
                        240,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                else:
                    image = raw.toImage()
                    left = image.width()
                    right = 0
                    top = image.height()
                    bottom = 0
                    for y in range(0, image.height(), 2):
                        for x in range(0, image.width(), 2):
                            if image.pixelColor(x, y).alpha() > 96:
                                if x < left:
                                    left = x
                                if x > right:
                                    right = x
                                if y < top:
                                    top = y
                                if y > bottom:
                                    bottom = y
                    if right > left and bottom > top:
                        inset = int(min(bottom - top, right - left) * 0.06)
                        left = max(0, left - 4)
                        top = max(0, top - 4)
                        right = min(image.width(), right + 4)
                        bottom = min(image.height(), bottom + 4)
                        if inset > 0 and (right - left) > inset * 2 and (bottom - top) > inset * 2:
                            left += inset
                            top += inset
                            right -= inset
                            bottom -= inset
                        raw = raw.copy(left, top, right - left, bottom - top)
                    self._logo = raw.scaled(
                        240,
                        240,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

        self.setFixedSize(720, 408)
        self.setWindowFlags(
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.0)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def _tr(self, en: str, fa: str) -> str:
        return en if self.language == "en" else fa

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().availableGeometry().center())
        geometry = (screen or QGuiApplication.primaryScreen()).availableGeometry()
        self.move(geometry.center() - self.rect().center())
        super().showEvent(event)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.start()

    @staticmethod
    def _color(value: str) -> QColor:
        text = str(value or "").strip()
        color = QColor(text)
        if color.isValid():
            return color
        lowered = text.lower()
        if lowered.startswith("rgba(") and lowered.endswith(")"):
            parts = [part.strip() for part in lowered[5:-1].split(",")]
            if len(parts) == 4:
                try:
                    return QColor(*(max(0, min(255, int(float(part)))) for part in parts))
                except ValueError:
                    pass
        if lowered.startswith("rgb(") and lowered.endswith(")"):
            parts = [part.strip() for part in lowered[4:-1].split(",")]
            if len(parts) == 3:
                try:
                    return QColor(*(max(0, min(255, int(float(part)))) for part in parts))
                except ValueError:
                    pass
        return QColor(0, 0, 0, 0)

    @classmethod
    def _with_alpha(cls, color: str, alpha: int) -> QColor:
        value = cls._color(color)
        value.setAlpha(max(0, min(255, alpha)))
        return value

    def _draw_brand(self, painter: QPainter, rect: QRectF) -> None:
        if self._logo is not None and not self._logo.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(rect, self._logo, QRectF(self._logo.rect()))
            return
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, self._color(self.theme.primary_end))
        gradient.setColorAt(1.0, self._color(self.theme.primary_start))
        painter.setPen(QPen(self._color(self.theme.accent_hover), 1.0))
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 14.0, 14.0)

        x, y = rect.x(), rect.y()
        pen = QPen(self._color(self.theme.accent_text), 3.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(x + 15, y + 13, x + 15, y + 34)
        painter.drawLine(x + 15, y + 34, x + 28, y + 34)
        painter.drawLine(x + 33, y + 13, x + 33, y + 28)
        painter.drawLine(x + 28, y + 23, x + 33, y + 29)
        painter.drawLine(x + 38, y + 23, x + 33, y + 29)

    @staticmethod
    def _round_pen(color: QColor, width: float) -> QPen:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        return pen

    def _ambient_orb(self, painter: QPainter, cx: float, cy: float, radius: float, color: str, alpha: int) -> None:
        gradient = QRadialGradient(cx, cy, radius)
        gradient.setColorAt(0.0, self._with_alpha(color, alpha))
        gradient.setColorAt(1.0, self._with_alpha(color, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            elapsed = time.monotonic() - self._started
            if (
                self._static is None
                or elapsed - self._static_at > 0.4
                or self._static.size() != self.size()
            ):
                self._static = self._render_static(elapsed)
                self._static_at = elapsed
            painter.drawPixmap(0, 0, self._static)

            # Animated progress segment — the only per-tick work.
            # Coordinates mirror the static track: card is inset 24 from frame,
            # frame inset 14 from window, pad 22 inside card -> track at y ~ it+104.
            M = 24.0
            frame = QRectF(self.rect()).adjusted(14.0, 14.0, -14.0, -14.0)
            left = frame.left() + M
            right = frame.right() - M
            top = frame.top() + M
            bottom = frame.bottom() - M
            logo_size = 60.0
            card_top = top + logo_size + 22
            card = QRectF(left, card_top, right - left, bottom - card_top - 8)
            pad = 22.0
            il = card.left() + pad
            ir = card.right() - pad
            it = card.top() + pad
            track_left = il + 2
            track_right = ir - 2
            track_y = it + 104.0
            track_width = track_right - track_left
            cycle = 3.1
            phase = (elapsed % cycle) / cycle
            sweep = 0.5 - 0.5 * math.cos(phase * math.tau)
            segment = 118.0 + 6.0 * math.sin(elapsed * 0.9)
            start = track_left + 8 + sweep * (track_width - segment - 16)
            end = start + segment
            painter.setPen(self._round_pen(self._with_alpha(self.theme.accent_hover, 168 if self.theme.dark else 132), 10.0))
            painter.drawLine(start - 2, track_y, end + 2, track_y)
            painter.setPen(self._round_pen(self._color(self.theme.accent), 6.0))
            painter.drawLine(start, track_y, end, track_y)

            painter.setPen(self._color(self.theme.text))
            status_font = QFont("Tahoma", 9)
            painter.setFont(status_font)
            dots = "." * (int(elapsed * 2.2) % 4)
            painter.drawText(QRectF(il, track_y + 16, track_width, 28), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.status.rstrip(".…") + dots)
        finally:
            if painter.isActive():
                painter.end()

    def _render_static(self, elapsed: float) -> QPixmap:
        # Render at device-pixel-ratio resolution so text and artwork stay
        # crisp on HiDPI displays (a logical-size cache gets upscaled -> blur).
        dpr = self.devicePixelRatioF() or 1.0
        width = max(1, int(round(self.width() * dpr)))
        height = max(1, int(round(self.height() * dpr)))
        # Outer window frame: 14px margin, 24px radius.
        frame = QRectF(self.rect()).adjusted(14.0, 14.0, -14.0, -14.0)
        outer_radius = 24.0
        clip = QPainterPath()
        clip.addRoundedRect(frame, outer_radius, outer_radius)

        static = QPixmap(width, height)
        static.setDevicePixelRatio(dpr)
        static.fill(Qt.GlobalColor.transparent)
        painter = QPainter(static)
        painter.scale(dpr, dpr)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # Background fill.
            background = QLinearGradient(frame.topLeft(), frame.bottomRight())
            background.setColorAt(0.0, self._color(self.theme.background_a))
            background.setColorAt(0.53, self._color(self.theme.background_b))
            background.setColorAt(1.0, self._color(self.theme.background_c))
            painter.fillPath(clip, background)

            # Ambient orbs (subtle, behind content).
            accent_alpha = 58 if self.theme.dark else 34
            second_alpha = 46 if self.theme.dark else 28
            third_alpha = 34 if self.theme.dark else 20
            self._ambient_orb(painter, 118 + math.sin(elapsed * 0.7) * 7, 70 + math.cos(elapsed * 0.55) * 5, 210, self.theme.accent, accent_alpha)
            self._ambient_orb(painter, 626 + math.cos(elapsed * 0.6) * 6, 126 + math.sin(elapsed * 0.5) * 6, 186, self.theme.primary_start, second_alpha)
            self._ambient_orb(painter, 404 + math.sin(elapsed * 0.45) * 8, 396 + math.cos(elapsed * 0.4) * 4, 230, self.theme.primary_end, third_alpha)

            # Top sheen.
            sheen = QLinearGradient(frame.topLeft(), frame.bottomRight())
            sheen.setColorAt(0.0, QColor(255, 255, 255, 12 if self.theme.dark else 28))
            sheen.setColorAt(0.42, QColor(255, 255, 255, 0))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 7 if self.theme.dark else 18))
            painter.fillPath(clip, sheen)

            # Outer border.
            painter.setClipping(False)
            painter.setPen(QPen(self._color(self.theme.border), 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(frame, outer_radius, outer_radius)

            # Content margins (safe area inside the frame).
            M = 24.0            # outer margin
            left = frame.left() + M
            right = frame.right() - M
            top = frame.top() + M
            bottom = frame.bottom() - M
            content_w = right - left

            # --- Header (logo + title + subtitle + version badge) ---
            logo_size = 60.0
            self._draw_brand(painter, QRectF(left, top, logo_size, logo_size))

            title = QFont("Segoe UI", 19)
            title.setBold(True)
            painter.setPen(self._color(self.theme.accent_soft))
            painter.setFont(title)
            painter.drawText(QRectF(left + logo_size + 14, top + 6, 360, 30), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "LeonDL")

            subtitle = QFont("Tahoma", 9)
            painter.setPen(self._color(self.theme.muted))
            painter.setFont(subtitle)
            painter.drawText(QRectF(left + logo_size + 14, top + 36, 380, 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._tr("Universal media workspace", "فضای هوشمند دانلود رسانه"))

            badge_w = 64.0
            badge = QRectF(right - badge_w, top + 4, badge_w, 26)
            painter.setPen(QPen(self._color(self.theme.border), 1.0))
            painter.setBrush(self._color(self.theme.control_hover))
            painter.drawRoundedRect(badge, 9.0, 9.0)
            badge_font = QFont("Segoe UI", 8)
            badge_font.setBold(True)
            painter.setPen(self._color(self.theme.accent))
            painter.setFont(badge_font)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.version)

            # --- Inner content card (centered, fully inside frame) ---
            card_top = top + logo_size + 22
            card = QRectF(left, card_top, content_w, bottom - card_top - 8)
            painter.setPen(QPen(self._color(self.theme.border), 1.0))
            painter.setBrush(self._color(self.theme.glass_strong))
            painter.drawRoundedRect(card, 18.0, 18.0)

            # Inner padding.
            pad = 22.0
            il = card.left() + pad
            ir = card.right() - pad
            it = card.top() + pad
            ib = card.bottom() - pad
            inner_w = ir - il

            heading = QFont("Tahoma", 13)
            heading.setBold(True)
            painter.setPen(self._color(self.theme.text))
            painter.setFont(heading)
            painter.drawText(QRectF(il, it, inner_w, 30), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._tr("Preparing your workspace", "در حال آماده‌سازی فضای کار"))

            body = QFont("Tahoma", 9)
            painter.setPen(self._color(self.theme.muted))
            painter.setFont(body)
            painter.drawText(QRectF(il, it + 34, inner_w, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._tr("Loading the interface without opening a console window.", "رابط برنامه بدون نمایش پنجره CMD بارگذاری می‌شود."))

            label_font = QFont("Segoe UI", 8)
            label_font.setBold(True)
            painter.setPen(self._color(self.theme.accent))
            painter.setFont(label_font)
            painter.drawText(QRectF(il, it + 72, 120, 18), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._tr("STARTUP", "راه‌اندازی"))

            # Progress track (inside card, with padding from edges).
            track_left = il + 2
            track_right = ir - 2
            track_y = it + 104
            painter.setPen(self._round_pen(self._color(self.theme.progress_bg), 7.0))
            painter.drawLine(track_left, track_y, track_right, track_y)
            painter.setPen(self._round_pen(self._with_alpha(self.theme.control_hover, 120 if self.theme.dark else 86), 1.0))
            painter.drawLine(track_left, track_y - 2, track_right, track_y - 2)

            # Footer note (inside frame, below the card, centered).
            footer = QFont("Tahoma", 8)
            painter.setPen(self._color(self.theme.muted))
            painter.setFont(footer)
            footer_rect = QRectF(left, bottom - 24, content_w, 22)
            painter.drawText(footer_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter, self._tr("The splash closes when the main window is ready.", "با آماده‌شدن پنجره اصلی، اسپلش خودکار بسته می‌شود."))
        finally:
            if painter.isActive():
                painter.end()
        return static

    def set_status(self, text: str) -> None:
        self.status = str(text or "").strip() or self.status
        self.update()

    def finish(self, window: QWidget) -> None:
        del window
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade.finished.connect(self.close)
        self._fade.start()
