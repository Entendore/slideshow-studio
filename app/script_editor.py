"""Whole-deck Script Editor — edit every title, body and narration as one
plain-text document (see app/script_mode.py for the format).

The dialog is non-modal so the canvas updates live while you work. Apply
updates ONLY the words: images, voice settings, motion and durations of
matching slides are preserved; untouched blocks don't even mark the deck
dirty (an Apply right after opening is a no-op).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QFontDatabase
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from .script_mode import deck_to_script, parse_script, script_stats

SCRIPT_FILTER = "Text script (*.txt *.md *.text);;All files (*)"


class ScriptEditorDialog(QDialog):
    """Non-modal editor for the whole deck's text content."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.win = main_window
        self._synced_text: str | None = None
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(880, 720)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # ---- toolbar row ------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(6)
        self.btn_apply = QPushButton("Apply to deck")
        self.btn_apply.setProperty("primary", True)
        self.btn_apply.setToolTip("Parse the script and update the deck "
                                  "(Ctrl+Return)\nImages, voices and motion "
                                  "stay on their slides.")
        self.btn_apply.clicked.connect(self.apply_to_deck)
        self.btn_refresh = QPushButton("Refresh from deck")
        self.btn_refresh.setToolTip("Discard editor edits and reload the "
                                    "deck's current text")
        self.btn_refresh.clicked.connect(lambda: self.refresh())
        self.btn_import = QPushButton("Import script…")
        self.btn_import.setToolTip("Load a .txt script file into this editor")
        self.btn_import.clicked.connect(self._import_dialog)
        self.btn_export = QPushButton("Export script…")
        self.btn_export.setToolTip("Save the script text to a file")
        self.btn_export.clicked.connect(self._export_dialog)
        for b in (self.btn_apply, self.btn_refresh, self.btn_import,
                  self.btn_export):
            row.addWidget(b)
        row.addStretch(1)
        self.stats_label = QLabel("")
        self.stats_label.setProperty("hint", True)
        row.addWidget(self.stats_label)
        lay.addLayout(row)

        # ---- editor ------------------------------------------------------
        self.edit = QPlainTextEdit()
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        f.setPointSize(max(10, f.pointSize()))
        self.edit.setFont(f)
        self.edit.setTabChangesFocus(False)
        self.edit.setPlaceholderText(
            "# Slide title\n"
            "Body text…\n\n"
            "~ Narration spoken by the TTS voice\n\n"
            "---\n\n"
            "# Next slide")
        lay.addWidget(self.edit, 1)

        hint = QLabel(
            "Format:  “# Title” starts a slide  ·  “~ text” is narration  ·  "
            "“---” starts an untitled slide  ·  a leading “\\” escapes  ·  "
            "HTML bodies appear as plain text")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # Ctrl+Return applies
        sc = QShortcut(QKeySequence("Ctrl+Return"), self.edit)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(self.apply_to_deck)

        # live stats (debounced)
        self._stat_timer = QTimer(self)
        self._stat_timer.setSingleShot(True)
        self._stat_timer.setInterval(250)
        self._stat_timer.timeout.connect(self._update_stats)
        self.edit.textChanged.connect(self._stat_timer.start)

        self.set_text(deck_to_script(self.win.deck))

    # ------------------------------------------------------------------ #
    # text access
    # ------------------------------------------------------------------ #
    def text(self) -> str:
        return self.edit.toPlainText()

    def set_text(self, text: str) -> None:
        self.edit.setPlainText(text)
        self._synced_text = text
        self._update_stats()

    # ------------------------------------------------------------------ #
    # sync with the deck
    # ------------------------------------------------------------------ #
    def sync_on_show(self) -> None:
        """Called when the window opens/raises: follow an unchanged deck."""
        self.setWindowTitle(
            f"Script editor — {self.win.deck.name} — Slideshow Studio")
        current = deck_to_script(self.win.deck)
        clean = self.edit.toPlainText() == self._synced_text
        if clean and current != self._synced_text:
            self.set_text(current)
        elif not clean and current != self._synced_text:
            self.stats_label.setText(
                self.stats_label.text() +
                "   ·   deck changed — click “Refresh from deck”")

    def refresh(self, force: bool = False) -> bool:
        """Reload the script from the deck (discards editor edits)."""
        if not force and self.edit.toPlainText() != self._synced_text:
            ret = QMessageBox.question(
                self, "Refresh script",
                "Discard the edits made in the script editor?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                return False
        self.set_text(deck_to_script(self.win.deck))
        return True

    # ------------------------------------------------------------------ #
    # apply
    # ------------------------------------------------------------------ #
    def apply_to_deck(self) -> bool:
        """Parse the script and update the deck's titles/bodies/narrations.

        Returns True when the deck was modified. Slides matched by index
        keep their image, voice, motion and duration; blocks whose text is
        identical to the deck are left completely untouched (so HTML
        formatting survives an idempotent apply).
        """
        parsed = parse_script(self.text())
        if not parsed:
            if self.win.deck.slides:
                # never block: explain in the status bar / stats label
                self.win.statusBar().showMessage(
                    "Nothing to apply — the script has no slide. Every "
                    "slide needs a “# Title” line or a “---” separator.",
                    6000)
                self.stats_label.setText(
                    self.stats_label.text() +
                    "   ·   no slide found — add a “# Title” line")
            return False

        win = self.win
        win._push_undo()
        deck = win.deck
        changed = False
        n = min(len(deck.slides), len(parsed))
        for i in range(n):
            s, p = deck.slides[i], parsed[i]
            if (s.title == p.title and s.body_plain() == p.body
                    and (s.narration or "") == p.narration):
                continue                      # untouched block
            s.title = p.title
            s.body = p.body
            s.body_format = "plain"
            s.narration = p.narration
            changed = True
        if len(deck.slides) > len(parsed):
            del deck.slides[len(parsed):]
            changed = True
        elif len(parsed) > len(deck.slides):
            deck.slides.extend(parsed[len(deck.slides):])
            changed = True

        if not changed:
            # idempotent apply — don't pollute the undo stack
            win._undo_stack.pop()
            win._update_undo_actions()
            win.statusBar().showMessage(
                "Script matches the deck — nothing to apply.", 3000)
            self._synced_text = self.text()
            return False

        win._mark_dirty()
        win.slide_list.set_deck(deck)
        win.canvas.invalidate()
        win._current_index = 0
        win.slide_list.setCurrentRow(0)
        win.canvas.set_index(0)
        win.inspector.set_slide(win.current_slide())
        win._refresh_baseline()
        self._synced_text = self.text()
        win.statusBar().showMessage(
            f"Script applied — {len(deck.slides)} slides in the deck.", 5000)
        return True

    # ------------------------------------------------------------------ #
    # import / export
    # ------------------------------------------------------------------ #
    def import_from(self, path: str) -> None:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            self.set_text(fh.read())
        self.stats_label.setText(self.stats_label.text() +
                                 "   ·   press “Apply to deck” to use it")

    def export_to(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.text())

    def _import_dialog(self) -> None:
        start = self.win.settings.value("last_dir", os.path.expanduser("~"))
        path, _ = QFileDialog.getOpenFileName(self, "Import text script",
                                              start, SCRIPT_FILTER)
        if path:
            self.import_from(path)

    def _export_dialog(self) -> None:
        start = self.win.settings.value("last_dir", os.path.expanduser("~"))
        name = (self.win.deck.name or "deck").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export text script",
            os.path.join(start, name + "_script.txt"), SCRIPT_FILTER)
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".txt"
        self.export_to(path)
        self.win.settings.setValue("last_dir", os.path.dirname(path))
        self.win.statusBar().showMessage(
            f"Script exported — {os.path.basename(path)}", 5000)

    # ------------------------------------------------------------------ #
    def _update_stats(self) -> None:
        st = script_stats(self.text())
        self.stats_label.setText(
            f"{st['slides']} slides · {st['words']} words · "
            f"{st['chars']} chars")

    def closeEvent(self, event) -> None:  # noqa: N802
        self.win.script_dlg = None
        super().closeEvent(event)
