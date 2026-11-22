from __future__ import annotations

import math
from collections import deque
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    QSize,
    QPropertyAnimation,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.i18n import tr
from ui.theme import Theme


def _qcolor(value: str) -> QColor:
    """Parse theme colors including Qt stylesheet-style rgb/rgba strings."""
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
            except (TypeError, ValueError):
                pass
    if lowered.startswith("rgb(") and lowered.endswith(")"):
        parts = [part.strip() for part in lowered[4:-1].split(",")]
        if len(parts) == 3:
            try:
                return QColor(*(max(0, min(255, int(float(part)))) for part in parts))
            except (TypeError, ValueError):
                pass
    return QColor(0, 0, 0, 0)


def make_line_icon(name: str, color: str, *, accent: str | None = None, size: int = 24) -> QIcon:
    """Create crisp, theme-aware vector icons without external assets."""
    scale = 4
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(scale, scale)
        pen = QPen(
            QColor(color),
            1.75,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if name == "minimize":
            painter.drawLine(6.5, 15.5, 17.5, 15.5)
        elif name == "maximize":
            painter.drawRoundedRect(QRectF(6.1, 6.1, 11.8, 11.8), 2.0, 2.0)
        elif name == "restore":
            painter.drawRoundedRect(QRectF(8.2, 5.2, 10.3, 10.3), 1.7, 1.7)
            painter.drawRoundedRect(QRectF(5.4, 8.0, 10.3, 10.3), 1.7, 1.7)
        elif name == "close":
            painter.drawLine(7.2, 7.2, 16.8, 16.8)
            painter.drawLine(16.8, 7.2, 7.2, 16.8)
        elif name == "theme":
            accent_color = QColor(accent or color)
            painter.drawEllipse(QRectF(4.8, 4.8, 14.4, 14.4))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent_color)
            painter.drawEllipse(QRectF(7.0, 7.1, 3.8, 3.8))
            painter.drawEllipse(QRectF(13.3, 7.7, 3.0, 3.0))
            painter.drawEllipse(QRectF(10.6, 13.1, 3.7, 3.7))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen)
            painter.drawArc(QRectF(3.4, 3.4, 17.2, 17.2), 24 * 16, 86 * 16)
        elif name == "language":
            painter.drawEllipse(QRectF(4.8, 4.8, 14.4, 14.4))
            painter.drawArc(QRectF(8.0, 4.8, 8.0, 14.4), 90 * 16, 180 * 16)
            painter.drawArc(QRectF(8.0, 4.8, 8.0, 14.4), 270 * 16, 180 * 16)
            painter.drawLine(5.2, 12.0, 18.8, 12.0)
            painter.drawArc(QRectF(5.4, 7.1, 13.2, 9.8), 0, 180 * 16)
            painter.drawArc(QRectF(5.4, 7.1, 13.2, 9.8), 180 * 16, 180 * 16)
        elif name == "preview":
            painter.drawRoundedRect(QRectF(4.4, 6.0, 15.2, 12.0), 2.6, 2.6)
            painter.drawEllipse(QRectF(7.2, 8.8, 3.0, 3.0))
            painter.drawLine(6.6, 16.1, 10.3, 12.8)
            painter.drawLine(10.3, 12.8, 12.9, 14.9)
            painter.drawLine(12.9, 14.9, 17.0, 11.0)
        elif name == "folder":
            painter.drawRoundedRect(QRectF(4.2, 7.1, 15.6, 11.2), 2.3, 2.3)
            painter.drawLine(5.0, 8.4, 9.0, 8.4)
            painter.drawLine(9.0, 8.4, 10.8, 6.1)
            painter.drawLine(10.8, 6.1, 14.7, 6.1)
        elif name == "download":
            painter.drawLine(12.0, 4.4, 12.0, 14.0)
            painter.drawLine(8.2, 10.8, 12.0, 14.6)
            painter.drawLine(15.8, 10.8, 12.0, 14.6)
            painter.drawRoundedRect(QRectF(4.9, 16.1, 14.2, 3.0), 1.5, 1.5)
        elif name == "service":
            painter.drawEllipse(QRectF(4.8, 4.8, 14.4, 14.4))
            painter.drawLine(5.2, 12.0, 18.8, 12.0)
            painter.drawArc(QRectF(8.0, 4.8, 8.0, 14.4), 90 * 16, 180 * 16)
            painter.drawArc(QRectF(8.0, 4.8, 8.0, 14.4), 270 * 16, 180 * 16)
        elif name == "copy":
            painter.drawRoundedRect(QRectF(7.2, 5.0, 11.2, 12.0), 1.8, 1.8)
            painter.drawRoundedRect(QRectF(4.7, 7.8, 11.2, 11.2), 1.8, 1.8)
        elif name == "trash":
            painter.drawRoundedRect(QRectF(7.0, 8.0, 10.0, 11.0), 1.7, 1.7)
            painter.drawLine(5.7, 7.0, 18.3, 7.0)
            painter.drawLine(9.0, 5.0, 15.0, 5.0)
            painter.drawLine(10.0, 10.5, 10.0, 16.0)
            painter.drawLine(14.0, 10.5, 14.0, 16.0)
        elif name == "sparkles":
            painter.drawLine(12.0, 3.8, 12.0, 9.0)
            painter.drawLine(9.4, 6.4, 14.6, 6.4)
            painter.drawLine(7.0, 11.0, 7.0, 15.0)
            painter.drawLine(5.0, 13.0, 9.0, 13.0)
            painter.drawLine(16.6, 12.5, 16.6, 19.2)
            painter.drawLine(13.2, 15.9, 20.0, 15.9)
        elif name == "link":
            painter.drawArc(QRectF(4.2, 8.5, 9.5, 7.5), 38 * 16, 270 * 16)
            painter.drawArc(QRectF(10.3, 8.0, 9.5, 7.5), 218 * 16, 270 * 16)
            painter.drawLine(8.8, 12.3, 15.2, 12.3)
        elif name == "queue":
            painter.drawRoundedRect(QRectF(5.0, 5.2, 14.0, 13.6), 2.2, 2.2)
            painter.drawLine(8.0, 9.0, 16.0, 9.0)
            painter.drawLine(8.0, 12.0, 16.0, 12.0)
            painter.drawLine(8.0, 15.0, 13.5, 15.0)
        elif name == "pulse":
            painter.drawLine(3.8, 12.0, 7.6, 12.0)
            painter.drawLine(7.6, 12.0, 10.0, 7.2)
            painter.drawLine(10.0, 7.2, 13.1, 16.4)
            painter.drawLine(13.1, 16.4, 15.5, 10.5)
            painter.drawLine(15.5, 10.5, 20.2, 10.5)
        elif name == "shield":
            path = QPainterPath()
            path.moveTo(12.0, 4.0)
            path.lineTo(18.2, 6.6)
            path.lineTo(17.4, 13.4)
            path.cubicTo(16.8, 16.6, 14.7, 18.7, 12.0, 20.0)
            path.cubicTo(9.3, 18.7, 7.2, 16.6, 6.6, 13.4)
            path.lineTo(5.8, 6.6)
            path.closeSubpath()
            painter.drawPath(path)
            painter.drawLine(9.2, 12.1, 11.2, 14.1)
            painter.drawLine(11.2, 14.1, 15.2, 9.8)
        elif name == "chevron":
            painter.drawLine(8.0, 10.0, 12.0, 14.0)
            painter.drawLine(12.0, 14.0, 16.0, 10.0)
        elif name == "check":
            painter.drawLine(6.2, 12.0, 10.3, 16.1)
            painter.drawLine(10.3, 16.1, 18.0, 8.0)
        elif name == "search":
            painter.drawEllipse(QRectF(5.3, 5.3, 9.2, 9.2))
            painter.drawLine(13.4, 13.4, 18.5, 18.5)
        elif name == "history":
            painter.drawEllipse(QRectF(4.6, 4.6, 14.8, 14.8))
            painter.drawLine(12.0, 8.0, 12.0, 12.2)
            painter.drawLine(12.0, 12.2, 15.3, 14.0)
            painter.drawLine(8.4, 6.6, 5.6, 6.6)
            painter.drawLine(5.6, 6.6, 6.7, 3.9)
        elif name == "settings":
            painter.drawEllipse(QRectF(9.0, 9.0, 6.0, 6.0))
            for ax, ay, bx, by in [(12,3.8,12,7.0),(12,17.0,12,20.2),(3.8,12,7.0,12),(17.0,12,20.2,12),(6.1,6.1,8.5,8.5),(15.5,15.5,17.9,17.9),(15.5,8.5,17.9,6.1),(6.1,17.9,8.5,15.5)]:
                painter.drawLine(ax, ay, bx, by)
        elif name == "package":
            painter.drawRoundedRect(QRectF(5.0, 7.0, 14.0, 11.5), 2.2, 2.2)
            painter.drawLine(5.8, 10.3, 18.2, 10.3)
            painter.drawLine(12.0, 7.1, 12.0, 18.2)
        elif name == "later":
            painter.drawEllipse(QRectF(4.8, 4.8, 14.4, 14.4))
            painter.drawLine(12.0, 7.5, 12.0, 12.2)
            painter.drawLine(12.0, 12.2, 15.4, 14.2)
            painter.drawLine(17.8, 4.7, 17.8, 9.0)
            painter.drawLine(15.7, 6.8, 19.9, 6.8)
        elif name == "log":
            painter.drawRoundedRect(QRectF(5.0, 4.8, 14.0, 14.4), 2.0, 2.0)
            painter.drawLine(8.0, 9.0, 16.0, 9.0)
            painter.drawLine(8.0, 12.0, 16.0, 12.0)
            painter.drawLine(8.0, 15.0, 13.5, 15.0)
        else:
            painter.drawEllipse(QRectF(6, 6, 12, 12))

    finally:
        if painter.isActive():
            painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


class SpeedWaveWidget(QFrame):
    """Small animated sine/history visualization for the current download speed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("speedWave")
        self.setMinimumHeight(64)
        self.setMaximumHeight(84)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._theme: Theme | None = None
        self._samples: deque[float] = deque([0.0] * 72, maxlen=72)
        self._target_speed = 0.0
        self._smooth_speed = 0.0
        self._peak_speed = 1.0
        self._phase = 0.0
        self._speed_text = "—"
        self._caption = "DOWNLOAD SPEED"
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_caption(self, text: str) -> None:
        self._caption = str(text or "").strip() or "DOWNLOAD SPEED"
        self.update()

    @staticmethod
    def _format_speed(bytes_per_second: float) -> str:
        value = max(0.0, float(bytes_per_second or 0.0))
        units = ("B/s", "KiB/s", "MiB/s", "GiB/s")
        unit_index = 0
        while value >= 1024.0 and unit_index < len(units) - 1:
            value /= 1024.0
            unit_index += 1
        if unit_index == 0:
            return f"{value:.0f} {units[unit_index]}"
        return f"{value:.2f} {units[unit_index]}"

    def set_speed(self, bytes_per_second: object) -> None:
        try:
            speed = max(0.0, float(bytes_per_second or 0.0))
        except (TypeError, ValueError):
            speed = 0.0
        self._target_speed = speed
        self._speed_text = self._format_speed(speed) if speed > 0.0 else "—"
        if speed > self._peak_speed:
            self._peak_speed = speed
        self.setToolTip(self._speed_text)

    def reset(self) -> None:
        self._target_speed = 0.0
        self._smooth_speed = 0.0
        self._peak_speed = 1.0
        self._speed_text = "—"
        self._samples = deque([0.0] * 72, maxlen=72)
        self.update()

    def _tick(self) -> None:
        if not self.isVisible():
            return
        self._smooth_speed += (self._target_speed - self._smooth_speed) * 0.24
        if self._target_speed <= 0.0:
            self._smooth_speed *= 0.88
        self._peak_speed = max(1.0, self._peak_speed * 0.997, self._smooth_speed)
        self._samples.append(self._smooth_speed)
        self._phase = (self._phase + 0.28) % (math.pi * 2)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        theme = self._theme
        if theme is None or self.width() < 8 or self.height() < 8:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
            painter.setPen(QPen(_qcolor(theme.border), 1.0))
            painter.setBrush(_qcolor(theme.input_bg))
            painter.drawRoundedRect(rect, 12.0, 12.0)

            header_h = min(22.0, max(18.0, rect.height() * 0.34))
            rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
            header_left = rect.left() + 11.0
            header_right = rect.right() - 11.0
            header_gap = 14.0
            half_width = max(20.0, (header_right - header_left - header_gap) / 2.0)
            left_rect = QRectF(header_left, rect.top() + 4.0, half_width, header_h - 2.0)
            right_rect = QRectF(header_left + half_width + header_gap, rect.top() + 4.0, half_width, header_h - 2.0)
            caption_rect = right_rect if rtl else left_rect
            value_rect = left_rect if rtl else right_rect

            caption_font = painter.font()
            caption_font.setBold(True)
            caption_font.setPointSizeF(max(7.5, caption_font.pointSizeF() - 0.7))
            painter.setFont(caption_font)
            painter.setPen(_qcolor(theme.muted))
            painter.setLayoutDirection(Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight)
            caption_alignment = (Qt.AlignmentFlag.AlignRight if rtl else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(caption_rect, caption_alignment, self._caption)

            value_font = painter.font()
            value_font.setBold(True)
            value_font.setPointSizeF(max(9.0, value_font.pointSizeF() + 1.0))
            painter.setFont(value_font)
            painter.setPen(_qcolor(theme.accent))
            # Speed values are always Latin/technical text. Force LTR so Qt's
            # bidi layout cannot move them into the Persian caption rectangle.
            painter.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
            value_alignment = (Qt.AlignmentFlag.AlignLeft if rtl else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(value_rect, value_alignment, f"\u2066{self._speed_text}\u2069")

            graph_top = rect.top() + header_h
            graph_height = max(8.0, rect.bottom() - graph_top - 6.0)
            grid_pen = QPen(_qcolor(theme.border), 0.7)
            painter.setPen(grid_pen)
            for factor in (0.33, 0.66):
                y = graph_top + graph_height * factor
                painter.drawLine(QPointF(rect.left() + 8, y), QPointF(rect.right() - 8, y))

            inner_left = rect.left() + 9.0
            inner_right = rect.right() - 9.0
            center_y = graph_top + graph_height / 2.0
            usable_h = max(4.0, graph_height * 0.36)
            peak = max(1.0, self._peak_speed)
            values = list(self._samples)
            count = max(2, len(values))
            path = QPainterPath()
            for index, value in enumerate(values):
                x = inner_left + (inner_right - inner_left) * index / (count - 1)
                normalized = max(0.0, min(1.0, value / peak))
                wave = math.sin(self._phase + index * 0.44)
                y = center_y - wave * usable_h * normalized
                if index == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            wave_pen = QPen(QColor(theme.accent), 2.0)
            wave_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            wave_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(wave_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        finally:
            if painter.isActive():
                painter.end()


class ResponsiveLabel(QLabel):
    """A wrapping label that can shrink in both RTL and LTR layouts."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())


class ElideLabel(QLabel):
    """QLabel that elides its text with an ellipsis when space runs out."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        super().setText(self._full_text)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            rect = self.rect()
            metrics = painter.fontMetrics()
            elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, rect.width())
            painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
            painter.drawText(rect, self.alignment() | Qt.AlignmentFlag.AlignVCenter, elided)
        finally:
            if painter.isActive():
                painter.end()


class AuroraSurface(QFrame):
    """Animated ambient background painted behind the glass dashboard."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme: Theme | None = None
        self._phase = 0.0
        self._reduced_motion = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def set_reduced_motion(self, reduced: bool) -> None:
        """Pause full-surface animation while maximized/fullscreen.

        Repainting several translucent radial gradients across a maximized
        frameless window can overload some Windows graphics drivers.  The
        background remains attractive, but static, in the large-window mode.
        """
        reduced = bool(reduced)
        if self._reduced_motion == reduced:
            return
        self._reduced_motion = reduced
        if reduced:
            self._timer.stop()
        elif self.isVisible():
            self._timer.start()
        self.update()

    def _tick(self) -> None:
        if not self.isVisible() or self._reduced_motion:
            return
        self._phase = (self._phase + 0.012) % (math.pi * 2)
        self.update()

    @staticmethod
    def _transparent(color: str, alpha: int) -> QColor:
        q = QColor(color)
        q.setAlpha(alpha)
        return q

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        theme = self._theme
        if theme is None or self.width() < 20 or self.height() < 20:
            return

        painter = QPainter(self)
        try:

            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0), 26.0, 26.0)
            painter.setClipPath(clip)

            w, h = float(self.width()), float(self.height())
            accent_alpha = 58 if theme.dark else 34
            second_alpha = 46 if theme.dark else 28
            third_alpha = 34 if theme.dark else 20
            orbs = (
                (
                    w * (0.17 + math.sin(self._phase) * 0.025),
                    h * (0.16 + math.cos(self._phase * 0.7) * 0.025),
                    min(w, h) * 0.47,
                    self._transparent(theme.accent, accent_alpha),
                ),
                (
                    w * (0.83 + math.cos(self._phase * 0.8) * 0.025),
                    h * (0.30 + math.sin(self._phase * 0.6) * 0.03),
                    min(w, h) * 0.42,
                    self._transparent(theme.primary_start, second_alpha),
                ),
                (
                    w * (0.54 + math.sin(self._phase * 0.45) * 0.035),
                    h * (0.92 + math.cos(self._phase * 0.55) * 0.018),
                    min(w, h) * 0.52,
                    self._transparent(theme.primary_end, third_alpha),
                ),
            )
            if self._reduced_motion:
                orbs = orbs[:2]
            for cx, cy, radius, center_color in orbs:
                gradient = QRadialGradient(cx, cy, radius)
                gradient.setColorAt(0.0, center_color)
                fade = QColor(center_color)
                fade.setAlpha(0)
                gradient.setColorAt(1.0, fade)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(gradient))
                painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

            # A very subtle diagonal sheen makes the glass feel dimensional without
            # requiring a bundled bitmap/noise texture. Skip it in reduced-motion
            # mode to keep maximized rendering inexpensive and stable.
            if not self._reduced_motion:
                sheen = QLinearGradient(0.0, 0.0, w, h)
                sheen.setColorAt(0.0, QColor(255, 255, 255, 12 if theme.dark else 28))
                sheen.setColorAt(0.42, QColor(255, 255, 255, 0))
                sheen.setColorAt(1.0, QColor(255, 255, 255, 7 if theme.dark else 18))
                painter.setBrush(QBrush(sheen))
                painter.drawRect(self.rect())
        finally:
            if painter.isActive():
                painter.end()


class BrandMark(QWidget):
    """LeonDL wordmark logo in the title bar, tinted per theme.

    Loads ``assets/brand_wordmark_<theme>.png`` (pre-tinted variants for each
    theme) and falls back to the gold original when a variant is missing.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme: Theme | None = None
        self._pixmap: QPixmap | None = None
        self._pad_left = 18
        self._pad_right = 8
        self.setFixedSize(126, 34)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self._load_pixmap()
        self.update()

    def _load_pixmap(self) -> None:
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        theme = self._theme
        candidate = (
            assets_dir / f"brand_wordmark_{theme.name}.png" if theme is not None else assets_dir / "brand_wordmark.png"
        )
        if not candidate.is_file():
            candidate = assets_dir / "brand_wordmark.png"
        if not candidate.is_file():
            self._pixmap = None
            return
        pixmap = QPixmap(str(candidate))
        if pixmap.isNull():
            self._pixmap = None
            return
        target_h = 36
        target_w = max(60, round(pixmap.width() * target_h / pixmap.height()))
        self._pixmap = pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setFixedSize(target_w + self._pad_left + self._pad_right, target_h + 6)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._pixmap is None:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            x = self._pad_left
            y = (self.height() - self._pixmap.height()) // 2
            painter.drawPixmap(x, y, self._pixmap)
        finally:
            if painter.isActive():
                painter.end()


class GlassCard(QFrame):
    def __init__(self, parent: QWidget | None = None, *, strong: bool = False, hoverable: bool = True) -> None:
        super().__init__(parent)
        self._hoverable = hoverable
        self.setProperty("glassStrong" if strong else "glass", True)
        self.setProperty("hovered", False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if strong:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(30)
            shadow.setOffset(0, 10)
            shadow.setColor(QColor(0, 0, 0, 76))
            self.setGraphicsEffect(shadow)

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._hoverable:
            self.setProperty("hovered", True)
            self.style().unpolish(self)
            self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._hoverable:
            self.setProperty("hovered", False)
            self.style().unpolish(self)
            self.style().polish(self)
        super().leaveEvent(event)


class QuickStatPill(QFrame):
    """Compact dashboard metric used in the hero command deck."""

    def __init__(self, title: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("quickStat")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(112)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("quickStatTitle")
        self.value = QLabel(value)
        self.value.setObjectName("quickStatValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, value: str, tooltip: str = "") -> None:
        self.value.setText(value)
        self.value.setToolTip(tooltip or value)


class EmptyStateGraphic(QWidget):
    """Vector empty-state art for the preview pane."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme: Theme | None = None
        self.setFixedSize(104, 74)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        theme = self._theme
        if theme is None:
            return

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            muted = QColor(theme.muted)
            muted.setAlpha(120)
            accent = QColor(theme.accent)
            accent.setAlpha(205)

            muted_pen = QPen(muted)
            muted_pen.setWidthF(1.5)
            painter.setPen(muted_pen)
            painter.setBrush(QColor(255, 255, 255, 8 if theme.dark else 120))
            painter.drawRoundedRect(QRectF(8.0, 12.0, 88.0, 52.0), 13.0, 13.0)

            # PySide6 does not accept ``cap=`` as a QPen constructor keyword.
            # Configure the cap and join styles through setters so this works
            # across supported PySide6 releases.
            accent_pen = QPen(accent)
            accent_pen.setWidthF(2.2)
            accent_pen.setStyle(Qt.PenStyle.SolidLine)
            accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            accent_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(accent_pen)
            painter.drawLine(31.0, 38.0, 45.0, 38.0)
            painter.drawArc(QRectF(20.0, 29.0, 24.0, 18.0), 35 * 16, 290 * 16)
            painter.drawArc(QRectF(43.0, 29.0, 24.0, 18.0), 215 * 16, 290 * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(QRectF(76.0, 20.0, 9.0, 9.0))
        finally:
            # A failed paint must never leave the backing store with an active
            # painter; otherwise Qt can terminate the process on the next resize.
            if painter.isActive():
                painter.end()


class TitleBar(QFrame):
    theme_requested = Signal()
    language_requested = Signal()
    update_requested = Signal()

    def __init__(self, window: QWidget, language: str = "fa") -> None:
        super().__init__(window)
        self.window_ref = window
        self.language = language
        self._drag_offset = QPoint()
        self._theme: Theme | None = None
        self.setObjectName("titleBar")
        self.setFixedHeight(66)

        layout = QHBoxLayout(self)
        layout.setDirection(QBoxLayout.Direction.LeftToRight)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.brand_mark = BrandMark(self)
        self.subtitle_label = ElideLabel()
        self.subtitle_label.setObjectName("appSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.version_badge = QLabel("2.7.0")
        self.version_badge.setObjectName("versionBadge")
        self.version_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self.update_button = QPushButton()
        self.update_button.setObjectName("titleUpdateButton")
        self.update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_button.setFixedHeight(26)
        self.update_button.setIconSize(QSize(14, 14))
        self.update_button.hide()
        self.update_button.clicked.connect(self.update_requested)

        controls = QHBoxLayout()
        controls.setSpacing(5)
        self.language_button = self._button("language", utility=True)
        self.theme_button = self._button("theme", utility=True)
        self.min_button = self._button("minimize")
        self.max_button = self._button("maximize")
        self.close_button = self._button("close")
        self.close_button.setProperty("danger", True)
        self.close_button.setProperty("closeButton", True)
        self.language_button.hide()
        self.theme_button.hide()
        controls.addSpacing(4)
        controls.addWidget(self.min_button)
        controls.addWidget(self.max_button)
        controls.addWidget(self.close_button)

        layout.addWidget(self.brand_mark)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.version_badge)
        layout.addWidget(self.update_button)
        layout.addStretch(1)
        layout.addLayout(controls)

        self.close_button.clicked.connect(window.close)
        self.min_button.clicked.connect(window.showMinimized)
        self.max_button.clicked.connect(self._toggle_maximize)
        self.theme_button.clicked.connect(self.theme_requested)
        self.language_button.clicked.connect(self.language_requested)
        self.set_language(language)

    @staticmethod
    def _button(icon_name: str, *, utility: bool = False) -> QPushButton:
        button = QPushButton()
        button.setProperty("windowButton", True)
        button.setProperty("utilityButton", utility)
        button.setProperty("iconName", icon_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedSize(QSize(38 if utility else 36, 38 if utility else 36))
        button.setIconSize(QSize(21 if utility else 18, 21 if utility else 18))
        return button

    def set_update_available(self, version: str | None) -> None:
        if version:
            self.update_button.setText(f"v{version}")
            if self._theme is not None:
                self.update_button.setIcon(make_line_icon("download", self._theme.accent, size=14))
            self.update_button.setToolTip(
                "Update to v%s" % version if self.language == "en" else f"بروزرسانی به v{version}"
            )
            self.update_button.show()
        else:
            self.update_button.setIcon(QIcon())
            self.update_button.hide()

    def set_language(self, language: str) -> None:
        self.language = "en" if language == "en" else "fa"
        alignment = Qt.AlignmentFlag.AlignLeft
        self.subtitle_label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        self.subtitle_label.setText(tr(self.language, "دانلود سریع و حرفه‌ای با yt-dlp"))
        self.close_button.setToolTip(tr(self.language, "بستن"))
        self.min_button.setToolTip(tr(self.language, "کمینه"))
        self.language_button.setToolTip(tr(self.language, "تغییر زبان"))
        self._update_maximize_icon()
        if self._theme is not None:
            self.theme_button.setToolTip(f"{tr(self.language, 'انتخاب تم')} — {self._theme.label(self.language)}")

    def set_theme(self, theme: Theme, language: str | None = None) -> None:
        if language is not None:
            self.language = language
        self._theme = theme
        normal = theme.text
        self.brand_mark.set_theme(theme)
        self.update_button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.accent};"
            f" border: 1px solid {theme.accent}; border-radius: 11px; padding: 0 10px;"
            f" font-weight: 600; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {theme.accent}22; border-color: {theme.accent}; }}"
        )
        self.min_button.setIcon(make_line_icon("minimize", normal, size=21))
        self.close_button.setIcon(make_line_icon("close", theme.danger, size=21))
        self.theme_button.setIcon(make_line_icon("theme", normal, accent=theme.accent, size=28))
        self.language_button.setIcon(make_line_icon("language", normal, accent=theme.accent, size=28))
        self._update_maximize_icon()
        self.set_language(self.language)

    def _update_maximize_icon(self) -> None:
        color = self._theme.text if self._theme else "#FFFFFF"
        state_reader = getattr(self.window_ref, "is_effectively_maximized", None)
        expanded = bool(state_reader()) if callable(state_reader) else (self.window_ref.isMaximized() or self.window_ref.isFullScreen())
        icon_name = "restore" if expanded else "maximize"
        self.max_button.setIcon(make_line_icon(icon_name, color, size=21))
        tooltip = "بازگردانی اندازه" if expanded else "تمام‌صفحه"
        self.max_button.setToolTip(tr(self.language, tooltip))

    def _toggle_maximize(self) -> None:
        handler = getattr(self.window_ref, "toggle_maximize_restore", None)
        if callable(handler):
            handler()
            return
        if self.window_ref.isMaximized() or self.window_ref.isFullScreen():
            self.window_ref.showNormal()
        else:
            self.window_ref.showMaximized()
        QTimer.singleShot(0, self._update_maximize_icon)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window_ref.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        state_reader = getattr(self.window_ref, "is_effectively_maximized", None)
        expanded = bool(state_reader()) if callable(state_reader) else (self.window_ref.isMaximized() or self.window_ref.isFullScreen())
        if event.buttons() & Qt.MouseButton.LeftButton and not expanded:
            self.window_ref.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
            event.accept()


class Toast(QFrame):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("glassStrong", True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

        layout = QHBoxLayout(self)
        layout.setDirection(QBoxLayout.Direction.LeftToRight)
        layout.setContentsMargins(18, 11, 18, 11)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity_effect)
        self.animation = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.animation.setDuration(240)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._on_animation_finished)
        self._hiding = False

    def show_message(self, text: str, duration_ms: int = 2400) -> None:
        self.label.setText(text)
        self.adjustSize()
        parent_rect = self.parentWidget().rect()
        self.move((parent_rect.width() - self.width()) // 2, 92)
        self.opacity_effect.setOpacity(0.0)
        self.show()
        self.raise_()
        self._hiding = False
        self.animation.stop()
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.start()
        QTimer.singleShot(duration_ms, self.fade_out)

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        self._hiding = True
        self.animation.stop()
        self.animation.setStartValue(self.opacity_effect.opacity())
        self.animation.setEndValue(0.0)
        self.animation.start()

    def _on_animation_finished(self) -> None:
        if self._hiding:
            self.hide()
