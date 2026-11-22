"""Main window: menus, toolbar, three-pane layout, all wiring."""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QDesktopServices, QKeySequence,
                           QPixmap)
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QScrollArea, QSplitter,
                               QStatusBar, QTabWidget, QToolBar,
                               QVBoxLayout, QWidget)

from . import (APP_VERSION, folders, icons, media, memory, paths, styles,
               tts, waveform as waveform_mod, workspace)
from .batch_dialog import BatchExportDialog, scan_folder
from .canvas import SlideCanvas
from .deck_panel import DeckPanel
from .diagnostics import build_dialog as build_diagnostics_dialog
from .export_dialog import ExportDialog
from .folders import FolderManagerDialog
from .find_replace import FindReplaceDialog
from .importers import ImportError_ as DocImportError
from .importers import import_file
from .inspector import SlideInspector
from .models import Deck, Slide, VoiceSettings
from .player import PreviewPlayer
from .present import PresentWindow, mmss
from .quick_convert import QuickConvertDialog
from .rehearse import RehearseWindow, format_summary
from .render import BASE_H, BASE_W, overlay_info, render_slide
from .script_editor import ScriptEditorDialog
from .script_mode import deck_to_script
from .slide_list import SlideListWidget
from .templates import DEFAULT_TEMPLATE, TEMPLATES, make_slide
from .widgets import PanelButton, panel_title
from .workflow import WorkflowBar

SUPPORTED_FILTER = (
    "All supported (*.pptx *.ppt *.pdf *.html *.htm *.txt *.md *.markdown "
    "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;"
    "PowerPoint (*.pptx *.ppt);;PDF (*.pdf);;"
    "HTML (*.html *.htm);;Text (*.txt);;Markdown (*.md *.markdown);;"
    "Images (*.png *.jpg *.jpeg *.bmp *.webp *.gif)"
)
SUPPORTED_EXTS = {".pptx", ".ppt", ".pdf", ".html", ".htm", ".txt",
                  ".md", ".markdown",
                  # photos become one slide each (keep in sync with
                  # paths.IMPORTABLE_EXTS and importers.IMAGE_EXTS)
                  ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif"}

UNDO_LIMIT = 100
AUTOSAVE_SECS = 120

WELCOME_SLIDES = [
    Slide(
        title="Welcome to Slideshow Studio",
        body="Create, edit and narrate slide decks — then export them as an "
             "MP4 video with natural text-to-speech narration.\n\n"
             "•  Import PPTX, PDF, HTML, TXT — or a folder of photos\n"
             "•  Guided pipeline: Import → Narrate → Preview → Export\n"
             "•  Quick convert (Ctrl+M): input files straight to MP4\n"
             "•  Rich-text (HTML) bodies + layout templates\n"
             "•  Ken Burns motion + per-slide transitions\n"
             "•  Voices: edge-tts, Piper (offline), Qwen TTS\n"
             "•  Smart TTS text cleaning (emoji, URLs, markdown)\n"
             "•  Input, output & temp folders, professionally managed\n"
             "•  Subtitles: .srt file or burned into the video\n"
             "•  Video overlays: slide numbers, progress bar, watermark\n"
             "•  Undo / redo, autosave, drag & drop import\n"
             "•  Present fullscreen (F6) with notes (N) · Rehearse timings\n"
             "•  Script mode: edit the whole deck as text (Ctrl+Shift+T)\n"
             "•  Export MP4, MP3, WAV, HTML, PDF handout or PPTX",
    ),
    Slide(
        title="Getting started",
        body="1.  Import (Ctrl+I) or drop a file on the window — the "
             "pipeline bar above the canvas tracks your progress.\n"
             "2.  Edit text in the right panel — Ctrl+Z undoes mistakes.\n"
             "3.  Add motion (zoom / pan) in the Slide tab.\n"
             "4.  Press ▶ to preview the narration.\n"
             "5.  Export (Ctrl+E) — or press Ctrl+M to go straight from "
             "an input file to a finished MP4.\n\n"
             "This slide deck can be deleted — right-click it in the list.",
    ),
    Slide(
        title="Rich text body",
        body="<p>Bodies support a safe <b>HTML</b> subset: "
             "<i>italic</i>, <u>underline</u>, <span style=\"color:#ffb86b\">"
             "colours</span> and lists.</p>"
             "<ul><li>Bullet one</li><li>Bullet two</li></ul>"
             "<p>Edit the <b>HTML source</b> directly from the view picker, "
             "or export the deck as a standalone <b>HTML slideshow</b>.</p>",
        body_format="html",
    ),
]


class MainWindow(QMainWindow):
    def __init__(self, restore_session: bool = False):
        super().__init__()
        self.settings = QSettings("ZaiStudio", "SlideshowStudio")
        self.deck: Deck = Deck()
        self.deck.slides = [
            Slide.from_dict(s.to_dict()) for s in WELCOME_SLIDES
        ]
        self._current_index = 0
        self._dirty = False
        self._import_replace = False
        self.script_dlg: ScriptEditorDialog | None = None
        self.find_dlg: FindReplaceDialog | None = None
        self.present_win: PresentWindow | None = None
        self.rehearse_win: RehearseWindow | None = None
        self.shortcut_dlg = None
        self.diag_dlg = None
        self.models_dlg = None
        self.folders_dlg: FolderManagerDialog | None = None
        # guided workflow state (Import -> Narrate -> Preview -> Export)
        self._content_loaded = False
        self._previewed = False
        self._exported = False
        self._narration_touched = False
        # user chose "Discard" on close: don't remember that state
        self._session_skip = False

        # undo / redo ----------------------------------------------------
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._edit_baseline: dict = {}
        self._edit_pending = False

        self.player = PreviewPlayer(self)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(350)
        self._thumb_timer.timeout.connect(self._refresh_current_thumb)
        self._all_thumb_timer = QTimer(self)
        self._all_thumb_timer.setSingleShot(True)
        self._all_thumb_timer.setInterval(350)
        self._all_thumb_timer.timeout.connect(self._refresh_all_thumbs)
        # coalesces bursts of text edits into a single undo step
        self._edit_coalesce = QTimer(self)
        self._edit_coalesce.setSingleShot(True)
        self._edit_coalesce.setInterval(1200)
        self._edit_coalesce.timeout.connect(self._flush_edit_baseline)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(AUTOSAVE_SECS * 1000)
        self._autosave_timer.timeout.connect(self._autosave)

        self._build_ui()
        self._build_actions()
        self._load_settings()
        self._refresh_baseline()
        self._sync_all()
        self._update_title()
        self._check_autosave()
        self._autosave_timer.start()
        # smart memory: prune stale narration cache (silent), then reopen
        # the last session when launched with the startup toggle enabled
        try:
            memory.prune_narration_cache(days=60)
        except Exception:
            pass
        self.act_reopen_last.setEnabled(memory.session_info() is not None)
        if restore_session and memory.reopen_last_enabled() \
                and memory.session_info() is not None:
            self.reopen_last_session(auto=True)
        if self._is_first_run():
            QTimer.singleShot(
                800, lambda: self.statusBar().showMessage(
                    "Tip: File ▸ Import example loads a ready-made deck — "
                    "exports land in the output folder (File ▸ Open output "
                    "folder).", 12000))

        ok, msg = media.is_available()
        self.statusBar().showMessage(msg)
        if not ok:
            QTimer.singleShot(400, lambda: QMessageBox.warning(
                self, "ffmpeg not found",
                "ffmpeg/ffprobe were not found on your PATH.\n\n"
                "Video and audio export need ffmpeg:\n"
                "  •  Windows: winget install ffmpeg  (or ffmpeg.org)\n"
                "  •  macOS:   brew install ffmpeg\n"
                "  •  Linux:   sudo apt install ffmpeg\n\n"
                "Editing, importing and TTS preview still work."))

        # temp hygiene: prune scratch left behind by crashed runs (files
        # younger than a day stay, so a second app instance is undisturbed)
        try:
            removed, freed = folders.auto_clean_temp()
            if removed:
                QTimer.singleShot(600, lambda: self.statusBar().showMessage(
                    f"Cleaned {removed} leftover temp "
                    f"item{'s' if removed != 1 else ''} "
                    f"({folders.human_size(freed)} freed) from the "
                    "working folder.", 8000))
        except Exception:
            pass

    @staticmethod
    def _is_first_run() -> bool:
        """True exactly once per machine — used for the examples tip."""
        s = QSettings("ZaiStudio", "SlideshowStudio")
        if s.value("has_run"):
            return False
        s.setValue("has_run", True)
        return True

    # ================================================================== #
    # UI construction
    # ================================================================== #
    def _build_ui(self) -> None:
        self.resize(1440, 860)
        self.setWindowTitle("Slideshow Studio")
        self.setAcceptDrops(True)

        # ---- left: slides panel ----------------------------------------
        self.left_panel = QWidget()
        ll = QVBoxLayout(self.left_panel)
        ll.setContentsMargins(8, 8, 4, 8)
        ll.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(panel_title("Slides"))
        head.addStretch(1)
        self.slide_count_label = QLabel("")
        self.slide_count_label.setProperty("hint", True)
        head.addWidget(self.slide_count_label)
        ll.addLayout(head)

        btnrow = QHBoxLayout()
        btnrow.setSpacing(4)
        self.btn_add_slide = PanelButton("plus", "Add slide (Ctrl+Shift+A)")
        self.btn_dup_slide = PanelButton("copy", "Duplicate slide (Ctrl+D)")
        self.btn_del_slide = PanelButton("trash", "Delete slide "
                                         "(Ctrl+Delete)")
        self.btn_move_up = PanelButton("up", "Move up (Ctrl+Up)")
        self.btn_move_down = PanelButton("down", "Move down (Ctrl+Down)")
        self.btn_add_slide.clicked.connect(self.add_slide)
        self.btn_dup_slide.clicked.connect(self.duplicate_current_slide)
        self.btn_del_slide.clicked.connect(self.delete_current_slide)
        self.btn_move_up.clicked.connect(lambda: self._move_current(-1))
        self.btn_move_down.clicked.connect(lambda: self._move_current(1))
        for b in (self.btn_add_slide, self.btn_dup_slide, self.btn_del_slide,
                  self.btn_move_up, self.btn_move_down):
            btnrow.addWidget(b)
        btnrow.addStretch(1)
        ll.addLayout(btnrow)

        self.slide_list = SlideListWidget()
        self.slide_list.setMinimumWidth(230)
        self.slide_list.setMaximumWidth(300)
        ll.addWidget(self.slide_list, 1)

        # ---- center: canvas + controls ---------------------------------
        self.canvas = SlideCanvas()
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.setSpacing(8)
        self.workflow = WorkflowBar()
        cl.addWidget(self.workflow)
        cl.addWidget(self.canvas, 1)
        self.waveform = waveform_mod.WaveformBar()
        self.waveform.setToolTip("Narration waveform — click or drag to "
                                 "seek while playing; shows the selected "
                                 "slide's cached narration when idle")
        cl.addWidget(self.waveform)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.btn_play_deck = QPushButton(icons.icon("play"), "  Play deck")
        self.btn_play_deck.setToolTip("Preview the whole deck with narration "
                                      "(Ctrl+P or F5)")
        self.btn_play_slide = QPushButton(icons.icon("play"), "  Play slide")
        self.btn_pause = QPushButton(icons.icon("pause"), "  Pause")
        self.btn_pause.setEnabled(False)
        self.btn_stop = QPushButton(icons.icon("stop"), "  Stop")
        self.btn_present = PanelButton("present", "Present fullscreen (F6) "
                                       "— arrows navigate, Esc exits")
        self.btn_present.clicked.connect(self.present_deck)
        self.play_label = QLabel("Idle")
        self.play_label.setProperty("hint", True)
        for b in (self.btn_play_deck, self.btn_play_slide, self.btn_stop):
            b.clicked.connect(self._on_play_button)
        self.btn_pause.clicked.connect(self.player.toggle_pause)
        bar.addWidget(self.btn_play_deck)
        bar.addWidget(self.btn_play_slide)
        bar.addWidget(self.btn_pause)
        bar.addWidget(self.btn_stop)
        bar.addWidget(self.btn_present)
        bar.addStretch(1)
        bar.addWidget(self.play_label)

        # zoom cluster (right side of the control bar)
        self.btn_zoom_out = PanelButton("zoom-out", "Zoom out (Ctrl+-)")
        self.btn_zoom_in = PanelButton("zoom-in", "Zoom in (Ctrl+=)")
        self.btn_zoom_fit = PanelButton("fit", "Fit slide (Ctrl+0)")
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setMinimumWidth(64)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setProperty("hint", True)
        self.zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_label.setToolTip("Click to switch between Fit and 100%")
        self.btn_zoom_out.clicked.connect(self.canvas.zoom_out)
        self.btn_zoom_in.clicked.connect(self.canvas.zoom_in)
        self.btn_zoom_fit.clicked.connect(self.canvas.zoom_fit)
        self.zoom_label.mousePressEvent = lambda _e: (
            self.canvas.zoom_fit() if not self.canvas.is_fit()
            else self.canvas.zoom_100())
        self.canvas.zoomChanged.connect(self._on_zoom_changed)
        bar.addWidget(self.btn_zoom_out)
        bar.addWidget(self.zoom_label)
        bar.addWidget(self.btn_zoom_in)
        bar.addWidget(self.btn_zoom_fit)
        cl.addLayout(bar)

        # ---- right: inspector tabs --------------------------------------
        self.inspector = SlideInspector()
        self.deck_panel = DeckPanel()
        self.tabs = QTabWidget()
        self.tabs.addTab(self._wrap_scroll(self.inspector), "Slide")
        self.tabs.addTab(self._wrap_scroll(self.deck_panel), "Deck & Theme")
        self.tabs.setMinimumWidth(330)
        self.tabs.setMaximumWidth(430)

        # ---- splitter ----------------------------------------------------
        self.split = QSplitter(Qt.Orientation.Horizontal)
        self.split.addWidget(self.left_panel)
        self.split.addWidget(center)
        self.split.addWidget(self.tabs)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setCollapsible(1, False)
        self.setCentralWidget(self.split)

        # ---- status bar ---------------------------------------------------
        bar = QStatusBar()
        self.setStatusBar(bar)
        self.stat_label = QLabel("")
        bar.addPermanentWidget(self.stat_label)

        # ---- wiring --------------------------------------------------------
        self.slide_list.slideSelected.connect(self._on_list_selected)
        self.slide_list.orderChanged.connect(self._on_reordered)
        self.slide_list.deleteRequested.connect(self.delete_current_slide)
        self.inspector.slideChanged.connect(self._on_slide_edited)
        self.deck_panel.deckChanged.connect(self._on_deck_edited)
        self.player.stateChanged.connect(self._on_play_state)
        self.player.slideEntered.connect(self._on_play_entered)
        self.player.status.connect(self.play_label.setText)
        self.player.narrationChanged.connect(self._on_player_narration)
        self.player.positionChanged.connect(self._on_player_position)
        self.waveform.seekRequested.connect(self.player.seek_fraction)
        self.canvas.backgroundDropped.connect(self._apply_background_path)
        self.workflow.stepClicked.connect(self._workflow_step)

    @staticmethod
    def _wrap_scroll(w: QWidget) -> QScrollArea:
        """Put a tall panel inside a frameless scroll area so the window
        keeps its normal height no matter how many sections it has."""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(w)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.viewport().setAutoFillBackground(False)
        w.setAutoFillBackground(False)
        return sa

    def _build_actions(self) -> None:
        # menus (kept on self: PySide6 may garbage-collect the QMenu
        # wrappers created by addMenu() and delete the C++ objects with
        # them — the menubar's QActions would then point at dead menus)
        m_file = self.menu_file = self.menuBar().addMenu("&File")
        m_edit = self.menu_edit = self.menuBar().addMenu("&Edit")
        m_view = self.menu_view = self.menuBar().addMenu("&View")
        m_slide = self.menu_slide = self.menuBar().addMenu("&Slide")
        m_script = self.menu_script = self.menuBar().addMenu("Scri&pt")
        m_help = self.menu_help = self.menuBar().addMenu("&Help")

        self.act_new = QAction(icons.icon("new"), "New deck", self)
        self.act_new.setShortcut(QKeySequence("Ctrl+N"))
        self.act_new.triggered.connect(self.new_deck)

        self.act_open = QAction(icons.icon("open"), "Open project…", self)
        self.act_open.setShortcut(QKeySequence("Ctrl+O"))
        self.act_open.triggered.connect(self.open_project)

        self.act_save = QAction(icons.icon("save"), "Save", self)
        self.act_save.setShortcut(QKeySequence("Ctrl+S"))
        self.act_save.triggered.connect(self.save_project)

        self.act_save_as = QAction(icons.icon("save"), "Save as…", self)
        self.act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self.act_save_as.triggered.connect(self.save_project_as)

        self.act_recover = QAction(icons.icon("refresh"),
                                   "Restore autosave…", self)
        self.act_recover.setEnabled(False)
        self.act_recover.triggered.connect(self.restore_autosave)

        self.act_reopen_last = QAction(icons.icon("clock"),
                                       "Reopen last session", self)
        self.act_reopen_last.setToolTip(
            "Bring back the deck exactly as it was on screen when the "
            "studio was closed — selected slide and all")
        self.act_reopen_last.triggered.connect(self.reopen_last_session)

        self.act_import = QAction(icons.icon("import"), "Import slides…", self)
        self.act_import.setShortcut(QKeySequence("Ctrl+I"))
        self.act_import.triggered.connect(self.import_dialog)

        self.act_quick = QAction(icons.icon("wand"),
                                 "Quick convert to MP4…", self)
        self.act_quick.setShortcut(QKeySequence("Ctrl+M"))
        self.act_quick.setIconText("Quick MP4")
        self.act_quick.setToolTip(
            "The fast lane: pick input files (PPTX, PDF, HTML, TXT, MD) "
            "and get finished, narrated MP4 videos — import, narration "
            "and rendering handled in one step")
        self.act_quick.triggered.connect(self.quick_convert_dialog)

        self.act_export = QAction(icons.icon("export"), "Export…", self)
        self.act_export.setShortcut(QKeySequence("Ctrl+E"))
        self.act_export.triggered.connect(self.export_dialog)

        self.act_batch = QAction(icons.icon("film"), "Batch export…", self)
        self.act_batch.setIconText("Batch")
        self.act_batch.setShortcut(QKeySequence("Ctrl+Shift+E"))
        self.act_batch.setToolTip(
            "Queue many slideshows (projects, PPTX/PDF/HTML/TXT/MD or "
            "folders) and export them all in one run")
        self.act_batch.triggered.connect(self.batch_export)

        self.act_quit = QAction("Exit", self)
        self.act_quit.triggered.connect(self.close)

        for a in (self.act_new, self.act_open, self.act_save, self.act_save_as):
            m_file.addAction(a)
        m_file.addAction(self.act_recover)
        m_file.addAction(self.act_reopen_last)
        m_file.addSeparator()
        m_file.addAction(self.act_import)
        self.menu_examples = QMenu("Import example", self)
        self.menu_examples.setIcon(icons.icon("import"))
        m_file.insertMenu(self.act_quick, self.menu_examples)
        self._rebuild_examples_menu()
        m_file.addAction(self.act_quick)
        m_file.addAction(self.act_export)
        m_file.addAction(self.act_batch)
        self.act_slide_png = QAction(icons.icon("image"),
                                     "Export current slide as image…", self)
        self.act_slide_png.setToolTip(
            "Render the slide you are editing to a PNG/JPG file "
            "(2000 px wide, overlays included)")
        self.act_slide_png.triggered.connect(self.export_slide_image)
        m_file.addAction(self.act_slide_png)
        m_file.addSeparator()
        self.act_folders = QAction(icons.icon("open"),
                                   "Input & output folders…", self)
        self.act_folders.setToolTip(
            "Choose where browsing starts and where exports land — "
            "flat, one subfolder per deck, or date-stamped")
        self.act_folders.triggered.connect(self.folders_manager)
        m_file.addAction(self.act_folders)
        self.act_open_input = QAction(icons.icon("import"),
                                      "Open input folder", self)
        self.act_open_input.setToolTip(
            "Show the folder where imports start (Tools ▸ Input & output "
            "folders sets it)")
        self.act_open_input.triggered.connect(self._open_input_folder)
        m_file.addAction(self.act_open_input)
        self.act_open_output = QAction(icons.icon("save"),
                                       "Open output folder", self)
        self.act_open_output.setToolTip(
            "Show the folder where exports are saved")
        self.act_open_output.triggered.connect(
            lambda: self._open_folder(folders.output_root()))
        m_file.addAction(self.act_open_output)
        self.act_open_examples = QAction(icons.icon("open"),
                                         "Open examples folder", self)
        self.act_open_examples.setToolTip(
            "Show the bundled sample slideshows in the file manager")
        self.act_open_examples.triggered.connect(
            lambda: self._open_folder(paths.examples_dir()))
        m_file.addAction(self.act_open_examples)
        self.act_open_temp = QAction(icons.icon("open"),
                                     "Open temp folder", self)
        self.act_open_temp.setToolTip(
            "Show the working folder that holds temporary render files "
            "(tmp/ in the folder the app starts from)")
        self.act_open_temp.triggered.connect(
            lambda: self._open_folder(folders.temp_dir()))
        m_file.addAction(self.act_open_temp)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        self.menu_recent = QMenu("Open recent", self)
        m_file.insertMenu(self.act_import, self.menu_recent)
        self._rebuild_recent_menu()

        # ---- edit menu (undo / redo) ------------------------------------
        self.act_undo = QAction(icons.icon("undo"), "Undo", self)
        self.act_undo.setShortcuts([QKeySequence("Ctrl+Z"),
                                    QKeySequence("Alt+Backspace")])
        self.act_undo.triggered.connect(self.undo)

        self.act_redo = QAction(icons.icon("redo"), "Redo", self)
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"),
                                    QKeySequence("Ctrl+Y")])
        self.act_redo.triggered.connect(self.redo)

        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)
        self._update_undo_actions()

        m_edit.addSeparator()
        self.act_find = QAction(icons.icon("search"), "Find & replace…", self)
        self.act_find.setShortcut(QKeySequence("Ctrl+F"))
        self.act_find.setToolTip("Find text in titles, bodies and "
                                 "narrations, and replace it")
        self.act_find.triggered.connect(self.find_replace)
        m_edit.addAction(self.act_find)

        self.act_paste_img = QAction(icons.icon("image"),
                                     "Paste image as slide background", self)
        self.act_paste_img.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self.act_paste_img.setToolTip(
            "Use the image on the clipboard as the current slide's "
            "background (you can also drop an image on the canvas)")
        self.act_paste_img.triggered.connect(self._paste_image_background)
        m_edit.addAction(self.act_paste_img)

        self.act_slide_copy = QAction(icons.icon("copy"),
                                      "Copy slide image", self)
        self.act_slide_copy.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self.act_slide_copy.setToolTip(
            "Put a high-resolution render of the current slide on the "
            "clipboard — paste it into chat, docs or slides")
        self.act_slide_copy.triggered.connect(self.copy_slide_image)
        m_edit.addAction(self.act_slide_copy)

        # ---- view menu (zoom + theme) -------------------------------------
        self.act_zoom_in = QAction(icons.icon("zoom-in"), "Zoom in", self)
        self.act_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        self.act_zoom_in.triggered.connect(self.canvas.zoom_in)

        self.act_zoom_out = QAction(icons.icon("zoom-out"), "Zoom out", self)
        self.act_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self.act_zoom_out.triggered.connect(self.canvas.zoom_out)

        self.act_zoom_fit = QAction(icons.icon("fit"), "Fit slide", self)
        self.act_zoom_fit.setShortcut(QKeySequence("Ctrl+0"))
        self.act_zoom_fit.triggered.connect(self.canvas.zoom_fit)

        self.act_zoom_100 = QAction("Actual size (100%)", self)
        self.act_zoom_100.setShortcut(QKeySequence("Ctrl+1"))
        self.act_zoom_100.triggered.connect(self.canvas.zoom_100)

        self.act_dark = QAction("Dark theme", self)
        self.act_dark.setCheckable(True)
        self.act_dark.setChecked(True)
        self.act_dark.setShortcut(QKeySequence("Ctrl+T"))
        self.act_dark.toggled.connect(self._set_dark_theme)

        self.act_present = QAction(icons.icon("present"),
                                   "Present deck (fullscreen)", self)
        self.act_present.setShortcut(QKeySequence("F6"))
        self.act_present.setToolTip(
            "Run the deck full-screen with narration — arrows navigate, "
            "Esc exits")
        self.act_present.triggered.connect(self.present_deck)

        for a in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit,
                  self.act_zoom_100):
            m_view.addAction(a)
        m_view.addSeparator()
        m_view.addAction(self.act_present)
        m_view.addSeparator()
        m_view.addAction(self.act_dark)

        # ---- slide menu ---------------------------------------------------
        self.act_add = QAction(icons.icon("plus"), "Add slide", self)
        self.act_add.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_add.triggered.connect(self.add_slide)

        self.act_dup = QAction(icons.icon("copy"), "Duplicate slide", self)
        self.act_dup.setShortcut(QKeySequence("Ctrl+D"))
        self.act_dup.triggered.connect(self.duplicate_current_slide)

        self.act_del = QAction(icons.icon("trash"), "Delete slide", self)
        self.act_del.setShortcut(QKeySequence("Ctrl+Delete"))
        self.act_del.triggered.connect(self.delete_current_slide)

        self.act_up = QAction(icons.icon("up"), "Move up", self)
        self.act_up.setShortcut(QKeySequence("Ctrl+Up"))
        self.act_up.triggered.connect(lambda: self._move_current(-1))

        self.act_down = QAction(icons.icon("down"), "Move down", self)
        self.act_down.setShortcut(QKeySequence("Ctrl+Down"))
        self.act_down.triggered.connect(lambda: self._move_current(1))

        self.menu_templates = QMenu("Add slide from template", self)
        for name, desc in TEMPLATES:
            a = self.menu_templates.addAction(icons.icon("plus"), name)
            a.setToolTip(desc)
            a.triggered.connect(
                lambda _=False, n=name: self.add_slide_from_template(n))

        for a in (self.act_add, self.act_dup, self.act_del,
                  self.act_up, self.act_down):
            m_slide.addAction(a)
        m_slide.addSeparator()
        m_slide.addMenu(self.menu_templates)

        # ---- script menu -------------------------------------------------
        self.act_script_editor = QAction(icons.icon("script"),
                                         "Script editor…", self)
        self.act_script_editor.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_script_editor.setToolTip(
            "Edit every title, body and narration as one plain-text script")
        self.act_script_editor.triggered.connect(self.script_editor)

        self.act_script_export = QAction(icons.icon("export"),
                                         "Export text script…", self)
        self.act_script_export.triggered.connect(self.export_script)

        self.act_script_import = QAction(icons.icon("import"),
                                         "Import text script…", self)
        self.act_script_import.setToolTip(
            "Import a .txt script (‘# Title’, body, ‘~ narration’)")
        self.act_script_import.triggered.connect(self.import_script_dialog)

        self.act_script_help = QAction(icons.icon("help"),
                                       "Script format help…", self)
        self.act_script_help.triggered.connect(self._script_help)

        m_script.addAction(self.act_script_editor)
        m_script.addSeparator()
        self.act_fill_narr = QAction(icons.icon("mic"),
                                     "Fill empty narrations from slide text",
                                     self)
        self.act_fill_narr.setToolTip(
            "Copy each slide's title + body into its empty narration box")
        self.act_fill_narr.triggered.connect(self.fill_empty_narrations)
        self.act_clear_narr = QAction(icons.icon("close"),
                                      "Clear all narrations", self)
        self.act_clear_narr.setToolTip(
            "Empty every narration box (slides then speak title + body); "
            "one undo step restores them")
        self.act_clear_narr.triggered.connect(self.clear_all_narrations)
        m_script.addAction(self.act_fill_narr)
        m_script.addAction(self.act_clear_narr)
        m_script.addSeparator()
        m_script.addAction(self.act_script_import)
        m_script.addAction(self.act_script_export)
        m_script.addSeparator()
        m_script.addAction(self.act_script_help)

        # ---- tools menu (models + smart-memory controls) -----------------
        m_tools = self.menu_tools = self.menuBar().addMenu("&Tools")
        self.act_models = QAction(icons.icon("mic"),
                                  "Voice models & caches…", self)
        self.act_models.setToolTip(
            "Download or delete Piper voice models, refresh the edge "
            "voice list, clear caches")
        self.act_models.triggered.connect(self.show_models)
        m_tools.addAction(self.act_models)
        self.act_rehearse = QAction(icons.icon("clock"),
                                    "Rehearse timings…", self)
        self.act_rehearse.setToolTip(
            "Run the deck like a talk and record how long you spend on "
            "each slide — apply the timings as minimum slide durations")
        self.act_rehearse.triggered.connect(self.rehearse_timings)
        m_tools.addAction(self.act_rehearse)
        m_tools.addSeparator()
        self.act_remember = QAction("Reopen last deck at startup", self)
        self.act_remember.setCheckable(True)
        self.act_remember.setChecked(memory.reopen_last_enabled())
        self.act_remember.setToolTip(
            "When checked, the studio reopens the deck that was on screen "
            "at exit (Tools ▸ Reopen last session does it manually)")
        self.act_remember.toggled.connect(memory.set_reopen_last_enabled)
        m_tools.addAction(self.act_remember)
        self.act_forget_recent = QAction("Clear recent projects", self)
        self.act_forget_recent.setToolTip(
            "Empty the File ▸ Open recent list")
        self.act_forget_recent.triggered.connect(self._clear_recent)
        m_tools.addAction(self.act_forget_recent)
        self.act_clean_temp = QAction("Clean temp folder", self)
        self.act_clean_temp.setToolTip(
            "Delete leftover files from the working folder — finished "
            "exports already clean up after themselves")
        self.act_clean_temp.triggered.connect(self._clean_temp_folder)
        m_tools.addAction(self.act_clean_temp)

        self.act_about = QAction(icons.icon("help"), "About", self)
        self.act_about.triggered.connect(self._about)
        m_help.addAction(self.act_about)
        self.act_diag = QAction(icons.icon("gear"), "Diagnostics…", self)
        self.act_diag.setToolTip("Versions, tools, speech engines, storage "
                                 "and deck state — one copyable report")
        self.act_diag.triggered.connect(self.show_diagnostics)
        m_help.addAction(self.act_diag)
        act_shortcuts = QAction(icons.icon("help"), "Keyboard shortcuts…", self)
        act_shortcuts.triggered.connect(self._shortcuts_dialog)
        m_help.addAction(act_shortcuts)
        act_html_help = QAction("Rich text & HTML help…", self)
        act_html_help.triggered.connect(self._html_help)
        m_help.addAction(act_html_help)
        act_ff = QAction(icons.icon("gear"), "Check ffmpeg…", self)
        act_ff.triggered.connect(self._check_ffmpeg)
        m_help.addAction(act_ff)

        # toolbar: file | history | media | text tools | play
        tb = QToolBar("Main")
        tb.setObjectName("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toolbar = tb          # kept on self: stable wrapper for tests
        for a in (self.act_new, self.act_open, self.act_save):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()
        tb.addAction(self.act_import)
        tb.addAction(self.act_quick)
        tb.addAction(self.act_export)
        tb.addAction(self.act_batch)
        tb.addSeparator()
        tb.addAction(self.act_script_editor)
        tb.addAction(self.act_find)
        tb.addSeparator()
        tb.addAction(self.act_add)
        tb.addAction(self.act_dup)
        self.addToolBar(tb)

        # extra shortcut: F5 plays the deck
        self._act_play_f5 = QAction(self)
        self._act_play_f5.setShortcut(QKeySequence("F5"))
        self._act_play_f5.triggered.connect(
            lambda: self._on_play_button_src(self.btn_play_deck))
        self.addAction(self._act_play_f5)

    # ================================================================== #
    # undo / redo
    # ================================================================== #
    def _snapshot(self) -> dict:
        return self.deck.to_dict()

    def _push_undo(self, state: dict | None = None) -> None:
        self._undo_stack.append(state if state is not None
                                else self._snapshot())
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_actions()

    def _flush_edit_baseline(self) -> None:
        if self._edit_pending:
            self._edit_pending = False
            self._edit_baseline = self._snapshot()

    def _refresh_baseline(self) -> None:
        self._edit_coalesce.stop()
        self._edit_pending = False
        self._edit_baseline = self._snapshot()

    def _restore_snapshot(self, state: dict) -> None:
        path = self.deck.project_path
        idx = self._current_index
        self.deck = Deck.from_dict(state)
        self.deck.project_path = path
        self._sync_all()
        # keep the user's place in the deck when undoing
        self._current_index = max(0, min(idx, len(self.deck.slides) - 1))
        self.slide_list.setCurrentRow(self._current_index)
        self.canvas.set_index(self._current_index)
        self.inspector.set_slide(self.current_slide())
        self._refresh_baseline()
        self._mark_dirty()

    def undo(self) -> None:
        # text edits inside the inspector's editors undo locally first
        if self.inspector.body_editor.editor_undo():
            self._mark_dirty()
            return
        if not self._undo_stack:
            return
        self.player.stop()
        self._edit_coalesce.stop()
        self._edit_pending = False
        self._redo_stack.append(self._snapshot())
        state = self._undo_stack.pop()
        self._restore_snapshot(state)
        self._update_undo_actions()
        self.statusBar().showMessage("Undo.", 2500)

    def redo(self) -> None:
        if self.inspector.body_editor.editor_redo():
            self._mark_dirty()
            return
        if not self._redo_stack:
            return
        self.player.stop()
        self._undo_stack.append(self._snapshot())
        state = self._redo_stack.pop()
        self._restore_snapshot(state)
        self._update_undo_actions()
        self.statusBar().showMessage("Redo.", 2500)

    def _update_undo_actions(self) -> None:
        self.act_undo.setEnabled(bool(self._undo_stack))
        self.act_redo.setEnabled(bool(self._redo_stack))

    # ================================================================== #
    # state sync
    # ================================================================== #
    def _sync_all(self) -> None:
        self.slide_list.set_deck(self.deck)
        self.canvas.set_deck(self.deck)
        self.inspector.set_deck(self.deck)
        self.deck_panel.set_deck(self.deck)
        self._current_index = 0
        if self.deck.slides:
            self.slide_list.setCurrentRow(0)
        self.canvas.set_index(self._current_index)
        self.inspector.set_slide(self.deck.slides[self._current_index]
                                 if self.deck.slides else None)
        self._update_stats()
        self._refresh_waveform_idle()

    def current_index(self) -> int:
        return self._current_index

    def current_slide(self) -> Slide | None:
        if 0 <= self._current_index < len(self.deck.slides):
            return self.deck.slides[self._current_index]
        return None

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._update_title()
        self._update_stats()

    def _update_title(self) -> None:
        name = self.deck.name or "Untitled Deck"
        dirty = " •" if self._dirty else ""
        self.setWindowTitle(f"{name}{dirty} — Slideshow Studio")

    def _update_stats(self) -> None:
        """Small permanent status readout: slide count + duration estimate."""
        n = len(self.deck.slides)
        self.slide_count_label.setText(
            f"{n} slide{'s' if n != 1 else ''}")
        if not n:
            self.stat_label.setText("0 slides")
            return
        total = 0.0
        for s in self.deck.slides:
            if s.duration_override:
                total += s.duration_override
            else:
                chars = max(1, len(s.effective_narration().strip()))
                total += max(2.0, chars / 14.0 + 0.7)
        self.stat_label.setText(
            f"{n} slide{'s' if n != 1 else ''} · est. "
            f"{int(total // 60)}:{int(total % 60):02d}")
        self._update_workflow()

    # ------------------------------------------------------------------ #
    # guided workflow: Import -> Narrate -> Preview -> Export MP4
    # ------------------------------------------------------------------ #
    def _update_workflow(self) -> None:
        """Recompute the pipeline-bar state from the deck + session."""
        slides = self.deck.slides
        imported = bool(self._content_loaded or self.deck.project_path)
        narrated = (
            (bool(slides) and
             all((s.narration or "").strip() for s in slides))
            or self._narration_touched)
        self.workflow.set_state(
            [imported, narrated, self._previewed, self._exported])

    def _workflow_step(self, step: int) -> None:
        """One-click access to a pipeline stage from the workflow bar."""
        if step == 0:                                   # Import
            self.import_dialog()
        elif step == 1:                                 # Narrate
            self._workflow_narrate()
        elif step == 2:                                 # Preview
            if not self.deck.slides:
                self.statusBar().showMessage(
                    "The deck has no slides to preview — import first.",
                    4000)
                return
            self._on_play_button_src(self.btn_play_deck)
        else:                                           # Export MP4
            self.export_dialog()

    def _workflow_narrate(self) -> None:
        """Jump into the narration step: auto-fill empties, then edit."""
        self.tabs.setCurrentIndex(0)
        self.inspector.narr_edit.setFocus()
        if not self.deck.slides:
            self.statusBar().showMessage(
                "No slides to narrate yet — import a file first.", 4000)
            return
        filled = self.apply_fill_narrations()
        if filled:
            self.statusBar().showMessage(
                f"Filled {filled} narration(s) from the slide text — "
                "tweak them here, or pick the voice in the Deck & Theme "
                "tab.", 6000)
        else:
            self.statusBar().showMessage(
                "Narrations are ready — edit them here, or pick the "
                "voice in the Deck & Theme tab.", 5000)

    def _on_external_export(self, path: str) -> None:
        """A finished export (any dialog) — advance the pipeline bar."""
        self._exported = True
        self._update_workflow()
        folders.remember_folder(os.path.dirname(os.path.abspath(path)))
        self.statusBar().showMessage(
            f"Exported {os.path.basename(path)} — saved to "
            f"{os.path.dirname(os.path.abspath(path))}.", 6000)

    # ------------------------------------------------------------------ #
    # folder management
    # ------------------------------------------------------------------ #
    def folders_manager(self):
        """Open (or raise) the input & output folders manager."""
        if self.folders_dlg is None:
            self.folders_dlg = FolderManagerDialog(self)
        self.folders_dlg.refresh()
        self.folders_dlg.show()
        self.folders_dlg.raise_()
        self.folders_dlg.activateWindow()
        return self.folders_dlg

    def _open_input_folder(self) -> None:
        """Reveal the configured input folder, if one is set."""
        d = folders.input_dir()
        if not d or not os.path.isdir(d):
            self.statusBar().showMessage(
                "No input folder configured — File ▸ Input & output "
                "folders… sets one.", 6000)
            return
        self._open_folder(d)

    # ------------------------------------------------------------------ #
    # zoom + theme
    # ------------------------------------------------------------------ #
    def _on_zoom_changed(self) -> None:
        if self.canvas.is_fit():
            self.zoom_label.setText(f"Fit {self.canvas.zoom_pct()}%")
        else:
            self.zoom_label.setText(f"{self.canvas.zoom_pct()}%")

    def _set_dark_theme(self, dark: bool) -> None:
        styles.apply_theme(QApplication.instance(),
                           "dark" if dark else "light")
        self.settings.setValue("theme", "dark" if dark else "light")
        self.canvas.update()
        self.slide_list.refresh(keep_current=True)
        self.statusBar().showMessage(
            "Dark theme." if dark else "Light theme.", 2000)

    # ================================================================== #
    # selection
    # ================================================================== #
    def _on_list_selected(self, row: int) -> None:
        if self.player.is_playing():
            return  # list highlights during playback are programmatic
        self._current_index = row
        self.canvas.set_index(row)
        self.inspector.set_slide(self.current_slide())
        self._refresh_waveform_idle()

    def _on_slide_edited(self) -> None:
        if not self._edit_pending:
            self._push_undo(self._edit_baseline)
            self._edit_pending = True
        self._edit_coalesce.start()
        self._mark_dirty()
        self.canvas.invalidate()
        self.slide_list.update_thumb(self._current_index)
        self._thumb_timer.start()

    def _on_deck_edited(self) -> None:
        if not self._edit_pending:
            self._push_undo(self._edit_baseline)
            self._edit_pending = True
        self._edit_coalesce.start()
        self._mark_dirty()
        self.canvas.invalidate()
        self._all_thumb_timer.start()

    def _refresh_current_thumb(self) -> None:
        self.slide_list.update_thumb(self._current_index)

    def _refresh_all_thumbs(self) -> None:
        self._thumb_timer.stop()
        self.slide_list.refresh(keep_current=True)

    def _on_reordered(self, src: int, dst: int) -> None:
        self.player.stop()
        self._push_undo()
        if self.deck.move_slide(src, dst):
            self._current_index = dst
            self.slide_list.blockSignals(True)
            self.slide_list.refresh(keep_current=False)
            self.slide_list.setCurrentRow(dst)
            self.slide_list.blockSignals(False)
            self.canvas.set_index(dst)
            self.inspector.set_slide(self.current_slide())
            self._mark_dirty()
            self._refresh_baseline()

    # ================================================================== #
    # slide operations
    # ================================================================== #
    def add_slide(self, template_name: str | None = None) -> None:
        self.player.stop()
        self._push_undo()
        self.deck.insert_slide(
            self._current_index + 1,
            make_slide(template_name or DEFAULT_TEMPLATE))
        self._inserted_at(self._current_index + 1)

    def add_slide_from_template(self, template_name: str) -> None:
        """Insert a new slide built from a layout template."""
        self.add_slide(template_name)
        self.statusBar().showMessage(
            f"Added “{template_name}” slide — edit it in the inspector.",
            4000)

    def duplicate_current_slide(self) -> None:
        self.player.stop()
        self._push_undo()
        dup = self.deck.duplicate_slide(self._current_index)
        if dup:
            self._inserted_at(self._current_index + 1)
        else:
            self._undo_stack.pop()
            self._update_undo_actions()

    def _inserted_at(self, idx: int) -> None:
        self._mark_dirty()
        self.slide_list.refresh(keep_current=False)
        self._current_index = idx
        self.slide_list.setCurrentRow(idx)
        self.canvas.set_index(idx)
        self.inspector.set_slide(self.current_slide())
        self._refresh_baseline()

    def delete_current_slide(self) -> None:
        self.player.stop()
        if not self.deck.slides:
            return
        if len(self.deck.slides) == 1:
            QMessageBox.information(
                self, "Cannot delete",
                "The deck needs at least one slide. Add another first.")
            return
        self._push_undo()
        gone = self.deck.remove_slide(self._current_index)
        if gone and gone.image:
            pass  # keep the staged media file; harmless to leave behind
        self._mark_dirty()
        self.slide_list.refresh(keep_current=False)
        idx = max(0, min(self._current_index, len(self.deck.slides) - 1))
        self._current_index = idx
        self.slide_list.setCurrentRow(idx)
        self.canvas.set_index(idx)
        self.inspector.set_slide(self.current_slide())
        self._refresh_baseline()

    def _move_current(self, delta: int) -> None:
        src = self._current_index
        dst = src + delta
        if 0 <= dst < len(self.deck.slides):
            self._on_reordered(src, dst)

    # ================================================================== #
    # file operations
    # ================================================================== #
    def new_deck(self) -> None:
        if not self._confirm_discard():
            return
        self.player.stop()
        self._push_undo()
        self.deck = Deck()
        self.deck.slides = [
            Slide.from_dict(s.to_dict()) for s in WELCOME_SLIDES
        ]
        self._content_loaded = False
        self._previewed = False
        self._exported = False
        self._narration_touched = False
        self._sync_all()
        self._refresh_baseline()
        self._dirty = False
        self._session_skip = False
        self._update_title()
        self.statusBar().showMessage("New deck created.", 3000)

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open slideshow project", folders.browse_dir("input"),
            "Slideshow project (*.slideshow)")
        if not path:
            return
        self._load_project_file(path)

    def _load_project_file(self, path: str) -> bool:
        try:
            deck = workspace.load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return False
        self.player.stop()
        self._remember_deck_state()      # memory for the outgoing deck
        self._push_undo()
        self.deck = deck
        self._content_loaded = True
        self._sync_all()
        self._refresh_baseline()
        self._dirty = False
        self._update_title()
        self._session_skip = False
        self.settings.setValue("last_dir", os.path.dirname(path))
        folders.remember_folder(os.path.dirname(path))
        self._add_recent(path)
        self._restore_deck_state(path)   # put the user back where they were
        self.statusBar().showMessage(f"Opened {os.path.basename(path)}", 4000)
        return True

    def save_project(self) -> bool:
        if not self.deck.project_path:
            return self.save_project_as()
        try:
            workspace.save_project(self.deck, self.deck.project_path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._dirty = False
        self._update_title()
        self._remove_autosave()
        self.statusBar().showMessage(
            f"Saved {os.path.basename(self.deck.project_path)}", 4000)
        return True

    def save_project_as(self) -> bool:
        start = folders.browse_dir("input")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save slideshow project",
            os.path.join(start, (self.deck.name or "deck") + ".slideshow"),
            "Slideshow project (*.slideshow)")
        if not path:
            return False
        if not path.lower().endswith(".slideshow"):
            path += ".slideshow"
        folders.remember_folder(os.path.dirname(os.path.abspath(path)))
        self.deck.project_path = path
        return self.save_project()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        ret = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Save before continuing?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel)
        if ret == QMessageBox.StandardButton.Save:
            return self.save_project()
        if ret == QMessageBox.StandardButton.Discard:
            # keep the user's decision: don't remember this state as a
            # session snapshot when the window closes right after
            self._session_skip = True
            return True
        return False

    # ------------------------------------------------------------------ #
    # recent projects
    # ------------------------------------------------------------------ #
    def _recent_list(self) -> list[str]:
        val = self.settings.value("recent_projects", []) or []
        if isinstance(val, str):
            val = [val]
        return [str(p) for p in val if os.path.isfile(str(p))]

    def _add_recent(self, path: str) -> None:
        items = [p for p in self._recent_list()
                 if os.path.abspath(p) != os.path.abspath(path)]
        items.insert(0, path)
        self.settings.setValue("recent_projects", items[:8])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self.menu_recent.clear()
        items = self._recent_list()
        if not items:
            act = self.menu_recent.addAction("(no recent projects)")
            act.setEnabled(False)
            return
        for p in items:
            label = os.path.basename(p) + "   —   " + os.path.dirname(p)
            act = self.menu_recent.addAction(label)
            act.triggered.connect(
                lambda _=False, path=p: self._recent_open(path))

    def _recent_open(self, path: str) -> None:
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Missing file",
                                f"{path} no longer exists.")
            self._rebuild_recent_menu()
            return
        if not self._confirm_discard():
            return
        self._load_project_file(path)

    def _clear_recent(self) -> None:
        self.settings.setValue("recent_projects", [])
        self._rebuild_recent_menu()
        self.statusBar().showMessage("Recent projects cleared.", 3000)

    def _clean_temp_folder(self) -> None:
        """Tools ▸ Clean temp folder — wipe working-folder leftovers."""
        removed, freed = folders.cleanup_temp()
        if removed:
            QMessageBox.information(
                self, "Temp folder cleaned",
                f"Removed {removed} leftover "
                f"item{'s' if removed != 1 else ''} from the working "
                f"folder and freed {folders.human_size(freed)}.")
            self.statusBar().showMessage(
                f"Temp folder cleaned — {folders.human_size(freed)} "
                "freed.", 5000)
        else:
            self.statusBar().showMessage(
                "Temp folder is already clean.", 4000)

    # ------------------------------------------------------------------ #
    # smart memory: session + per-deck state + models manager
    # ------------------------------------------------------------------ #
    def _remember_deck_state(self) -> None:
        """Store the selected slide + inspector tab for the current deck."""
        if self.deck.project_path:
            try:
                memory.save_deck_state(self.deck.project_path,
                                       self._current_index,
                                       self.tabs.currentIndex())
            except Exception:
                pass

    def _restore_deck_state(self, path: str) -> None:
        state = memory.load_deck_state(path)
        idx = state.get("index")
        if isinstance(idx, int) and self.deck.slides:
            self._current_index = max(0, min(idx, len(self.deck.slides) - 1))
            self.slide_list.setCurrentRow(self._current_index)
            self.canvas.set_index(self._current_index)
            self.inspector.set_slide(self.current_slide())
        tab = state.get("tab")
        if isinstance(tab, int) and 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)

    def reopen_last_session(self, auto: bool = False) -> None:
        """Restore the deck exactly as it was on screen at last exit."""
        info = memory.session_info()
        if info is None:
            if not auto:
                self.statusBar().showMessage(
                    "No remembered session — close the studio normally "
                    "and it will be saved.", 5000)
            return
        if not auto and not self._confirm_discard():
            return
        loaded = memory.load_session()
        if loaded is None:
            if not auto:
                self.statusBar().showMessage(
                    "The session snapshot could not be read.", 5000)
            return
        deck, meta = loaded
        self.player.stop()
        self._push_undo()
        deck.project_path = meta.get("path") or None
        if deck.project_path and not os.path.isfile(deck.project_path):
            deck.project_path = None
        self.deck = deck
        self._content_loaded = True
        self._sync_all()
        self._refresh_baseline()
        self._dirty = False
        self._update_title()
        self._session_skip = False
        if deck.project_path:
            self._add_recent(deck.project_path)
        idx = meta.get("index")
        if isinstance(idx, int) and self.deck.slides:
            self._current_index = max(0, min(idx, len(self.deck.slides) - 1))
            self.slide_list.setCurrentRow(self._current_index)
            self.canvas.set_index(self._current_index)
            self.inspector.set_slide(self.current_slide())
        tab = meta.get("tab")
        if isinstance(tab, int) and 0 <= tab < self.tabs.count():
            self.tabs.setCurrentIndex(tab)
        self.statusBar().showMessage(
            f"Reopened your last session — {len(self.deck.slides)} slide(s)"
            + ("" if deck.project_path else " (unsaved — remember to "
               "save)") + ".", 6000)

    def show_models(self):
        """Open (or raise) the voice models & caches manager."""
        if self.models_dlg is None:
            from .models_dialog import VoiceModelsDialog
            self.models_dlg = VoiceModelsDialog(self)
            self.models_dlg.modelsChanged.connect(self._on_models_changed)
        self.models_dlg.show()
        self.models_dlg.raise_()
        self.models_dlg.activateWindow()
        return self.models_dlg

    def _on_models_changed(self) -> None:
        """A model or cache changed — refresh engine readouts."""
        self.deck_panel.refresh_piper_status()
        if self.diag_dlg is not None:
            try:
                self.diag_dlg.refresh(self.deck)
            except RuntimeError:
                self.diag_dlg = None
        self.statusBar().showMessage("Voice models updated.", 3000)

    # ------------------------------------------------------------------ #
    # autosave + recovery
    # ------------------------------------------------------------------ #
    def _autosave(self) -> None:
        if not self._dirty or not self.deck.slides:
            return
        try:
            workspace.save_project(self.deck, workspace.autosave_path(),
                                   set_path=False)
            self.statusBar().showMessage("Autosaved.", 2000)
        except Exception:
            pass  # autosave must never interrupt work

    def _check_autosave(self) -> None:
        if os.path.isfile(workspace.autosave_path()):
            self.act_recover.setEnabled(True)
            self.statusBar().showMessage(
                "An autosave from a previous session was found — "
                "File ▸ Restore autosave.", 8000)

    def restore_autosave(self) -> None:
        path = workspace.autosave_path()
        if not os.path.isfile(path):
            self.statusBar().showMessage("No autosave found.", 3000)
            return
        if not self._confirm_discard():
            return
        try:
            deck = workspace.load_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Recovery failed", str(exc))
            return
        deck.project_path = None
        self.player.stop()
        self._push_undo()
        self.deck = deck
        self._content_loaded = True
        self._sync_all()
        self._refresh_baseline()
        self._dirty = True
        self._session_skip = False
        self._update_title()
        self.statusBar().showMessage("Autosave restored — remember to "
                                     "save it properly.", 5000)

    def _remove_autosave(self) -> None:
        try:
            p = workspace.autosave_path()
            if os.path.isfile(p):
                os.remove(p)
            self.act_recover.setEnabled(False)
        except OSError:
            pass

    # ================================================================== #
    # import / export
    # ================================================================== #
    def import_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import slides from file", folders.browse_dir("input"),
            SUPPORTED_FILTER)
        if not path:
            return
        folders.remember_folder(os.path.dirname(path))
        self.import_path(path)

    def import_path(self, path: str) -> None:
        self.player.stop()
        self.statusBar().showMessage(f"Importing {os.path.basename(path)} …")
        QApplication_setWaitCursor(True)
        try:
            slides = import_file(path)
        except DocImportError as exc:
            QApplication_setWaitCursor(False)
            QMessageBox.warning(self, "Import failed", str(exc))
            self.statusBar().showMessage("Import failed.", 4000)
            return
        except Exception as exc:  # unexpected
            QApplication_setWaitCursor(False)
            QMessageBox.critical(self, "Import failed",
                                 f"Unexpected error: {exc}")
            return
        QApplication_setWaitCursor(False)

        if self.deck.slides and not self._confirm_import_mode():
            self.statusBar().showMessage("Import cancelled.", 3000)
            return
        self._apply_import(slides, self._import_replace,
                           os.path.splitext(os.path.basename(path))[0])

    def _import_many(self, paths: list[str]) -> None:
        """Drop-import: ask replace/append once, then import all files."""
        self.player.stop()
        self.statusBar().showMessage(f"Importing {len(paths)} file(s) …")
        QApplication_setWaitCursor(True)
        all_slides: list[Slide] = []
        failed: list[str] = []
        first_name = ""
        for p in paths:
            try:
                if os.path.splitext(p)[1].lower() == ".slideshow":
                    # a dropped project contributes its slides (batch
                    # export handles whole-project queues instead)
                    loaded = workspace.load_project(p)
                    imported, name = loaded.slides, loaded.name
                else:
                    imported = import_file(p)
                    name = os.path.splitext(os.path.basename(p))[0]
                if not first_name:
                    first_name = name
                all_slides.extend(imported)
            except Exception as exc:
                failed.append(f"{os.path.basename(p)}: {exc}")
        QApplication_setWaitCursor(False)
        if not all_slides:
            QMessageBox.warning(self, "Import failed",
                                "Nothing could be imported.\n\n" +
                                "\n".join(failed))
            self.statusBar().showMessage("Import failed.", 4000)
            return
        if self.deck.slides and not self._confirm_import_mode():
            self.statusBar().showMessage("Import cancelled.", 3000)
            return
        first = os.path.splitext(os.path.basename(paths[0]))[0]
        self._apply_import(all_slides, self._import_replace,
                           first_name or first)
        if failed:
            QMessageBox.warning(self, "Some files failed",
                                "\n".join(failed))

    def _apply_import(self, slides: list[Slide], replace: bool,
                      deck_name: str) -> None:
        self._push_undo()
        if replace:
            self.deck.slides.clear()
        self.deck.slides.extend(slides)
        if replace:
            self.deck.name = deck_name
        self._session_skip = False
        self._content_loaded = True

        self._mark_dirty()
        self.slide_list.set_deck(self.deck)
        self.canvas.invalidate()
        self._current_index = 0
        self.slide_list.setCurrentRow(0)
        self.canvas.set_index(0)
        self.inspector.set_slide(self.current_slide())
        self._refresh_baseline()
        self.statusBar().showMessage(
            f"Imported {len(slides)} slides.", 6000)

    def _confirm_import_mode(self) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Import slides")
        box.setText("Replace the current deck, or append the imported "
                    "slides after the existing ones?")
        replace = box.addButton("Replace deck",
                                QMessageBox.ButtonRole.DestructiveRole)
        append = box.addButton("Append", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is replace:
            self._import_replace = True
        elif box.clickedButton() is append:
            self._import_replace = False
        else:
            return False
        return True

    def _rebuild_examples_menu(self) -> None:
        """File ▸ Import example lists every file bundled in examples/."""
        self.menu_examples.clear()
        files = paths.list_examples()
        if not files:
            a = self.menu_examples.addAction("(no examples found)")
            a.setEnabled(False)
            return
        for p in files:
            act = self.menu_examples.addAction(
                icons.icon("film"), paths.describe_example(p))
            act.setToolTip(p)
            act.triggered.connect(
                lambda _=False, path=p: self._open_example(path))

    def _open_example(self, path: str) -> None:
        """Import a bundled example (or open it, if it is a project)."""
        if path.lower().endswith(".slideshow"):
            if not self._confirm_discard():
                return
            self._load_project_file(path)
        else:
            self.import_path(path)

    def _open_folder(self, path: str) -> None:
        """Reveal a folder in the OS file manager, creating it if needed."""
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                QMessageBox.warning(self, "Folder missing",
                                    f"{path} could not be created.")
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        self.statusBar().showMessage(f"Opened {path}", 4000)

    def export_dialog(self) -> None:
        ok, msg = media.is_available()
        dlg = ExportDialog(self.deck, self, ffmpeg_ok=ok)
        dlg.exported.connect(self._on_external_export)
        if not ok:
            dlg.status_label.setText(
                "ffmpeg not found — video/audio export disabled. "
                "HTML, PDF and PPTX export work without it.")
        dlg.exec()

    def quick_convert_dialog(self) -> None:
        """Input files in -> narrated MP4 files out, in one dialog."""
        ok, msg = media.is_available()
        dlg = QuickConvertDialog(self, ffmpeg_ok=ok)
        dlg.exported.connect(self._on_external_export)
        if not ok:
            dlg.status_label.setText(
                "ffmpeg not found — install it to convert to MP4 "
                "(see Help ▸ Check ffmpeg).")
        dlg.exec()

    def batch_export(self) -> None:
        """Queue many decks/files and export them all in one run."""
        ok, msg = media.is_available()
        dlg = BatchExportDialog(self, ffmpeg_ok=ok, current_deck=self.deck)
        dlg.exec()

    # ================================================================== #
    # text script mode
    # ================================================================== #
    def script_editor(self):
        """Open (or raise) the whole-deck text script editor."""
        if self.script_dlg is None:
            self.script_dlg = ScriptEditorDialog(self)
        self.script_dlg.sync_on_show()
        self.script_dlg.show()
        self.script_dlg.raise_()
        self.script_dlg.activateWindow()
        return self.script_dlg

    def find_replace(self):
        """Open (or raise) the find & replace dialog."""
        if self.find_dlg is None:
            self.find_dlg = FindReplaceDialog(self)
        self.find_dlg.show()
        self.find_dlg.raise_()
        self.find_dlg.activateWindow()
        self.find_dlg.find_edit.setFocus()
        return self.find_dlg

    def export_script(self) -> None:
        start = folders.browse_dir("output")
        name = (self.deck.name or "deck").replace(" ", "_")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export text script",
            os.path.join(start, name + "_script.txt"),
            "Text script (*.txt *.md);;All files (*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".txt"
        try:
            self.export_script_to(path)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.settings.setValue("last_dir", os.path.dirname(path))
        folders.remember_folder(os.path.dirname(path))

    def export_script_to(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(deck_to_script(self.deck))
        self.statusBar().showMessage(
            f"Script exported — {os.path.basename(path)}", 5000)

    def import_script_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import text script", folders.browse_dir("input"),
            "Text script (*.txt *.md *.text);;All files (*)")
        if not path:
            return
        folders.remember_folder(os.path.dirname(path))
        self.import_path(path)

    # ================================================================== #
    # narration tools (deck-wide)
    # ================================================================== #
    def fill_empty_narrations(self) -> None:
        self.apply_fill_narrations()

    def apply_fill_narrations(self) -> int:
        """Copy title+body into every empty narration box (one undo)."""
        targets = [s for s in self.deck.slides
                   if not (s.narration or "").strip()
                   and s.effective_narration().strip()]
        if not targets:
            self.statusBar().showMessage(
                "No empty narrations to fill.", 4000)
            return 0
        self._push_undo()               # capture pre-change state
        for s in targets:
            s.narration = s.effective_narration().strip()
        self._narration_touched = True
        self._mark_dirty()
        self.inspector.set_slide(self.current_slide())
        self.statusBar().showMessage(
            f"Filled {len(targets)} empty narration(s) from slide text.",
            5000)
        return len(targets)

    def clear_all_narrations(self) -> None:
        self.apply_clear_narrations()

    def apply_clear_narrations(self) -> int:
        """Empty every narration box (one undo step restores them)."""
        targets = [s for s in self.deck.slides if (s.narration or "").strip()]
        if not targets:
            self.statusBar().showMessage("No narrations to clear.", 4000)
            return 0
        self._push_undo()               # capture pre-change state
        for s in targets:
            s.narration = ""
        self._narration_touched = True
        self._mark_dirty()
        self.inspector.set_slide(self.current_slide())
        self.statusBar().showMessage(
            f"Cleared {len(targets)} narration(s) — slides speak their "
            "text again.", 5000)
        return len(targets)

    # ================================================================== #
    # image -> slide background (paste / drop)
    # ================================================================== #
    def _paste_image_background(self) -> None:
        if not self.current_slide():
            self.statusBar().showMessage(
                "No slide selected — add a slide first.", 4000)
            return
        if not self.canvas.paste_background():
            self.statusBar().showMessage(
                "The clipboard does not contain an image.", 4000)

    def _apply_background_path(self, path: str) -> None:
        """Set an image (dropped or pasted) as the current slide's bg."""
        slide = self.current_slide()
        if slide is None or not path or not os.path.isfile(path):
            return
        self.player.stop()
        self._push_undo()
        try:
            slide.image = workspace.stage_media(path)
        except Exception as exc:
            self._undo_stack.pop()
            self._update_undo_actions()
            QMessageBox.warning(self, "Image failed",
                                f"Could not load the image:\n{exc}")
            return
        self._mark_dirty()
        self.canvas.invalidate()
        self.slide_list.update_thumb(self._current_index)
        self.inspector.set_slide(slide)
        self._refresh_baseline()
        self.statusBar().showMessage(
            f"Background set — {os.path.basename(path)}", 4000)

    # ================================================================== #
    # present mode
    # ================================================================== #
    def present_deck(self) -> None:
        """Run the deck full-screen with narration (F6)."""
        if not self.deck.slides:
            self.statusBar().showMessage("The deck has no slides to "
                                         "present.", 4000)
            return
        self.player.stop()
        if self.present_win is not None:
            try:
                self.present_win.close()
            except RuntimeError:
                pass
            self.present_win = None
        win = PresentWindow(self.deck, start=self._current_index)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        win.closed.connect(self._present_closed)
        win.showFullScreen()
        self.present_win = win
        self.statusBar().showMessage("Presenting — Esc to exit.", 4000)

    def _present_closed(self) -> None:
        self.present_win = None

    # ================================================================== #
    # rehearse timings
    # ================================================================== #
    def rehearse_timings(self) -> None:
        """Run the deck like a talk and record per-slide seconds."""
        if not self.deck.slides:
            self.statusBar().showMessage("The deck has no slides to "
                                         "rehearse.", 4000)
            return
        self.player.stop()
        if self.rehearse_win is not None:
            try:
                self.rehearse_win.close()
            except RuntimeError:
                pass
            self.rehearse_win = None
        win = RehearseWindow(self.deck, start=self._current_index)
        win.finishedRun.connect(self._rehearse_finished)
        win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        win.showFullScreen()
        self.rehearse_win = win
        self.statusBar().showMessage("Rehearsing — Esc when done.", 4000)

    def _ask_apply_rehearsal(self, times: list) -> bool:
        """Modal summary dialog; True when the user applies the times."""
        total = sum(times)
        box = QMessageBox(self)
        box.setWindowTitle("Rehearsal results")
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(
            f"Rehearsed {len([t for t in times if t > 0])} slide(s) in "
            f"{mmss(total)}.\n\n"
            "Apply the recorded times as each slide's minimum duration? "
            "(Exports never cut narration short — a slide with audio "
            "lasts max(audio, duration).)")
        box.setDetailedText(format_summary(times))
        apply_btn = box.addButton("Apply to slides",
                                  QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Discard", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is apply_btn

    def _rehearse_finished(self, times: list) -> None:
        self.rehearse_win = None
        if not any(t > 0 for t in times):
            self.statusBar().showMessage("Rehearsal discarded — nothing "
                                         "recorded.", 4000)
            return
        if not self._ask_apply_rehearsal(times):
            self.statusBar().showMessage("Rehearsal discarded.", 4000)
            return
        self._push_undo()
        applied = 0
        for slide, secs in zip(self.deck.slides, times):
            if secs > 0:
                slide.duration_override = round(float(secs), 1)
                applied += 1
        self._mark_dirty()
        if self.deck.slides:
            self.inspector.set_slide(
                self.deck.slides[min(self._current_index,
                                     len(self.deck.slides) - 1)])
        self.statusBar().showMessage(
            f"Applied rehearsed durations to {applied} slide(s) — "
            "Ctrl+Z undoes.", 5000)

    # ================================================================== #
    # slide -> image (file / clipboard)
    # ================================================================== #
    def _render_current_slide_image(self):
        """2000-px render of the current slide (overlays included)."""
        slide = self.current_slide()
        if slide is None:
            return None
        w = 2000
        h = int(w * BASE_H / BASE_W)
        return render_slide(slide, self.deck.theme, w, h,
                            overlay=overlay_info(self.deck,
                                                 self._current_index))

    def export_slide_image(self, path: str | None = None) -> str:
        """Write the current slide as a PNG/JPG; returns the path or ""."""
        img = self._render_current_slide_image()
        if img is None:
            self.statusBar().showMessage(
                "No slide selected — add a slide first.", 4000)
            return ""
        if path is None:
            from . import folders
            name = (f"{(self.deck.name or 'slide')}_slide-"
                    f"{self._current_index + 1:02d}.png")
            base = folders.output_root() or folders.default_output_root()
            os.makedirs(base, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(
                self, "Export slide as image",
                os.path.join(base, name),
                "PNG image (*.png);;JPEG image (*.jpg)")
            if not path:
                return ""
        if not img.save(path):
            QMessageBox.warning(self, "Export failed",
                                f"Could not write {path}")
            return ""
        self.statusBar().showMessage(
            f"Slide image saved — {path}", 5000)
        return path

    def copy_slide_image(self) -> None:
        """Put a high-resolution render of the slide on the clipboard."""
        img = self._render_current_slide_image()
        if img is None:
            self.statusBar().showMessage(
                "No slide selected — add a slide first.", 4000)
            return
        QApplication.clipboard().setPixmap(QPixmap.fromImage(img))
        self.statusBar().showMessage(
            "Slide image copied to the clipboard (2000 px).", 4000)

    def _shortcuts_dialog(self) -> None:
        from PySide6.QtWidgets import QDialog
        if self.shortcut_dlg is not None:
            try:
                self.shortcut_dlg.show()
                self.shortcut_dlg.raise_()
                self.shortcut_dlg.activateWindow()
                return
            except RuntimeError:
                self.shortcut_dlg = None

        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard shortcuts")
        dlg.setLayout(QVBoxLayout())
        rows = [
            ("File", []),
            ("", [("New deck", "Ctrl+N"), ("Open project", "Ctrl+O"),
                   ("Save", "Ctrl+S"), ("Import slides", "Ctrl+I"),
                   ("Quick convert to MP4", "Ctrl+M"),
                   ("Export", "Ctrl+E"), ("Batch export", "Ctrl+Shift+E")]),
            ("Editing", []),
            ("", [("Undo / Redo", "Ctrl+Z / Ctrl+Shift+Z"),
                   ("Find &amp; replace", "Ctrl+F"),
                   ("Paste image as background", "Ctrl+Shift+V"),
                   ("Copy slide image", "Ctrl+Shift+C")]),
            ("Slides", []),
            ("", [("Add slide", "Ctrl+Shift+A"),
                   ("Duplicate / Delete", "Ctrl+D / Ctrl+Delete"),
                   ("Move up / down", "Ctrl+Up / Ctrl+Down")]),
            ("Playback & presenting", []),
            ("", [("Play deck", "F5"), ("Present fullscreen", "F6"),
                   ("Navigate while presenting", "← / → / Space"),
                   ("Subtitles while presenting", "S"),
                   ("Presenter notes &amp; clock", "N"),
                   ("Auto-advance toggle", "A"), ("Exit present", "Esc")]),
            ("Rehearsing", []),
            ("", [("Rehearse timings", "Tools menu"),
                   ("Navigate / finish", "← / → / Space / Esc")]),
            ("View", []),
            ("", [("Zoom in / out", "Ctrl+= / Ctrl+-"),
                   ("Fit slide / 100%", "Ctrl+0 / Ctrl+1"),
                   ("Dark / light theme", "Ctrl+T"),
                   ("Script editor", "Ctrl+Shift+T")]),
        ]
        html = ["<style>h2{margin:6px 0 2px 0;} td{padding:2px 16px 2px 0;}",
                "</style>"]
        open_table = False
        for title, pairs in rows:
            if title:
                if open_table:
                    html.append("</table>")
                    open_table = False
                html.append(f"<h2>{title}</h2>")
            else:
                if not open_table:
                    html.append("<table>")
                    open_table = True
                for name, keys in pairs:
                    html.append(f"<tr><td><b>{keys}</b></td>")
                    html.append(f"<td>{name}</td></tr>")
        if open_table:
            html.append("</table>")
        lab = QLabel("".join(html))
        lab.setWordWrap(False)
        dlg.layout().addWidget(lab)
        dlg.setModal(False)
        self.shortcut_dlg = dlg
        dlg.show()

    # ================================================================== #
    # drag & drop import (files, or whole folders of sources)
    # ================================================================== #
    @staticmethod
    def _expand_drop(paths_in: list[str]) -> list[str]:
        """Expand dropped folders into every importable file inside."""
        files: list[str] = []
        for p in paths_in:
            if os.path.isdir(p):
                files.extend(scan_folder(p))
            elif os.path.splitext(p)[1].lower() in SUPPORTED_EXTS:
                files.append(p)
        return files

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                ext = os.path.splitext(p)[1].lower()
                if ext in SUPPORTED_EXTS or os.path.isdir(p):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        dropped = [url.toLocalFile() for url in event.mimeData().urls()
                   if url.isLocalFile()]
        paths_ = self._expand_drop(dropped)
        if paths_:
            event.acceptProposedAction()
            for d in dropped:
                if os.path.isdir(d):
                    folders.remember_folder(d)
            self._import_many(paths_)

    # ================================================================== #
    # playback
    # ================================================================== #
    def _on_play_button(self) -> None:
        self._on_play_button_src(self.sender())

    def _on_play_button_src(self, src) -> None:
        if src is self.btn_stop:
            self.player.stop()
        elif src is self.btn_play_deck:
            if self.player.is_playing():
                self.player.stop()
            else:
                self.player.play_deck(self.deck)
        else:
            self.player.play_current(self.deck)

    def _on_play_state(self, playing: bool) -> None:
        if playing:
            self._previewed = True
            self._update_workflow()
        self.btn_play_deck.setText("  Stop" if playing else "  Play deck")
        self.btn_play_deck.setIcon(icons.icon(
            "stop" if playing else "play", "#ffffff"))
        self.btn_play_deck.setProperty("primary", playing)
        self.btn_play_deck.style().unpolish(self.btn_play_deck)
        self.btn_play_deck.style().polish(self.btn_play_deck)
        self.btn_play_slide.setEnabled(not playing)
        self.btn_pause.setEnabled(playing)
        self.btn_pause.setText("  Pause")
        self.waveform.set_playing(playing)
        if not playing:
            self.play_label.setText("Idle")
            self._refresh_waveform_idle()

    def _on_play_entered(self, idx: int) -> None:
        self._current_index = idx
        self.slide_list.blockSignals(True)
        self.slide_list.setCurrentRow(idx)
        self.slide_list.blockSignals(False)
        self.canvas.set_index(idx)

    # ------------------------------------------------------------------ #
    # audio waveform strip (canvas footer)
    # ------------------------------------------------------------------ #
    def _on_player_narration(self, path: str) -> None:
        """Playback moved to a new slide: show that file's waveform."""
        if path:
            self.waveform.show_path(path)

    def _on_player_position(self, pos: int, dur: int) -> None:
        if dur > 0:
            self.waveform.set_progress(pos / dur)

    def _refresh_waveform_idle(self) -> None:
        """Idle state: show the selected slide's cached narration, if any.

        Never synthesizes — the waveform appears once the narration has
        been cached by a preview (or TTS generation).
        """
        if self.player.is_playing():
            return
        path = ""
        slides = self.deck.slides
        if slides:
            i = max(0, min(self._current_index, len(slides) - 1))
            if slides[i].effective_narration().strip():
                path = tts.cached_narration_path(slides[i], self.deck) or ""
        if path:
            self.waveform.show_path(path)
        else:
            self.waveform.set_message(
                "Narration waveform — appears after the slide's audio is "
                "cached (Play slide, Ctrl+P)")

    def voices_loaded(self, voices: list, online: bool) -> None:
        self.inspector.set_voices(voices)

    # ================================================================== #
    # diagnostics
    # ================================================================== #
    def show_diagnostics(self):
        """Open (or raise + refresh) the non-modal diagnostics report."""
        if self.diag_dlg is None:
            self.diag_dlg = build_diagnostics_dialog(self.deck, self)
        else:
            self.diag_dlg.refresh(self.deck)
        self.diag_dlg.show()
        self.diag_dlg.raise_()
        self.diag_dlg.activateWindow()
        return self.diag_dlg

    # ================================================================== #
    # misc
    # ================================================================== #
    def _about(self) -> None:
        QMessageBox.about(
            self, "About Slideshow Studio",
            "<b>Slideshow Studio</b> " + APP_VERSION + "<br>"
            "Create narrated slideshows and export them to MP4, HTML, "
            "PDF handouts or PowerPoint.<br>"
            "<br>"
            "<b>Guided workflow</b>: the pipeline bar tracks Import → "
            "Narrate → Preview → Export, and <b>Quick convert</b> "
            "(Ctrl+M) turns input files into finished MP4s in one step<br>"
            "Import: PPTX · PPT (via LibreOffice) · PDF · HTML · TXT · MD "
            "· photos (one slide each)<br>"
            "<b>Batch export</b>: queue many decks &amp; files (even a "
            "whole folder) and render them all in one run — "
            "Ctrl+Shift+E<br>"
            "Editing: rich-text (HTML) bodies · layout templates · "
            "text script mode · find &amp; replace · zoomable canvas · "
            "dark &amp; light themes<br>"
            "Narration: <b>edge-tts</b> (online) · <b>Piper</b> (local, "
            "offline) · <b>Qwen TTS</b> (DashScope API)<br>"
            "Voice models &amp; caches manager (Tools menu): download or "
            "delete Piper models with live progress<br>"
            "Smart memory: reopens your last session, remembers each "
            "deck's place, prunes old caches<br>"
            "<b>Folders</b> manager: pick where browsing starts, where "
            "exports land (per-deck or date-stamped subfolders) and "
            "where temporary render files go — <b>tmp/</b> in the "
            "working directory by default, pruned and cleanable<br>"
            "TTS text cleaning: emoji/markdown/URLs/symbols stripped "
            "before speaking<br>"
            "<b>Named export presets</b> recall a whole export "
            "configuration in one click, and a live <b>narration "
            "waveform</b> under the canvas lets you click to seek while "
            "previewing<br>"
            "Motion &amp; transitions (per-slide overrides) · subtitles "
            "(.srt or burned in)<br>"
            "Overlays: slide numbers · progress bar · watermark text<br>"
            "Present: full-screen with narration (F6), presenter notes "
            "(N) and rehearsal timing capture<br>"
            "Bundled examples: File ▸ Import example · exports go to the "
            "<b>output</b> folder<br>"
            "Headless: <code>python main.py deck.slideshow --headless "
            "--format mp4</code> for scripts &amp; CI<br>"
            "Video: ffmpeg<br><br>"
            "Built with PySide6.")

    def _script_help(self) -> None:
        QMessageBox.information(
            self, "Text script format",
            "<b>The whole deck as plain text</b><br><br>"
            "<code># Slide title</code> starts a new slide; the body "
            "follows (a blank line starts a new paragraph).<br><br>"
            "<code>~ Narration text</code> is what the TTS voice speaks "
            "— several <code>~</code> lines are joined; "
            "<code>Narration:</code> / <code>Notes:</code> work too.<br><br>"
            "<code>---</code> starts a slide without a title. A leading "
            "<code>\\</code> escapes a special first character, so a body "
            "line can literally start with <code>#</code> or <code>~</code> "
            "(a literal backslash is written as two).<br><br>"
            "<b>Script editor</b> (Ctrl+Shift+T): edit the deck as text, "
            "then Apply. Images, voices, motion and durations stay on "
            "their slides; untouched blocks keep HTML formatting.<br><br>"
            "<b>Find &amp; replace</b> (Ctrl+F) searches titles, bodies "
            "and narrations — HTML tags are never touched.")

    def _html_help(self) -> None:
        QMessageBox.information(
            self, "Rich text & HTML bodies",
            "<b>Editing slide bodies</b><br><br>"
            "The <b>Visual</b> view is a word-processor: bold, italic, "
            "lists, colours, highlights, links. Pasted content is "
            "sanitised automatically.<br><br>"
            "The <b>HTML source</b> view edits the markup directly. "
            "Supported tags:<br>"
            "<code>p · h1-h3 · b · strong · i · em · u · s · sub · sup · "
            "ul · ol · li · blockquote · pre · code · br · a href · "
            "span/font colour</code><br><br>"
            "The <b>Plain text</b> view is the classic mode: a blank line "
            "starts a new paragraph.<br><br>"
            "Typography (font family/size) always follows the theme, and "
            "long text auto-shrinks to fit the slide.")

    def _check_ffmpeg(self) -> None:
        ok, msg = media.is_available()
        if ok:
            QMessageBox.information(self, "ffmpeg", f"OK — {msg}")
        else:
            QMessageBox.warning(self, "ffmpeg", msg)

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._confirm_discard():
            event.ignore()
            return
        self.player.stop()
        try:
            self.waveform.shutdown()
        except RuntimeError:
            pass
        if self.present_win is not None:
            try:
                self.present_win.close()
            except RuntimeError:
                pass
            self.present_win = None
        if self.rehearse_win is not None:
            try:
                self.rehearse_win.close()
            except RuntimeError:
                pass
            self.rehearse_win = None
        if self.script_dlg:
            self.script_dlg.close()
        if self.find_dlg:
            self.find_dlg.close()
        if self.models_dlg:
            self.models_dlg.close()
        if self.folders_dlg:
            try:
                self.folders_dlg.close()
            except RuntimeError:
                pass
            self.folders_dlg = None
        if self.shortcut_dlg:
            try:
                self.shortcut_dlg.close()
            except RuntimeError:
                pass
            self.shortcut_dlg = None
        # smart memory: snapshot the on-screen deck + place for next start
        if not self._session_skip:
            try:
                memory.save_session(self.deck, self._current_index,
                                    self.tabs.currentIndex())
                self._remember_deck_state()
            except Exception:
                pass
        self._remove_autosave()
        # professional temp hygiene: a clean exit leaves no tmp/ litter
        # behind (a custom working folder is left untouched)
        try:
            folders.remove_temp_dir_if_empty()
        except Exception:
            pass
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("splitter", self.split.saveState())
        super().closeEvent(event)

    def _load_settings(self) -> None:
        geo = self.settings.value("geometry")
        if geo:
            self.restoreGeometry(geo)
        split = self.settings.value("splitter")
        if split:
            self.split.restoreState(split)
        # theme (apply without re-saving)
        theme = str(self.settings.value("theme", "dark"))
        self.act_dark.blockSignals(True)
        self.act_dark.setChecked(theme != "light")
        self.act_dark.blockSignals(False)
        styles.apply_theme(QApplication.instance(),
                           "dark" if theme != "light" else "light")
        self._on_zoom_changed()


def QApplication_setWaitCursor(on: bool) -> None:
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication
    if on:
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
    else:
        QApplication.restoreOverrideCursor()


def apply_dark_theme(app) -> None:
    styles.apply_theme(app, "dark")
