"""Professional input, output & working (temp) folder management.

One place that answers "where do my files live?":

  Input folder    where browsing for source material starts (imports,
                  scripts, projects). Optional — when unset, file dialogs
                  open wherever you last browsed.
  Output folder   where exports land. Defaults to the app's bundled
                  ``output/`` folder; a custom folder can be set anywhere.
  Output layout   how the output folder is organised:
                    flat        everything side by side
                    per_deck    one subfolder per deck name
                    dated       one subfolder per day (YYYY-MM-DD)
  Working folder  where temporary scratch files (rendered PNG frames,
                  video segments, converted documents) are kept while a
                  job runs. Defaults to ``tmp/`` inside the current
                  working directory, falls back gracefully when that is
                  not writable, prunes stale leftovers at startup and
                  can be cleaned manually at any time.
  Recent folders  the folders you have picked in any dialog, for quick
                  switching in the folder manager.

The settings layer is plain QSettings (crash-safe, remembered between
runs) and every helper is pure Python apart from that, so tests can drive
the whole module without showing a dialog. ``FolderManagerDialog`` at the
bottom is the GUI (opened via File ▸ Input & output folders…).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import uuid

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QDialog, QListWidgetItem

from . import paths

ORG = "ZaiStudio"
APP = "SlideshowStudio"

INPUT_KEY = "folders/input"             # "" = not configured
OUTPUT_KEY = "folders/output_root"      # "" = app's bundled output/
LAYOUT_KEY = "folders/output_layout"    # flat | per_deck | dated
RECENT_KEY = "folders/recent"           # list of recently used folders
TEMP_KEY = "folders/temp_root"          # "" = tmp/ in the current dir
MAX_RECENT = 8

TEMP_DIRNAME = "tmp"                    # working-folder name
TEMP_MAX_AGE_HOURS = 24.0               # startup prune age for leftovers

# why temp_dir() last fell back ("" = the preferred location works)
_fallback_reason = ""

LAYOUTS = [
    ("flat", "Everything in one folder"),
    ("per_deck", "One subfolder per deck"),
    ("dated", "Date-stamped subfolders (YYYY-MM-DD)"),
]
LAYOUT_LABELS = dict(LAYOUTS)
LAYOUT_KEYS = list(LAYOUT_LABELS)


def _settings() -> QSettings:
    return QSettings(ORG, APP)


# ------------------------------------------------------------------ #
# input folder
# ------------------------------------------------------------------ #
def input_dir() -> str:
    """The configured input folder ('' when not set)."""
    return str(_settings().value(INPUT_KEY, "") or "").strip()


def set_input_dir(path: str) -> None:
    _settings().setValue(INPUT_KEY, os.path.abspath(path) if path else "")


# ------------------------------------------------------------------ #
# output folder
# ------------------------------------------------------------------ #
def default_output_root() -> str:
    """The app's bundled output folder (always usable)."""
    return paths.output_dir()


def output_root(create: bool = True) -> str:
    """Where exports land — the custom folder, or the bundled output/."""
    custom = str(_settings().value(OUTPUT_KEY, "") or "").strip()
    if custom:
        if create:
            try:
                os.makedirs(custom, exist_ok=True)
            except OSError:
                pass
        return custom
    return paths.output_dir(create)


def set_output_root(path: str) -> None:
    """Set a custom output folder ('' restores the bundled default)."""
    _settings().setValue(OUTPUT_KEY, os.path.abspath(path) if path else "")


def using_default_output() -> bool:
    """False when the user picked their own output folder."""
    return not bool(str(_settings().value(OUTPUT_KEY, "") or "").strip())


def output_layout() -> str:
    """'flat' | 'per_deck' | 'dated' (flat before the user chooses)."""
    val = str(_settings().value(LAYOUT_KEY, "flat") or "flat")
    return val if val in LAYOUT_KEYS else "flat"


def set_output_layout(layout: str) -> None:
    if layout in LAYOUT_KEYS:
        _settings().setValue(LAYOUT_KEY, layout)


def layout_subdir(deck_name: str = "") -> str:
    """Subfolder (inside the output root) the layout policy asks for."""
    layout = output_layout()
    if layout == "per_deck":
        return paths.sanitize_stem(deck_name or "slideshow")
    if layout == "dated":
        return time.strftime("%Y-%m-%d")
    return ""


def organized_output_path(name: str, ext: str,
                          deck_name: str = "") -> str:
    """Collision-safe export path honouring the output folder + layout.

    Creates the layout subfolder on demand so the export never fails for
    a missing directory."""
    stem = paths.sanitize_stem(name)
    ext = ext.lstrip(".")
    root = output_root()
    sub = layout_subdir(deck_name or name)
    folder = os.path.join(root, sub) if sub else root
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = root                       # read-only subdir: fall back
    base = os.path.join(folder, f"{stem}.{ext}")
    if not os.path.exists(base):
        return base
    i = 2
    while os.path.exists(os.path.join(folder, f"{stem}-{i}.{ext}")):
        i += 1
    return os.path.join(folder, f"{stem}-{i}.{ext}")


def suggest_output_path(name: str, ext: str) -> str:
    """Best-guess destination for a new export.

    Priority: a configured output folder (with its layout policy) ›
    the last folder an export was saved to › the bundled output folder."""
    if not using_default_output():
        return organized_output_path(name, ext)
    last = str(_settings().value("last_export_dir", "") or "").strip()
    if last and os.path.isdir(last):
        stem = paths.sanitize_stem(name)
        return os.path.join(last, f"{stem}.{ext.lstrip('.')}")
    return paths.default_output_path(name, ext)


# ------------------------------------------------------------------ #
# working (temp) folder
# ------------------------------------------------------------------ #
def cwd_temp_dir() -> str:
    """The default working folder: ``tmp/`` in the current directory."""
    return os.path.join(os.getcwd(), TEMP_DIRNAME)


def using_default_temp() -> bool:
    """False when the user picked their own working folder."""
    return not bool(str(_settings().value(TEMP_KEY, "") or "").strip())


def set_temp_dir(path: str) -> None:
    """Set a custom working folder ('' restores the cwd default)."""
    _settings().setValue(TEMP_KEY, os.path.abspath(path)
                         if path and path.strip() else "")


def temp_source() -> str:
    """Human label for where temp_dir() resolves right now."""
    if _fallback_reason:
        return "system temporary folder (fallback)"
    if not using_default_temp():
        return "custom folder"
    return f"{TEMP_DIRNAME}/ folder in the current working directory"


def temp_fallback_reason() -> str:
    """Why temp_dir() is not where the user asked it to be ('' = fine)."""
    return _fallback_reason


def temp_dir(create: bool = True) -> str:
    """The folder holding scratch files while a job runs.

    Resolution: a custom folder if one is set, otherwise ``tmp/`` inside
    the current working directory. With ``create`` every candidate is
    created on demand and the chain degrades gracefully — cwd › app
    folder › system temp — so a read-only launch directory never breaks
    an export. The reason for a fallback is kept for diagnostics.
    """
    global _fallback_reason
    _fallback_reason = ""
    custom = str(_settings().value(TEMP_KEY, "") or "").strip()
    if custom:
        chain = [(custom, "the chosen working folder")]
    else:
        chain = [(cwd_temp_dir(), "the current working directory"),
                 (os.path.join(paths.app_dir(), TEMP_DIRNAME),
                  "the app folder")]
    chain.append((tempfile.gettempdir(), "the system temporary folder"))
    for d, src in chain:
        if not create:
            return d
        try:
            os.makedirs(d, exist_ok=True)
            if os.access(d, os.W_OK):
                return d
            _fallback_reason = f"{src} is read-only"
        except OSError as exc:
            _fallback_reason = (f"{src} is not usable "
                                f"({exc.strerror or exc})")
    return chain[-1][0]


def temp_stats() -> tuple[int, int]:
    """(file count, total bytes) currently inside the working folder."""
    return folder_stats(temp_dir())


def describe_temp() -> str:
    """One-line 'N files · 12.3 MB' summary for the working folder."""
    n, size = temp_stats()
    return f"{n} file{'s' if n != 1 else ''} · {human_size(size)}"


def new_temp_dir(prefix: str = "work") -> str:
    """A fresh scratch subfolder inside the working folder.

    Named ``<prefix>-<pid>-<n>`` so two app instances (or two jobs)
    never collide. Callers remove it when done; anything left behind is
    pruned by :func:`auto_clean_temp` on a later startup.
    """
    root = temp_dir()
    i = 1
    while True:
        d = os.path.join(root, f"{prefix}-{os.getpid()}-{i}")
        try:
            os.makedirs(d)
            return d
        except FileExistsError:
            i += 1


def new_temp_path(prefix: str = "file", suffix: str = ".tmp") -> str:
    """A unique scratch file path inside the working folder (not created)."""
    sfx = suffix if suffix.startswith(".") else f".{suffix}"
    return os.path.join(temp_dir(),
                        f"{prefix}-{uuid.uuid4().hex[:10]}{sfx}")


def _cleanup_safe(root: str) -> bool:
    """Refuse to wipe system-critical folders, whatever the settings say."""
    r = os.path.abspath(root)
    home = os.path.expanduser("~")
    if r in ("/", home, os.path.dirname(home)):
        # '/', the home directory itself and its parent (/home, /Users)
        return False
    if os.name == "nt" and len(r) <= 3:          # C:\ and friends
        return False
    return True


def cleanup_temp(older_than_hours: float = 0.0) -> tuple[int, int]:
    """Delete leftover scratch entries inside the working folder.

    Only the *contents* are removed — the folder itself stays so running
    jobs keep working. With ``older_than_hours`` set, entries touched
    more recently than that are kept (used at startup so a concurrent
    app instance is not disturbed). Returns (entries removed, bytes
    freed); system-critical locations are never touched.
    """
    root = temp_dir()
    if not os.path.isdir(root) or not _cleanup_safe(root):
        return 0, 0
    cutoff = time.time() - max(0.0, older_than_hours) * 3600.0
    removed = 0
    freed = 0
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        try:
            if os.path.getmtime(p) > cutoff:
                continue
            if os.path.isdir(p) and not os.path.islink(p):
                _n, size = folder_stats(p)
                shutil.rmtree(p, ignore_errors=True)
            else:
                size = os.path.getsize(p)
                os.remove(p)
            if not os.path.exists(p):
                removed += 1
                freed += size
        except OSError:
            continue
    return removed, freed


def auto_clean_temp(max_age_hours: float = TEMP_MAX_AGE_HOURS
                    ) -> tuple[int, int]:
    """Startup hygiene: prune leftovers from crashed or killed runs."""
    try:
        return cleanup_temp(max_age_hours)
    except Exception:
        return 0, 0


def remove_temp_dir_if_empty() -> bool:
    """Clean-exit courtesy: drop the default working folder when empty.

    Only the default ``tmp/`` location is removed — a custom folder was
    chosen deliberately and is left alone. Returns True when removed.
    """
    if not using_default_temp():
        return False
    root = cwd_temp_dir()
    try:
        if os.path.isdir(root) and not os.listdir(root):
            os.rmdir(root)
            return True
    except OSError:
        pass
    return False


# ------------------------------------------------------------------ #
# browse start dirs + recent folders
# ------------------------------------------------------------------ #
def browse_dir(kind: str = "input") -> str:
    """Sensible start directory for a file dialog.

    kind='input'  input folder › last browsed › home
    kind='output' output folder › last browsed › home
    """
    s = _settings()
    if kind == "output":
        custom = str(s.value(OUTPUT_KEY, "") or "").strip()
        if custom and os.path.isdir(custom):
            return custom
    inp = str(s.value(INPUT_KEY, "") or "").strip()
    if inp and os.path.isdir(inp):
        return inp
    if kind == "output":
        return paths.output_dir()
    last = str(s.value("last_dir", "") or "").strip()
    if last and os.path.isdir(last):
        return last
    return os.path.expanduser("~")


def remember_folder(path: str) -> None:
    """Record a folder the user just picked (deduped, most-recent first)."""
    if not path:
        return
    d = os.path.abspath(path)
    if not os.path.isdir(d):
        return
    items = [p for p in recent_folders(all=True)
             if os.path.abspath(p) != d]
    items.insert(0, d)
    _settings().setValue(RECENT_KEY, items[:MAX_RECENT])


def recent_folders(all: bool = False) -> list[str]:
    """Recently used folders (existing ones only unless all=True)."""
    val = _settings().value(RECENT_KEY, []) or []
    if isinstance(val, str):
        val = [val]
    items = [str(p) for p in val]
    if all:
        return items
    return [p for p in items if os.path.isdir(p)]


def forget_folder(path: str) -> None:
    d = os.path.abspath(path)
    items = [p for p in recent_folders(all=True)
             if os.path.abspath(p) != d]
    _settings().setValue(RECENT_KEY, items)


def clear_recent_folders() -> None:
    _settings().setValue(RECENT_KEY, [])


# ------------------------------------------------------------------ #
# inspection helpers
# ------------------------------------------------------------------ #
def validate_dir(path: str) -> str:
    """'' when the folder is usable, otherwise a human-readable reason."""
    if not path or not path.strip():
        return "No folder chosen."
    p = os.path.abspath(path.strip())
    if not os.path.exists(p):
        return "The folder does not exist."
    if not os.path.isdir(p):
        return "That path is a file, not a folder."
    if not os.access(p, os.W_OK):
        return "The folder is read-only."
    return ""


def folder_stats(path: str) -> tuple[int, int]:
    """(file count, total bytes) below path — (0, 0) when missing."""
    if not os.path.isdir(path):
        return 0, 0
    count = 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
                count += 1
            except OSError:
                pass
    return count, total


def human_size(n: float) -> str:
    if n <= 0:
        return "0 B"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


def describe_folder(path: str) -> str:
    """One-line 'N files · 12.3 MB' summary for a folder."""
    n, size = folder_stats(path)
    return f"{n} file{'s' if n != 1 else ''} · {human_size(size)}"


# ------------------------------------------------------------------ #
# the dialog
# ------------------------------------------------------------------ #
def build_dialog(parent=None):
    """Stable factory entry for the folder manager dialog."""
    return FolderManagerDialog(parent)


class FolderManagerDialog(QDialog):
    """File ▸ Input & output folders… — set, inspect and reuse folders.

    Changes apply immediately (no OK/Save step). The pure-logic parts of
    this module carry the behaviour; the dialog is a thin editor on top,
    so tests exercise the settings layer directly and only smoke the UI.
    """

    def __init__(self, parent=None):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout,
                                       QLabel, QLineEdit, QListWidget,
                                       QPushButton, QVBoxLayout)
        super().__init__(parent)
        self._QUrl, self._QDesktopServices = QUrl, QDesktopServices
        self.setWindowTitle("Folders — input, output & working")
        self.setMinimumWidth(560)
        self._build()
        self.refresh()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel,
                                       QLineEdit, QListWidget,
                                       QPushButton, QVBoxLayout)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        head = QLabel("Folders — input, output & working")
        head.setProperty("heading", True)
        lay.addWidget(head)

        self.hint = QLabel(
            "Where browsing for source files starts, where exports land "
            "and where temporary render files live. Changes apply "
            "immediately.")
        self.hint.setProperty("hint", True)
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        # input row -------------------------------------------------------
        lay.addWidget(QLabel("Input folder — where imports start"))
        row = QHBoxLayout()
        self.inp_edit = QLineEdit()
        self.inp_edit.setPlaceholderText(
            "Not set — dialogs open in the last folder you browsed")
        row.addWidget(self.inp_edit, 1)
        self.btn_inp_browse = QPushButton("Browse…")
        self.btn_inp_browse.clicked.connect(self._browse_input)
        row.addWidget(self.btn_inp_browse)
        self.btn_inp_open = QPushButton("Open")
        self.btn_inp_open.clicked.connect(self._open_input)
        row.addWidget(self.btn_inp_open)
        self.btn_inp_reset = QPushButton("Reset")
        self.btn_inp_reset.setToolTip("Forget the input folder")
        self.btn_inp_reset.clicked.connect(self._reset_input)
        row.addWidget(self.btn_inp_reset)
        lay.addLayout(row)
        self.inp_info = QLabel("")
        self.inp_info.setProperty("hint", True)
        lay.addWidget(self.inp_info)

        # output row ------------------------------------------------------
        lay.addWidget(QLabel("Output folder — where exports land"))
        row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText(
            f"Bundled default: {paths.output_dir(create=False)}")
        row.addWidget(self.out_edit, 1)
        self.btn_out_browse = QPushButton("Browse…")
        self.btn_out_browse.clicked.connect(self._browse_output)
        row.addWidget(self.btn_out_browse)
        self.btn_out_open = QPushButton("Open")
        self.btn_out_open.clicked.connect(self._open_output)
        row.addWidget(self.btn_out_open)
        self.btn_out_reset = QPushButton("Reset")
        self.btn_out_reset.setToolTip("Back to the bundled output folder")
        self.btn_out_reset.clicked.connect(self._reset_output)
        row.addWidget(self.btn_out_reset)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Organise exports"))
        self.layout_combo = QComboBox()
        for _key, label in LAYOUTS:
            self.layout_combo.addItem(label)
        self.layout_combo.setToolTip(
            "Flat: every file side by side · per deck: one subfolder per "
            "deck name · dated: one subfolder per day")
        row.addWidget(self.layout_combo, 1)
        lay.addLayout(row)
        self.out_info = QLabel("")
        self.out_info.setProperty("hint", True)
        lay.addWidget(self.out_info)

        # working (temp) folder -------------------------------------------
        lay.addWidget(QLabel("Working folder — temporary render files"))
        row = QHBoxLayout()
        self.tmp_edit = QLineEdit()
        self.tmp_edit.setPlaceholderText(
            f"Default: {TEMP_DIRNAME}/ in the folder the app starts in")
        self.tmp_edit.setToolTip(
            "Rendered frames, video segments and converted documents are "
            "written here while a job runs, then deleted")
        row.addWidget(self.tmp_edit, 1)
        self.btn_tmp_browse = QPushButton("Browse…")
        self.btn_tmp_browse.clicked.connect(self._browse_temp)
        row.addWidget(self.btn_tmp_browse)
        self.btn_tmp_open = QPushButton("Open")
        self.btn_tmp_open.clicked.connect(self._open_temp)
        row.addWidget(self.btn_tmp_open)
        self.btn_tmp_reset = QPushButton("Reset")
        self.btn_tmp_reset.setToolTip(
            f"Back to {TEMP_DIRNAME}/ in the startup folder")
        self.btn_tmp_reset.clicked.connect(self._reset_temp)
        row.addWidget(self.btn_tmp_reset)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.btn_tmp_clean = QPushButton("Clean up now")
        self.btn_tmp_clean.setToolTip(
            "Delete every leftover file in the working folder — finished "
            "exports already clean up after themselves")
        self.btn_tmp_clean.clicked.connect(self._clean_temp)
        row.addWidget(self.btn_tmp_clean)
        self.tmp_info = QLabel("")
        self.tmp_info.setProperty("hint", True)
        self.tmp_info.setWordWrap(True)
        row.addWidget(self.tmp_info, 1)
        lay.addLayout(row)

        # recent folders ----------------------------------------------------
        lay.addWidget(QLabel("Recently used folders"))
        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(96)
        self.recent_list.setToolTip(
            "Folders you picked in any dialog. Double-click sets one as "
            "the input folder.")
        self.recent_list.itemDoubleClicked.connect(
            lambda it: self._apply_recent(it, as_output=False))
        lay.addWidget(self.recent_list)
        row = QHBoxLayout()
        self.btn_recent_input = QPushButton("Set as input")
        self.btn_recent_input.clicked.connect(
            lambda: self._apply_recent_selection(as_output=False))
        row.addWidget(self.btn_recent_input)
        self.btn_recent_output = QPushButton("Set as output")
        self.btn_recent_output.clicked.connect(
            lambda: self._apply_recent_selection(as_output=True))
        row.addWidget(self.btn_recent_output)
        self.btn_recent_open = QPushButton("Open")
        self.btn_recent_open.clicked.connect(self._open_recent_selection)
        row.addWidget(self.btn_recent_open)
        self.btn_recent_forget = QPushButton("Remove")
        self.btn_recent_forget.clicked.connect(self._forget_recent)
        row.addWidget(self.btn_recent_forget)
        self.btn_recent_clear = QPushButton("Clear all")
        self.btn_recent_clear.clicked.connect(self._clear_recent)
        row.addWidget(self.btn_recent_clear)
        row.addStretch(1)
        lay.addLayout(row)

        # bottom buttons ------------------------------------------------------
        row = QHBoxLayout()
        row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_close)
        lay.addLayout(row)

    # ------------------------------------------------------------------ #
    # loading / saving
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        inp = input_dir()
        out = "" if using_default_output() else \
            str(_settings().value(OUTPUT_KEY, "") or "")
        self.inp_edit.setText(inp)
        self.out_edit.setText(out)
        self.layout_combo.setCurrentIndex(LAYOUT_KEYS.index(output_layout()))
        self.tmp_edit.setText("" if using_default_temp() else
                              str(_settings().value(TEMP_KEY, "") or ""))
        self._refresh_info()
        self._refresh_recent()

    def _refresh_info(self) -> None:
        inp = self.inp_edit.text().strip()
        if inp:
            err = validate_dir(inp)
            self.inp_info.setText(
                f"✗ {err}" if err else f"{describe_folder(inp)} — import, "
                "script and project dialogs open here.")
        else:
            self.inp_info.setText(
                "Not set — file dialogs open in the last folder you "
                "browsed.")
        out_txt = self.out_edit.text().strip()
        if out_txt:
            err = validate_dir(out_txt)
            self.out_info.setText(
                f"✗ {err}" if err else
                f"{describe_folder(out_txt)} — exports land here.")
        else:
            d = paths.output_dir(create=False)
            self.out_info.setText(
                f"Bundled default in use — {describe_folder(d)}.")
        tmp_txt = self.tmp_edit.text().strip()
        if tmp_txt:
            err = validate_dir(tmp_txt)
            self.tmp_info.setText(
                f"✗ {err}" if err else
                f"{describe_temp()} — render and conversion scratch "
                "files live here, then deleted.")
        else:
            self.tmp_info.setText(
                f"Default in use — {describe_temp()}. Scratch files go "
                f"to {TEMP_DIRNAME}/ inside the folder the app was "
                "started from; leftovers older than a day are pruned at "
                "startup.")

    def _refresh_recent(self) -> None:
        self.recent_list.clear()
        items = recent_folders()
        if not items:
            it = QListWidgetItem("(no folders used yet)")
            it.setFlags(Qt.ItemFlag.NoItemFlags)     # not selectable
            self.recent_list.addItem(it)
            return
        for p in items:
            self.recent_list.addItem(QListWidgetItem(p))

    def _save(self) -> None:
        inp = self.inp_edit.text().strip()
        set_input_dir(inp)
        out = self.out_edit.text().strip()
        set_output_root(out)
        set_output_layout(LAYOUT_KEYS[self.layout_combo.currentIndex()])
        set_temp_dir(self.tmp_edit.text().strip())
        if inp and not validate_dir(inp):
            remember_folder(inp)
        if out and not validate_dir(out):
            remember_folder(out)
        self._refresh_info()

    # ------------------------------------------------------------------ #
    # handlers
    # ------------------------------------------------------------------ #
    def _browse_input(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, "Choose the input folder",
            self.inp_edit.text().strip() or browse_dir("input"))
        if d:
            self.inp_edit.setText(d)
            self._save()
            self._refresh_recent()

    def _browse_output(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, "Choose the output folder",
            self.out_edit.text().strip() or browse_dir("output"))
        if d:
            self.out_edit.setText(d)
            self._save()
            self._refresh_recent()

    def _reset_input(self) -> None:
        self.inp_edit.setText("")
        self._save()

    def _reset_output(self) -> None:
        self.out_edit.setText("")
        self._save()

    def _browse_temp(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, "Choose the working (temp) folder",
            self.tmp_edit.text().strip() or temp_dir())
        if d:
            self.tmp_edit.setText(d)
            self._save()

    def _reset_temp(self) -> None:
        self.tmp_edit.setText("")
        self._save()

    def _open_temp(self) -> None:
        self._open(temp_dir())

    def _clean_temp(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        removed, freed = cleanup_temp()
        self._refresh_info()
        if removed:
            QMessageBox.information(
                self, "Working folder cleaned",
                f"Removed {removed} leftover item{'s' if removed != 1 else ''} "
                f"and freed {human_size(freed)}.")
        else:
            QMessageBox.information(
                self, "Working folder cleaned",
                "Nothing to clean — the working folder has no leftover "
                "files.")

    def _open_input(self) -> None:
        d = self.inp_edit.text().strip()
        if d and not validate_dir(d):
            self._open(d)

    def _open_output(self) -> None:
        d = self.out_edit.text().strip() or paths.output_dir()
        self._open(d)

    def _open(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Folder missing",
                                f"{path} could not be created:\n{exc}")
            return
        self._QDesktopServices.openUrl(self._QUrl.fromLocalFile(
            os.path.abspath(path)))

    def _selected_recent(self):
        return self.recent_list.currentItem()

    def _apply_recent(self, item, as_output: bool) -> None:
        if item is None:
            return
        p = item.text()
        if not os.path.isdir(p):
            return
        if as_output:
            self.out_edit.setText(p)
        else:
            self.inp_edit.setText(p)
        self._save()

    def _apply_recent_selection(self, as_output: bool) -> None:
        self._apply_recent(self._selected_recent(), as_output)

    def _open_recent_selection(self) -> None:
        item = self._selected_recent()
        if item is not None and os.path.isdir(item.text()):
            self._open(item.text())

    def _forget_recent(self) -> None:
        item = self._selected_recent()
        if item is None:
            return
        forget_folder(item.text())
        self._refresh_recent()

    def _clear_recent(self) -> None:
        clear_recent_folders()
        self._refresh_recent()
