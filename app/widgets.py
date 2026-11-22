"""Small reusable GUI building blocks for the professional layout."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from . import icons


class HRule(QFrame):
    """A subtle horizontal separator line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("hrule", True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(1)


class PanelButton(QToolButton):
    """Compact icon button used in panel headers."""

    def __init__(self, icon_name: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setProperty("panelBtn", True)
        self.setIcon(icons.icon(icon_name))
        self.setIconSize(QSize(16, 16))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAutoRaise(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)


class SectionCard(QWidget):
    """Collapsible card with a chevron header — the backbone of the
    inspector / deck-panel layout."""

    toggled = Signal(bool)

    def __init__(self, title: str, icon_name: str | None = None,
                 collapsed: bool = False, parent=None):
        super().__init__(parent)
        self._collapsed = collapsed
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)

        self.header = QToolButton()
        self.header.setProperty("sectionHeader", True)
        self.header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header.setCheckable(True)
        self.header.setChecked(not collapsed)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
        self._set_header_title(title, icon_name)
        self.header.setArrowType(Qt.ArrowType.DownArrow if not collapsed
                                 else Qt.ArrowType.RightArrow)
        self.header.clicked.connect(self._on_toggle)
        lay.addWidget(self.header)

        self.body = QWidget()
        self._body_lay = QVBoxLayout(self.body)
        self._body_lay.setContentsMargins(2, 2, 2, 6)
        self._body_lay.setSpacing(6)
        lay.addWidget(self.body)
        self.body.setVisible(not collapsed)

    def _set_header_title(self, title: str, icon_name: str | None) -> None:
        label = title.upper()
        self.header.setText(label)
        if icon_name:
            self.header.setIcon(icons.icon(icon_name))
        self.header.setToolTip(title)

    # fluent API ------------------------------------------------------- #
    def add_widget(self, w, stretch: int = 0) -> "SectionCard":
        self._body_lay.addWidget(w, stretch)
        return self

    def add_layout(self, l, stretch: int = 0) -> "SectionCard":
        self._body_lay.addLayout(l, stretch)
        return self

    def add_rule(self) -> "SectionCard":
        self._body_lay.addSpacing(2)
        return self

    def add_stretch(self, stretch: int = 1) -> "SectionCard":
        self._body_lay.addStretch(stretch)
        return self

    # collapse behaviour ------------------------------------------------ #
    def _on_toggle(self, checked: bool) -> None:
        self.set_collapsed(not checked)
        self.toggled.emit(self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.header.setChecked(not collapsed)
        self.header.setArrowType(Qt.ArrowType.DownArrow if not collapsed
                                 else Qt.ArrowType.RightArrow)
        self.body.setVisible(not collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed


def panel_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setProperty("cardTitle", True)
    return lab
