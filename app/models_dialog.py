"""Voice models & caches manager (Tools ▸ Voice models & caches…).

One place to see and manage everything the speech engines need:

  • Piper voice models — the full catalog with size + status, download with
    live progress (runs in a QThread so the UI stays responsive), delete to
    reclaim disk space, open the models folder.
  • Edge voice list cache — count + age, one-click refresh.
  • Narration cache — file count / total size, clear on demand.
  • Qwen TTS — endpoint + key state (it is an API model: nothing to
    download, the key lives in the Deck & Theme tab).

Emits `modelsChanged` after any model/cache mutation so the main window can
refresh the engine status line and the diagnostics report.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QProgressBar, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import tts, workspace


def human_size(n: float) -> str:
    if n <= 0:
        return "—"
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class _PiperDownloadThread(QThread):
    """Downloads one Piper voice model with progress reporting."""
    progress = Signal(int, int)          # done bytes, total bytes (-1 ?)
    ok = Signal(str)                     # voice id
    failed = Signal(str)                 # friendly error message

    def __init__(self, voice_id: str, parent=None):
        super().__init__(parent)
        self.voice_id = voice_id

    def run(self) -> None:
        try:
            tts.download_piper_voice(
                self.voice_id,
                progress=lambda done, total:
                    self.progress.emit(done, total))
            self.ok.emit(self.voice_id)
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceModelsDialog(QDialog):
    """Non-modal manager for TTS voice models and caches."""
    modelsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice models & caches — Slideshow Studio")
        self.setModal(False)
        self.resize(720, 540)
        self._thread: _PiperDownloadThread | None = None
        self._confirm = self._confirm_default       # test seam
        self._build()
        self.populate()

    # ---------------------------------------------------------------- #
    # UI
    # ---------------------------------------------------------------- #
    def _build(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        head = QLabel("Speech models & caches")
        head.setProperty("heading", True)
        lay.addWidget(head)

        hint = QLabel("Piper voices run fully offline; missing models are "
                      "also fetched automatically on first use (≈60 MB "
                      "each, from huggingface.co).")
        hint.setProperty("hint", True)
        hint.setWordWrap(True)
        lay.addWidget(hint)

        # ---- piper model table -----------------------------------------
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setHeaderLabels(["Voice", "Language", "Quality",
                                   "Size", "Status"])
        self.tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection)
        self.tree.itemSelectionChanged.connect(self._sync_buttons)
        lay.addWidget(self.tree, 1)

        # ---- model buttons ----------------------------------------------
        row = QHBoxLayout()
        self.btn_download = QPushButton("Download")
        self.btn_download.setToolTip("Download the selected voice model "
                                     "(≈60 MB, stays usable offline)")
        self.btn_download.clicked.connect(self._download_selected)
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setToolTip("Delete the selected voice model to "
                                   "reclaim disk space")
        self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_folder = QPushButton("Open models folder")
        self.btn_folder.clicked.connect(self._open_models_folder)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setToolTip("Re-scan the models folder")
        self.btn_refresh.clicked.connect(self.populate)
        for b in (self.btn_download, self.btn_delete, self.btn_folder,
                  self.btn_refresh):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.hide()
        lay.addWidget(self.progress)
        self.status_label = QLabel("")
        self.status_label.setProperty("hint", True)
        lay.addWidget(self.status_label)

        # ---- caches ------------------------------------------------------
        self.cache_label = QLabel("")
        self.cache_label.setProperty("hint", True)
        self.cache_label.setWordWrap(True)
        lay.addWidget(self.cache_label)
        crow = QHBoxLayout()
        self.btn_edge_refresh = QPushButton("Refresh edge voice list")
        self.btn_edge_refresh.setToolTip(
            "Drop the cached Microsoft voice list; the next list refresh "
            "fetches all current voices again")
        self.btn_edge_refresh.clicked.connect(self._refresh_edge_cache)
        self.btn_clear_cache = QPushButton("Clear narration cache")
        self.btn_clear_cache.setToolTip(
            "Delete cached narration audio; it is re-synthesised on the "
            "next preview/export")
        self.btn_clear_cache.clicked.connect(self._clear_narration_cache)
        crow.addWidget(self.btn_edge_refresh)
        crow.addWidget(self.btn_clear_cache)
        crow.addStretch(1)
        lay.addLayout(crow)

        # ---- qwen ---------------------------------------------------------
        self.qwen_label = QLabel("")
        self.qwen_label.setProperty("hint", True)
        self.qwen_label.setWordWrap(True)
        lay.addWidget(self.qwen_label)

        # ---- close ---------------------------------------------------------
        brow = QHBoxLayout()
        brow.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        brow.addWidget(btn_close)
        lay.addLayout(brow)

    # ---------------------------------------------------------------- #
    # population
    # ---------------------------------------------------------------- #
    def populate(self) -> None:
        selected = self.selected_voice()
        self.tree.clear()
        for v in tts.PIPER_VOICES:
            vid = v["ShortName"]
            installed = tts.piper_voice_installed(vid)
            item = QTreeWidgetItem([
                vid,
                v["Locale"],
                v["Quality"],
                human_size(tts.piper_model_size(vid)) if installed
                else "≈60 MB",
                "installed" if installed else "not downloaded",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, vid)
            if installed:
                item.setToolTip(4, "Stored in the app workspace — usable "
                                   "offline")
            self.tree.addTopLevelItem(item)
        self._sync_buttons()
        self._update_cache_labels()
        if selected:
            items = self.tree.findItems(
                selected, Qt.MatchFlag.MatchExactly, 0)
            if items:
                self.tree.setCurrentItem(items[0])

    def selected_voice(self) -> str | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def selected_status(self) -> str:
        item = self.tree.currentItem()
        if item is None:
            return ""
        return item.text(4)

    def _sync_buttons(self) -> None:
        busy = self._thread is not None and self._thread.isRunning()
        vid = self.selected_voice()
        installed = self.selected_status() == "installed"
        self.btn_download.setEnabled(
            bool(vid) and not busy and not installed)
        self.btn_delete.setEnabled(bool(vid) and not busy and installed)
        self.btn_refresh.setEnabled(not busy)
        self.btn_edge_refresh.setEnabled(not busy)
        self.btn_clear_cache.setEnabled(not busy)

    def _update_cache_labels(self) -> None:
        from . import memory
        n_voices, age = tts.edge_cache_info()
        if age < 0:
            edge_txt = "no cache yet — the list is fetched online once"
        elif age < 3600:
            edge_txt = f"cached {int(age / 60)} min ago"
        else:
            edge_txt = f"cached {int(age / 3600)} h ago"
        n_narr, size_narr = memory.narration_cache_stats()
        n_piper = tts.piper_installed_count()
        self.cache_label.setText(
            f"Edge voice list: {n_voices} voices, {edge_txt} · "
            f"Narration cache: {n_narr} files "
            f"({human_size(size_narr)}) · Piper models: {n_piper} of "
            f"{len(tts.PIPER_VOICES)} installed "
            f"({human_size(tts.piper_total_size())})")
        key = tts.get_qwen_api_key()
        key_txt = ("configured" if key else
                   "not set (set it in Deck & Theme ▸ Narration engine)")
        self.qwen_label.setText(
            f"Qwen TTS: model {tts.QWEN_MODEL} · endpoint "
            f"{tts.get_qwen_region()} · API key {key_txt}")

    # ---------------------------------------------------------------- #
    # actions
    # ---------------------------------------------------------------- #
    def _download_selected(self) -> None:
        vid = self.selected_voice()
        if not vid or (self._thread is not None
                       and self._thread.isRunning()):
            return
        self.progress.setValue(0)
        self.progress.show()
        self.status_label.setText(f"Downloading {vid} …")
        self._thread = _PiperDownloadThread(vid, self)
        self._thread.progress.connect(self._on_download_progress)
        self._thread.ok.connect(self._on_download_ok)
        self._thread.failed.connect(self._on_download_failed)
        self._sync_buttons()
        self._thread.start()

    def _on_download_progress(self, done: int, total: int) -> None:
        if total and total > 0:
            pct = int(done * 100 / total)
            self.progress.setValue(min(100, pct))
            self.status_label.setText(
                f"Downloading {self.selected_voice()} … "
                f"{human_size(done)} / {human_size(total)} ({pct}%)")
        else:
            self.status_label.setText(
                f"Downloading {self.selected_voice()} … "
                f"{human_size(done)}")

    def _on_download_ok(self, vid: str) -> None:
        self.progress.hide()
        self.status_label.setText(f"✓ {vid} downloaded — ready to use "
                                  "offline.")
        self.populate()
        self.modelsChanged.emit()

    def _on_download_failed(self, msg: str) -> None:
        self.progress.hide()
        self.status_label.setText("✗ Download failed.")
        self._sync_buttons()
        QMessageBox.warning(self, "Download failed", msg)

    def _delete_selected(self) -> None:
        vid = self.selected_voice()
        if not vid or self.selected_status() != "installed":
            return
        if not self._confirm(vid):
            return
        tts.piper_delete_voice(vid)
        self.status_label.setText(f"Deleted {vid}.")
        self.populate()
        self.modelsChanged.emit()

    def _confirm_default(self, vid: str) -> bool:
        ret = QMessageBox.question(
            self, "Delete voice model",
            f"Delete the downloaded model for {vid}?\n"
            "You can download it again at any time.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return ret == QMessageBox.StandardButton.Yes

    def _open_models_folder(self) -> None:
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(workspace.piper_dir()))

    def _refresh_edge_cache(self) -> None:
        tts.edge_cache_clear()
        self.status_label.setText(
            "Edge voice list cache cleared — press ↻ Refresh voices in the "
            "Deck & Theme tab to fetch the current list.")
        self._update_cache_labels()
        self.modelsChanged.emit()

    def _clear_narration_cache(self) -> None:
        from . import memory
        ret = QMessageBox.question(
            self, "Clear narration cache",
            "Delete all cached narration audio?\n"
            "Nothing is lost — audio is simply re-synthesised on the next "
            "preview or export.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ret != QMessageBox.StandardButton.Yes:
            return
        n = memory.clear_narration_cache()
        self.status_label.setText(f"Removed {n} cached narration file(s).")
        self._update_cache_labels()
        self.modelsChanged.emit()
