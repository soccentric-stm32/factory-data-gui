"""Custom widgets for the factory data GUI.

Everything painted here reads the current theme tokens at paint time, so a
light/dark switch only needs update().  Every Qt name used inside a
paintEvent is imported at the top: an exception there aborts the process.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import (
    QPointF,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import icons
from . import soc_theme as theme

# Fits the longest row label ("Chip UID binding") with room to spare.
ROW_LABEL_WIDTH = 152


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t))


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_tone(label: QLabel, tone: str) -> None:
    """Pill/Hint colour: '', accent, success, warning or danger."""
    if label.property("tone") != tone:
        label.setProperty("tone", tone)
        repolish(label)


def label(text: str, name: str, parent: QWidget | None = None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setObjectName(name)
    return widget


def hairline() -> QFrame:
    line = QFrame()
    line.setObjectName("Hairline")
    line.setFixedHeight(1)
    return line


class ElidedLabel(QLabel):
    """Single-line label that elides in the middle and shows a tooltip."""

    def __init__(self, text: str = "", name: str = "Hint",
                 mode: Qt.TextElideMode = Qt.ElideMiddle) -> None:
        super().__init__()
        self.setObjectName(name)
        self._full = ""
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(40)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text
        self.setToolTip(text if text else "")
        self._elide()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, self._mode,
                                           max(self.width(), 40)))


class Card(QFrame):
    """Grouped surface: optional title row, then rows split by hairlines."""

    def __init__(self, title: str = "", trailing: QWidget | None = None) -> None:
        super().__init__()
        self.setObjectName("Card")
        self._box = QVBoxLayout(self)
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(0)
        self._rows = 0
        if title:
            head = QHBoxLayout()
            head.setContentsMargins(16, 12, 12, 8)
            head.setSpacing(8)
            head.addWidget(label(title, "CardTitle"))
            head.addStretch(1)
            if trailing is not None:
                head.addWidget(trailing)
            self._box.addLayout(head)

    def add_row(self, title: str | None, *items, stretch: int = -1,
                align_top: bool = False) -> QWidget:
        """One row: a fixed-width label, then widgets (None = stretch)."""
        if self._rows:
            self._box.addWidget(hairline())
        self._rows += 1
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        if title is not None:
            name = label(title, "RowLabel")
            name.setFixedWidth(ROW_LABEL_WIDTH)
            layout.addWidget(name, 0, Qt.AlignTop if align_top else
                             Qt.AlignVCenter)
        for index, item in enumerate(items):
            if item is None:
                layout.addStretch(1)
            elif isinstance(item, QWidget):
                layout.addWidget(item, 1 if index == stretch else 0)
            else:
                layout.addLayout(item, 1 if index == stretch else 0)
        self._box.addWidget(row)
        return row

    def add_widget(self, widget: QWidget) -> None:
        if self._rows:
            self._box.addWidget(hairline())
        self._rows += 1
        self._box.addWidget(widget)


def field(*widgets: QWidget, spacing: int = 4) -> QVBoxLayout:
    """Stack an input over its hint."""
    column = QVBoxLayout()
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(spacing)
    for widget in widgets:
        column.addWidget(widget)
    return column


class NavItem(QAbstractButton):
    """Sidebar entry: icon, title, subtitle and a status dot."""

    TONES: ClassVar[dict[str, str]] = {"": "text_tertiary", "success": "success", "warning": "warning",
             "accent": "accent", "danger": "danger"}

    def __init__(self, icon_name: str, title: str, subtitle: str) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover)
        self.icon_name = icon_name
        self.title = title
        self.subtitle = subtitle
        self.status_tone = ""
        self.status_filled = False
        self.setToolTip(f"{title} · {subtitle}")

    def set_status(self, tone: str, filled: bool, tip: str = "") -> None:
        self.status_tone = tone
        self.status_filled = filled
        self.setToolTip(f"{self.title} · {self.subtitle}" +
                        (f"\n{tip}" if tip else ""))
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(200, 48)

    def paintEvent(self, _event) -> None:
        t = theme.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        checked = self.isChecked()
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t.accent))
            painter.drawRoundedRect(rect, 8, 8)
        elif self.underMouse():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 14) if not t.dark
                             else QColor(255, 255, 255, 18))
            painter.drawRoundedRect(rect, 8, 8)
        if self.hasFocus() and not checked:
            painter.setPen(QPen(QColor(t.accent), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)

        fg = t.on_accent if checked else t.text
        secondary = QColor(t.on_accent if checked else t.text_secondary)
        if checked:
            secondary.setAlphaF(0.82)
        icons.paint(painter, self.icon_name,
                    QRectF(12, (rect.height() - 18) / 2, 18, 18),
                    t.on_accent if checked else t.text_secondary, 1.8)

        text_left = 42
        dot_space = 22
        width = rect.width() - text_left - dot_space
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold if checked else QFont.Medium)
        painter.setFont(font)
        painter.setPen(QColor(fg))
        metrics = QFontMetrics(font)
        painter.drawText(QRectF(text_left, 7, width, 18),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         metrics.elidedText(self.title, Qt.ElideRight,
                                            int(width)))
        small = QFont(self.font())
        small.setPixelSize(11)
        painter.setFont(small)
        painter.setPen(secondary)
        painter.drawText(QRectF(text_left, 25, width, 16),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(small).elidedText(
                             self.subtitle, Qt.ElideRight, int(width)))

        dot = QColor(getattr(t, self.TONES.get(self.status_tone,
                                                "text_tertiary")))
        if checked:
            dot = QColor(t.on_accent)
        centre = QPointF(rect.width() - 14, rect.height() / 2)
        if self.status_filled:
            painter.setPen(Qt.NoPen)
            painter.setBrush(dot)
        else:
            painter.setPen(QPen(dot, 1.5))
            painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(centre, 3.5, 3.5)
