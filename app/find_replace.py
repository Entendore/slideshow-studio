"""Find & Replace across slide titles, bodies and narrations.

Searching always works on the readable text of a slide (HTML bodies are
searched via their plain-text form). Replacing is format aware:

* plain fields (title, narration, plain bodies) get direct span replaces
* HTML bodies are edited **inside text nodes only** (BeautifulSoup), so
  tags, attributes and their names/urls can never be corrupted.

The dialog is non-modal; "Find next" jumps the main window to the
matching slide.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

FIELDS = ("title", "body", "narration")
_DROP_GUARD = {"script", "style"}


# --------------------------------------------------------------------- #
# pure helpers (unit-testable)
# --------------------------------------------------------------------- #
def replace_in_html(html: str, needle: str, repl: str,
                    case_sensitive: bool = True) -> tuple[str, int]:
    """Replace *needle* inside the TEXT of an HTML fragment.

    Tags and attributes are never touched. Returns (new_html, count).
    """
    if not html or not needle or "<" not in html:
        return html, 0
    from bs4 import BeautifulSoup, NavigableString

    soup = BeautifulSoup(html, "html.parser")
    flags = 0 if case_sensitive else re.IGNORECASE
    pat = re.compile(re.escape(needle), flags)
    n = 0
    for node in soup.find_all(string=True):
        # never edit inside <script>/<style> remnants
        p, skip = node.parent, False
        while p is not None:
            if getattr(p, "name", None) in _DROP_GUARD:
                skip = True
                break
            p = p.parent
        if skip:
            continue
        t = str(node)
        if pat.search(t):
            n += len(pat.findall(t))
            node.replace_with(NavigableString(pat.sub(lambda m: repl, t)))
    if not n:
        return html, 0
    return soup.decode(), n


def replace_in_slide(slide, needle: str, repl: str,
                     case_sensitive: bool = True) -> int:
    """Replace every occurrence of *needle* in one slide. Returns count."""
    if not needle:
        return 0
    flags = 0 if case_sensitive else re.IGNORECASE
    pat = re.compile(re.escape(needle), flags)
    n = 0

    def sub(text: str) -> str:
        nonlocal n
        n += len(pat.findall(text))
        return pat.sub(lambda m: repl, text)

    if slide.title and pat.search(slide.title):
        slide.title = sub(slide.title)
    if slide.narration and pat.search(slide.narration):
        slide.narration = sub(slide.narration)
    if not slide.body:
        return n
    if slide.body_is_html():
        new, k = replace_in_html(slide.body, needle, repl, case_sensitive)
        if k:
            slide.body = new
            n += k
    elif pat.search(slide.body):
        slide.body = sub(slide.body)
    return n


# --------------------------------------------------------------------- #
# dialog
# --------------------------------------------------------------------- #
class FindReplaceDialog(QDialog):
    """Non-modal find/replace bar for the whole deck."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.win = main_window
        self._cursor = None            # (slide_idx, field, start) | None
        self.setModal(False)
        self.setWindowTitle("Find & replace — Slideshow Studio")
        self.setMinimumWidth(520)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Find"))
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("text to find…")
        self.find_edit.returnPressed.connect(self.find_next)
        r1.addWidget(self.find_edit, 1)
        self.case_box = QCheckBox("Match case")
        r1.addWidget(self.case_box)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Replace with"))
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("replacement…")
        r2.addWidget(self.replace_edit, 1)
        lay.addLayout(r2)

        r3 = QHBoxLayout()
        self.btn_find = QPushButton("Find next")
        self.btn_replace_slide = QPushButton("Replace in this slide")
        self.btn_replace_all = QPushButton("Replace all")
        self.btn_replace_all.setProperty("primary", True)
        self.btn_find.clicked.connect(self.find_next)
        self.btn_replace_slide.clicked.connect(self.replace_current)
        self.btn_replace_all.clicked.connect(self.replace_all)
        r3.addWidget(self.btn_find)
        r3.addWidget(self.btn_replace_slide)
        r3.addWidget(self.btn_replace_all)
        r3.addStretch(1)
        lay.addLayout(r3)

        self.status_label = QLabel("Searches titles, bodies and narrations.")
        self.status_label.setProperty("hint", True)
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

    # ------------------------------------------------------------------ #
    # matching
    # ------------------------------------------------------------------ #
    def _pattern(self):
        needle = self.find_edit.text()
        if not needle:
            return None
        flags = 0 if self.case_box.isChecked() else re.IGNORECASE
        return re.compile(re.escape(needle), flags)

    def _matches(self) -> list[tuple[int, str, int, int]]:
        pat = self._pattern()
        if not pat:
            return []
        out: list[tuple[int, str, int, int]] = []
        for i, s in enumerate(self.win.deck.slides):
            for field, text in (("title", s.title or ""),
                                ("body", s.body_plain() or ""),
                                ("narration", s.narration or "")):
                for m in pat.finditer(text):
                    out.append((i, field, m.start(), m.end()))
        return out

    def count_matches(self) -> int:
        return len(self._matches())

    # ------------------------------------------------------------------ #
    # navigation
    # ------------------------------------------------------------------ #
    def find_next(self) -> bool:
        matches = self._matches()
        if not matches:
            self._cursor = None
            self.status_label.setText(
                f"No matches for “{self.find_edit.text()}”.")
            return False
        order = {f: k for k, f in enumerate(FIELDS)}
        cur = self._cursor
        nxt, wrapped = None, False
        for m in matches:
            if cur is None or (m[0], order[m[1]], m[2]) > \
                    (cur[0], order.get(cur[1], 0), cur[2]):
                nxt = m
                break
        if nxt is None:
            nxt, wrapped = matches[0], True
        self._cursor = (nxt[0], nxt[1], nxt[2])
        self._jump(nxt[0])
        s = self.win.deck.slides[nxt[0]]
        where = {"title": "title", "body": "body",
                 "narration": "narration"}[nxt[1]]
        k = matches.index(nxt) + 1
        self.status_label.setText(
            f"Match {k} of {len(matches)} — slide {nxt[0] + 1}, {where}"
            f"{' — wrapped' if wrapped else ''}"
            f"  ({s.title or 'untitled'})")
        return True

    def _jump(self, idx: int) -> None:
        win = self.win
        win._current_index = idx
        win.slide_list.blockSignals(True)
        win.slide_list.setCurrentRow(idx)
        win.slide_list.blockSignals(False)
        win.canvas.set_index(idx)
        win.inspector.set_slide(win.current_slide())

    # ------------------------------------------------------------------ #
    # replacing
    # ------------------------------------------------------------------ #
    def replace_current(self) -> bool:
        needle = self.find_edit.text()
        if not needle:
            self.status_label.setText("Type the text to find first.")
            return False
        win = self.win
        idx = win.current_index()
        if not (0 <= idx < len(win.deck.slides)):
            return False
        win._push_undo()
        n = replace_in_slide(win.deck.slides[idx], needle,
                             self.replace_edit.text(),
                             self.case_box.isChecked())
        if n:
            self._after_replace(f"Replaced {n} occurrence"
                                f"{'s' if n != 1 else ''} in slide {idx + 1}.",
                                refresh_all=False)
        else:
            win._undo_stack.pop()
            win._update_undo_actions()
            self.status_label.setText(
                f"“{needle}” does not occur in the current slide.")
        return n > 0

    def replace_all(self) -> bool:
        needle = self.find_edit.text()
        if not needle:
            self.status_label.setText("Type the text to find first.")
            return False
        win = self.win
        win._push_undo()
        total, slides_hit = 0, 0
        for s in win.deck.slides:
            n = replace_in_slide(s, needle, self.replace_edit.text(),
                                 self.case_box.isChecked())
            if n:
                slides_hit += 1
                total += n
        if not total:
            win._undo_stack.pop()
            win._update_undo_actions()
            self.status_label.setText(
                f"“{needle}” does not occur in the deck.")
            return False
        self._after_replace(
            f"Replaced {total} occurrence{'s' if total != 1 else ''} "
            f"on {slides_hit} slide{'s' if slides_hit != 1 else ''}.",
            refresh_all=True)
        return True

    def _after_replace(self, message: str, refresh_all: bool) -> None:
        win = self.win
        self._cursor = None
        win._mark_dirty()
        win.canvas.invalidate()
        if refresh_all:
            win.slide_list.refresh(keep_current=True)
        else:
            win.slide_list.update_thumb(win.current_index())
        win.inspector.set_slide(win.current_slide())
        win._refresh_baseline()
        self.status_label.setText(message)

    # ------------------------------------------------------------------ #
    def showEvent(self, event) -> None:  # noqa: N802
        self.find_edit.setFocus()
        self.find_edit.selectAll()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.win.find_dlg = None
        super().closeEvent(event)
