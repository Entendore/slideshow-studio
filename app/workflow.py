"""Guided pipeline bar: Import -> Narrate -> Preview -> Export MP4.

A compact horizontal checklist shown above the canvas. It tracks where the
user is on the way from an input file to the finished MP4 video, highlights
the next step, and every chip is a one-click shortcut to that stage.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from . import icons

# (icon, label, tooltip) — one entry per pipeline stage
STEPS = [
    ("import", "1 · Import",
     "Bring slides in: PPTX, PDF, HTML, TXT or Markdown — File ▸ Import "
     "(Ctrl+I), drag & drop onto the window, or File ▸ Import example."),
    ("mic", "2 · Narrate",
     "Give every slide something to say: click to auto-fill empty "
     "narrations from the slide text, then pick a voice in the "
     "Deck & Theme tab."),
    ("play", "3 · Preview",
     "Play the deck (F5) to check the narration, timing and motion "
     "before exporting."),
    ("export", "4 · Export MP4",
     "Render the finished video — click to open the export dialog "
     "(Ctrl+E), or use Quick convert (Ctrl+M) to go straight to MP4."),
]

TIPS = [
    "Next: import slides — File ▸ Import (Ctrl+I), drop a file here, "
    "or try a bundled example.",
    "Next: narrate — click to fill empty narrations from the slide text.",
    "Next: press Play (F5) to preview the deck with narration.",
    "Ready — click Export MP4 (Ctrl+E) or Quick convert (Ctrl+M).",
]


class WorkflowBar(QWidget):
    """Four clickable pipeline chips with done / current / todo states."""

    stepClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(3)

        self._icons = [s[0] for s in STEPS]
        self._chips: list[QToolButton] = []
        for i, (icon_name, label, tip) in enumerate(STEPS):
            if i:
                arrow = QLabel("→")
                arrow.setProperty("wfArrow", True)
                lay.addWidget(arrow)
            chip = QToolButton()
            chip.setText(label)
            chip.setProperty("wfStep", True)
            chip.setProperty("wfState", "todo")
            chip.setIcon(icons.icon(icon_name))
            chip.setIconSize(QSize(15, 15))
            chip.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            chip.setToolTip(tip)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.clicked.connect(lambda _=False, idx=i: self.stepClicked
                                 .emit(idx))
            lay.addWidget(chip)
            self._chips.append(chip)

        lay.addStretch(1)
        self.tip_label = QLabel("")
        self.tip_label.setProperty("hint", True)
        self.tip_label.setToolTip(
            "The studio tracks your progress from imported file to "
            "finished MP4 — click any step to jump to it.")
        lay.addWidget(self.tip_label, 1)

        self._current = -1
        self._done: list[bool] | None = None
        self.set_state([False] * len(STEPS))

    # ------------------------------------------------------------------ #
    def set_state(self, done: list[bool]) -> None:
        """Update chip states; ``current`` = first unfinished step."""
        n = len(self._chips)
        flags = [bool(d) for d in list(done)[:n]]
        flags += [False] * (n - len(flags))
        current = next((i for i, d in enumerate(flags) if not d), n - 1)
        if flags == self._done and current == self._current:
            return                      # nothing changed — skip the restyle
        self._done = flags
        self._current = current
        for i, chip in enumerate(self._chips):
            # the current step wins over "done" so the last chip stays an
            # active invitation once every earlier stage is complete
            if i == current:
                state = "current"
            else:
                state = "done" if flags[i] else "todo"
            if chip.property("wfState") != state:
                chip.setProperty("wfState", state)
            if flags[i]:
                from .styles import tokens
                chip.setIcon(icons.icon("check", tokens()["success"]))
            else:
                chip.setIcon(icons.icon(self._icons[i]))
            st = chip.style()
            st.unpolish(chip)
            st.polish(chip)
        self.tip_label.setText(TIPS[current])

    # accessors (handy for tests) --------------------------------------- #
    def current_step(self) -> int:
        return self._current

    def done_flags(self) -> list[bool]:
        return list(self._done)

    def chips(self) -> list[QToolButton]:
        return list(self._chips)
