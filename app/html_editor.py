"""Rich-text body editor with three interchangeable views.

* Visual  -- QTextEdit with a formatting toolbar (bold/italic/lists/colors…)
* Source  -- raw HTML editing of the sanitised subset used by the renderer
* Plain   -- old plain-text mode (blank line = paragraph)

All three write back to ``Slide.body`` + ``Slide.body_format``. Content is
always stored through app.htmlfmt.sanitize_html, so pastes and typed markup
can never smuggle scripts, event handlers or external resources into a deck.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QKeySequence, QTextBlockFormat,
                           QTextCharFormat, QTextCursor, QTextListFormat,
                           QShortcut)
from PySide6.QtWidgets import (QColorDialog, QComboBox, QHBoxLayout, QLabel,
                               QInputDialog, QPlainTextEdit, QPushButton,
                               QStackedWidget, QTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

from . import htmlfmt

MODES = ("Visual", "HTML source", "Plain text")
MODE_KEYS = ("visual", "source", "plain")

_EDITOR_CSS = (
    "a { color: #4da3ff; text-decoration: underline; } "
    "h1 { font-size: 1.3em; font-weight: bold; } "
    "h2 { font-size: 1.18em; font-weight: bold; } "
    "h3 { font-size: 1.08em; font-weight: bold; } "
    "blockquote { margin-left: 22px; color: #9fb2c4; } "
)


class _VisualEdit(QTextEdit):
    """Rich editor that sanitises everything that gets pasted in."""

    def __init__(self, owner: "HtmlBodyEditor", parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setAcceptRichText(True)
        self.document().setDefaultStyleSheet(_EDITOR_CSS)
        f = self.font()
        f.setPointSize(11)
        self.setFont(f)

    def insertFromMimeData(self, source) -> None:  # noqa: N802
        if source.hasHtml():
            clean = htmlfmt.sanitize_html(source.html())
            if clean:
                self.textCursor().insertHtml(clean)
                self._owner.changed.emit()
                return
        if source.hasText():
            # plain paste: newlines become paragraph breaks visually
            text = source.text()
            cursor = self.textCursor()
            cursor.beginEditBlock()
            for i, line in enumerate(text.replace("\r\n", "\n").split("\n")):
                if i:
                    if not line.strip():
                        cursor.insertBlock()
                        continue
                    cursor.insertBlock()
                cursor.insertText(line)
            cursor.endEditBlock()
            self._owner.changed.emit()
            return
        super().insertFromMimeData(source)


class HtmlBodyEditor(QWidget):
    """Slide body editor: visual / HTML source / plain text."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._mode = "visual"
        self._build()
        self._connect()

    # ================================================================== #
    # construction
    # ================================================================== #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        # ---- toolbar -------------------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(3)
        self.btn_bold = self._tool("B", "Bold (Ctrl+B)")
        bf = self.btn_bold.font()
        bf.setBold(True)
        self.btn_bold.setFont(bf)
        self.btn_italic = self._tool("I", "Italic (Ctrl+I)")
        itf = self.btn_italic.font()
        itf.setItalic(True)
        self.btn_italic.setFont(itf)
        self.btn_under = self._tool("U", "Underline (Ctrl+U)")
        uf = self.btn_under.font()
        uf.setUnderline(True)
        self.btn_under.setFont(uf)
        self.btn_strike = self._tool("S", "Strikethrough")
        sf = self.btn_strike.font()
        sf.setStrikeOut(True)
        self.btn_strike.setFont(sf)
        for b in (self.btn_bold, self.btn_italic, self.btn_under,
                  self.btn_strike):
            bar.addWidget(b)
        self._sep(bar)
        self.btn_ulist = self._tool("• —", "Bullet list")
        self.btn_olist = self._tool("1. —", "Numbered list")
        bar.addWidget(self.btn_ulist)
        bar.addWidget(self.btn_olist)
        self._sep(bar)
        self.btn_left = self._tool("L", "Align left")
        self.btn_center = self._tool("C", "Align centre")
        self.btn_right = self._tool("R", "Align right")
        for b in (self.btn_left, self.btn_center, self.btn_right):
            bar.addWidget(b)
        self._sep(bar)
        self.btn_color = self._tool("A", "Text colour …")
        self.btn_color.setStyleSheet("color:#ffb86b; font-weight:bold;")
        self.btn_mark = self._tool("H", "Highlight …")
        self.btn_clear = self._tool("✕", "Clear formatting")
        self.btn_link = self._tool("🔗", "Insert / edit link …")
        for b in (self.btn_color, self.btn_mark, self.btn_clear,
                  self.btn_link):
            bar.addWidget(b)
        bar.addStretch(1)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.setToolTip("Visual editor, raw HTML source, or the "
                                   "plain-text mode")
        bar.addWidget(self.mode_combo)
        lay.addLayout(bar)

        # ---- stacked editors ------------------------------------------
        self.stack = QStackedWidget()
        self.visual = _VisualEdit(self)
        self.visual.setPlaceholderText("Slide body …")
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText(
            "<p>Paragraph</p>\n<b>bold</b> <i>italic</i>\n"
            "<ul><li>list item</li></ul>\n<h2>heading</h2>")
        mono = QFont("Consolas, 'DejaVu Sans Mono', monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self.source.setFont(mono)
        self.plain_edit = QTextEdit()
        self.plain_edit.setAcceptRichText(False)
        self.plain_edit.setPlaceholderText(
            "Plain text — blank line starts a new paragraph …")
        f = self.plain_edit.font()
        f.setPointSize(11)
        self.plain_edit.setFont(f)
        for w in (self.visual, self.source, self.plain_edit):
            w.setMinimumHeight(120)
            self.stack.addWidget(w)
        self.stack.setCurrentWidget(self.visual)
        lay.addWidget(self.stack, 1)

        # ---- hint -------------------------------------------------------
        self.hint = QLabel("")
        self.hint.setProperty("hint", True)
        self.hint.setWordWrap(True)
        self.hint.setText("Rich text: bold, colours, lists … HTML source "
                          "supports p, h1-h3, b i u s, ul/ol/li, blockquote, "
                          "a, span style=color.")
        lay.addWidget(self.hint)

        # keyboard shortcuts inside the visual editor
        for seq, fn in (("Ctrl+B", self._do_bold), ("Ctrl+I", self._do_italic),
                        ("Ctrl+U", self._do_under)):
            sc = QShortcut(QKeySequence(seq), self.visual)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(fn)

    @staticmethod
    def _sep(bar: QHBoxLayout) -> None:
        w = QWidget()
        w.setFixedWidth(1)
        w.setStyleSheet("background:#38424f; margin: 2px 3px;")
        bar.addWidget(w)

    def _tool(self, text: str, tip: str) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(False)
        b.setAutoRaise(True)
        b.setFixedWidth(34)
        return b

    # ================================================================== #
    # wiring
    # ================================================================== #
    def _connect(self) -> None:
        self.btn_bold.clicked.connect(self._do_bold)
        self.btn_italic.clicked.connect(self._do_italic)
        self.btn_under.clicked.connect(self._do_under)
        self.btn_strike.clicked.connect(self._do_strike)
        self.btn_ulist.clicked.connect(lambda: self._do_list("bullet"))
        self.btn_olist.clicked.connect(lambda: self._do_list("number"))
        self.btn_left.clicked.connect(lambda: self._do_align("left"))
        self.btn_center.clicked.connect(lambda: self._do_align("center"))
        self.btn_right.clicked.connect(lambda: self._do_align("right"))
        self.btn_color.clicked.connect(self._do_color)
        self.btn_mark.clicked.connect(self._do_mark)
        self.btn_clear.clicked.connect(self._do_clear)
        self.btn_link.clicked.connect(self._do_link)

        self.visual.textChanged.connect(self._on_edit)
        self.source.textChanged.connect(self._on_source_edit)
        self.plain_edit.textChanged.connect(self._on_edit)
        self.visual.cursorPositionChanged.connect(self._update_fmt_buttons)
        self.visual.currentCharFormatChanged.connect(
            lambda _f: self._update_fmt_buttons())
        self.mode_combo.currentIndexChanged.connect(self._mode_switched)

        self._source_timer = QTimer(self)
        self._source_timer.setSingleShot(True)
        self._source_timer.setInterval(250)
        self._source_timer.timeout.connect(self._source_applied)

    # ================================================================== #
    # content API
    # ================================================================== #
    def mode(self) -> str:
        return self._mode

    def set_content(self, body: str, fmt: str) -> None:
        """Load a slide body. html -> visual, plain -> plain-text view."""
        self._loading = True
        try:
            if fmt == "html":
                self._set_mode("visual", convert=False)
                self.visual.setHtml(htmlfmt.sanitize_html(body) or
                                    "<p></p>")
            else:
                self._set_mode("plain", convert=False)
                self.plain_edit.setPlainText(body or "")
            self.source.clear()
            self._update_fmt_buttons()
        finally:
            self._loading = False

    def content(self) -> tuple[str, str]:
        """Return (body, body_format) for the current view."""
        if self._mode == "plain":
            return self.plain_edit.toPlainText(), "plain"
        if self._mode == "source":
            raw = self.source.toPlainText()
            return htmlfmt.sanitize_html(raw), "html"
        return self._clean_visual_html(), "html"

    def _clean_visual_html(self) -> str:
        html = self.visual.toHtml()
        clean = htmlfmt.sanitize_html(html)
        # collapse Qt's empty <p> artifacts at both ends
        clean = clean.replace("<p></p>", "").strip()
        return clean or ""

    # ------------------------------------------------------------------ #
    def _set_mode(self, mode: str, convert: bool = True) -> None:
        if mode == self._mode and convert:
            return
        if convert:
            # carry the content over into the new view
            body, fmt = self.content()
            if mode == "visual":
                html = body if fmt == "html" else htmlfmt.plain_to_html(body)
                self.visual.setHtml(htmlfmt.sanitize_html(html) or "<p></p>")
            elif mode == "source":
                html = body if fmt == "html" else htmlfmt.plain_to_html(body)
                self.source.setPlainText(htmlfmt.sanitize_html(html))
            else:  # plain
                text = htmlfmt.html_to_plain(body) if fmt == "html" else body
                self.plain_edit.setPlainText(text)
        self._mode = mode
        self.stack.setCurrentWidget(
            {"visual": self.visual, "source": self.source,
             "plain": self.plain_edit}[mode])
        self.hint.setText({
            "visual": "Rich text: bold, colours, lists … everything pasted "
                      "is sanitised automatically.",
            "source": "HTML source — allowed: p, h1-h3, b i u s sub sup, "
                      "ul/ol/li, blockquote, pre/code, a href, span & font "
                      "colours.",
            "plain": "Plain text — blank line starts a new paragraph. "
                     "Switch to Visual or HTML source for formatting.",
        }[mode])

    def _mode_switched(self, idx: int) -> None:
        if self._loading:
            return
        mode = MODE_KEYS[max(0, min(idx, len(MODE_KEYS) - 1))]
        self._set_mode(mode, convert=True)
        self._on_edit()

    def _on_edit(self) -> None:
        if self._loading:
            return
        self.changed.emit()

    def _on_source_edit(self) -> None:
        if self._loading:
            return
        self._source_timer.start()      # debounce raw-HTML typing

    def _source_applied(self) -> None:
        if self._mode == "source":
            self._on_edit()

    # ================================================================== #
    # toolbar actions
    # ================================================================== #
    def _do_bold(self) -> None:
        cur = self.visual.currentCharFormat()
        fmt = QTextCharFormat()
        weight = cur.fontWeight()
        fmt.setFontWeight(QFont.Weight.Normal if int(weight) >=
                          int(QFont.Weight.Bold) else QFont.Weight.Bold)
        self.visual.mergeCurrentCharFormat(fmt)
        self._update_fmt_buttons()

    def _do_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.visual.currentCharFormat().fontItalic())
        self.visual.mergeCurrentCharFormat(fmt)

    def _do_under(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.visual.currentCharFormat()
                             .fontUnderline())
        self.visual.mergeCurrentCharFormat(fmt)

    def _do_strike(self) -> None:
        fmt = QTextCharFormat()
        cur = self.visual.currentCharFormat()
        on = cur.fontStrikeOut()
        fmt.setFontStrikeOut(not on)
        self.visual.mergeCurrentCharFormat(fmt)

    def _selected_blocks(self) -> list:
        cursor = self.visual.textCursor()
        doc = self.visual.document()
        start, end = sorted((cursor.anchor(), cursor.position()))
        block = doc.findBlock(start)
        blocks = []
        while block.isValid() and block.position() <= end:
            blocks.append(block)
            block = block.next()
        return blocks or [doc.firstBlock()]

    def _do_list(self, kind: str) -> None:
        cursor = self.visual.textCursor()
        fmt = QTextListFormat()
        fmt.setIndent(1)
        fmt.setStyle(QTextListFormat.Style.ListDisc if kind == "bullet"
                     else QTextListFormat.Style.ListDecimal)
        blocks = self._selected_blocks()
        cursor.beginEditBlock()
        lst = None
        for block in blocks:
            bc = QTextCursor(block)
            if lst is None:
                lst = bc.createList(fmt)
            else:
                try:
                    lst.add(block)
                except Exception:
                    bc.createList(fmt)
        cursor.endEditBlock()
        self._on_edit()

    def _do_align(self, how: str) -> None:
        align = {"left": Qt.AlignmentFlag.AlignLeft,
                 "center": Qt.AlignmentFlag.AlignHCenter,
                 "right": Qt.AlignmentFlag.AlignRight}[how]
        anchor = self.visual.textCursor()
        anchor.beginEditBlock()
        try:
            for block in self._selected_blocks():
                cur = QTextCursor(block)
                bf = QTextBlockFormat(block.blockFormat())
                bf.setAlignment(align)
                cur.setBlockFormat(bf)
        finally:
            anchor.endEditBlock()
        self._on_edit()

    def _do_color(self) -> None:
        col = QColorDialog.getColor(
            self.visual.currentCharFormat().foreground().color() if
            self.visual.currentCharFormat().foreground().style() !=
            Qt.BrushStyle.NoBrush else QColor("#e6edf3"),
            self, "Text colour")
        if not col.isValid():
            return
        fmt = QTextCharFormat()
        fmt.setForeground(col)
        self.visual.mergeCurrentCharFormat(fmt)
        self._on_edit()

    def _do_mark(self) -> None:
        col = QColorDialog.getColor(QColor("#ffd54a"), self,
                                    "Highlight colour")
        if not col.isValid():
            return
        fmt = QTextCharFormat()
        fmt.setBackground(col)
        self.visual.mergeCurrentCharFormat(fmt)
        self._on_edit()

    def _do_clear(self) -> None:
        cursor = self.visual.textCursor()
        cursor.setCharFormat(QTextCharFormat())
        bf = QTextBlockFormat()
        bf.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cursor.setBlockFormat(bf)
        self._on_edit()

    def _do_link(self) -> None:
        cursor = self.visual.textCursor()
        url, ok = QInputDialog.getText(self, "Insert link",
                                       "URL (https:// …):")
        if not ok or not url.strip():
            return
        url = url.strip()
        if not url.lower().startswith(("http://", "https://", "mailto:")):
            url = "https://" + url
        text = cursor.selectedText()
        if not text:
            text, ok = QInputDialog.getText(self, "Insert link",
                                            "Link text:")
            if not ok or not text.strip():
                return
            cursor.insertHtml(f'<a href="{htmlfmt.esc_attr(url)}">'
                              f'{htmlfmt.esc(text)}</a>')
        else:
            fmt = QTextCharFormat()
            fmt.setAnchor(True)
            fmt.setAnchorHref(url)
            fmt.setFontUnderline(True)
            fmt.setForeground(QColor("#4da3ff"))
            cursor.mergeCharFormat(fmt)
            cursor.clearSelection()
            self.visual.setTextCursor(cursor)
        self._on_edit()

    # ================================================================== #
    def _update_fmt_buttons(self) -> None:
        cf = self.visual.currentCharFormat()
        self.btn_bold.setCheckable(True)
        self.btn_italic.setCheckable(True)
        self.btn_under.setCheckable(True)
        self.btn_strike.setCheckable(True)
        self.btn_bold.setChecked(int(cf.fontWeight()) >=
                                 int(QFont.Weight.Bold))
        self.btn_italic.setChecked(cf.fontItalic())
        self.btn_under.setChecked(cf.fontUnderline())
        self.btn_strike.setChecked(cf.fontStrikeOut())

    # ------------------------------------------------------------------ #
    # undo/redo delegation from the main window
    # ------------------------------------------------------------------ #
    def focused_editor(self):
        w = self.focusWidget()
        if w in (self.visual, self.source, self.plain_edit):
            return w
        for w in (self.visual, self.source, self.plain_edit):
            if w.hasFocus():
                return w
        return None

    def editor_undo(self) -> bool:
        """Undo inside the focused editor; True when handled."""
        ed = self.focused_editor()
        if ed is None or not ed.document().isUndoAvailable():
            return False
        ed.undo()
        return True

    def editor_redo(self) -> bool:
        """Redo inside the focused editor; True when handled."""
        ed = self.focused_editor()
        if ed is None or not ed.document().isRedoAvailable():
            return False
        ed.redo()
        return True
