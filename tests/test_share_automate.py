"""v2.5 'Share & automate': PDF handout export, PowerPoint export,
image import (photo slideshows) and the headless command-line export.

The suite is fully offline: documents render with the shared painter,
the CLI paths avoid TTS/ffmpeg (PDF / PPTX / HTML), and every scratch
folder must be gone by the time a test finishes.
"""
import os

import pytest


@pytest.fixture
def deck(make_deck):
    d = make_deck(3, name="Share deck")
    return d


@pytest.fixture
def project_file(deck, tmp_path):
    from app import workspace
    path = str(tmp_path / "share-deck.slideshow")
    deck.project_path = path
    workspace.save_project(deck, path)
    return path


@pytest.fixture
def photo_folder(tmp_path, png_image):
    """A folder with two photos + one text file + one hidden subdir."""
    from PIL import Image
    from PIL.ImageDraw import ImageDraw

    folder = tmp_path / "photos"
    folder.mkdir()
    for i, color in enumerate(((170, 60, 60), (60, 120, 170))):
        img = Image.new("RGB", (240, 135), color)
        ImageDraw(img).text((20, 60), f"photo {i + 1}", fill="white")
        img.save(str(folder / f"vacation_day-{i + 1}.jpg"))
    img2 = Image.new("RGB", (64, 64), (20, 90, 50))
    img2.save(str(folder / "logo.png"))
    (folder / "notes.txt").write_text("# A note\nbody")
    hidden = folder / ".hidden"
    hidden.mkdir()
    (hidden / "secret.png").write_bytes(b"not really an image")
    return folder


# ------------------------------------------------------------------ #
# PDF handout
# ------------------------------------------------------------------ #
def test_pdf_export_basic(deck, tmp_path):
    import fitz

    from app import document_export
    out = str(tmp_path / "handout.pdf")
    assert document_export.export_pdf(deck, out) == out
    doc = fitz.open(out)
    assert doc.page_count == 3
    page = doc[0]
    assert (page.rect.width, page.rect.height) == (960, 540)
    assert page.get_images()                       # slide picture embedded
    assert doc.metadata["title"] == "Share deck"
    assert doc.metadata["author"] == "Slideshow Studio"
    doc.close()


def test_pdf_export_with_notes(deck, tmp_path):
    import fitz

    from app import document_export
    out = str(tmp_path / "handout-notes.pdf")
    document_export.export_pdf(deck, out, notes=True)
    doc = fitz.open(out)
    assert doc.page_count == 6                     # slide + notes, per slide
    # even pages are slides, odd pages are notes with the spoken text
    assert doc[0].get_text().strip() == ""
    notes_text = doc[1].get_text()
    assert "Narration for slide 1." in notes_text
    assert "1. Slide 1" in notes_text              # numbered caption
    doc.close()


def test_pdf_export_progress_and_cancel(deck, tmp_path):
    from app import document_export, folders

    seen = []
    out = str(tmp_path / "handout.pdf")
    document_export.export_pdf(
        deck, out, on_progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (3, 3)
    assert os.path.isfile(out)

    class Cancelled(Exception):
        pass

    calls = []

    def _chk():
        calls.append(1)
        if len(calls) > 1:
            raise Cancelled()

    with pytest.raises(Cancelled):
        document_export.export_pdf(
            deck, str(tmp_path / "never.pdf"), check=_chk)
    # the scratch folder was removed despite the cancellation
    root = folders.temp_dir()
    assert [f for f in os.listdir(root) if f.startswith("docs-")] == []


def test_pdf_empty_deck_rejected(tmp_path):
    from app import document_export
    from app.models import Deck
    with pytest.raises(RuntimeError):
        document_export.export_pdf(Deck(), str(tmp_path / "none.pdf"))


# ------------------------------------------------------------------ #
# PowerPoint
# ------------------------------------------------------------------ #
def test_pptx_export(deck, tmp_path):
    from pptx import Presentation
    from pptx.util import Emu

    from app import document_export
    out = str(tmp_path / "deck.pptx")
    assert document_export.export_pptx(deck, out) == out
    prs = Presentation(out)
    assert len(prs.slides) == 3
    assert (prs.slide_width, prs.slide_height) == (Emu(12192000),
                                                   Emu(6858000))
    for i, slide in enumerate(prs.slides):
        pics = [sh for sh in slide.shapes
                if sh.shape_type == 13]        # PICTURE
        assert len(pics) == 1
        assert pics[0].width == prs.slide_width   # full-bleed
        notes = slide.notes_slide.notes_text_frame.text
        assert notes == f"Narration for slide {i + 1}."
    assert prs.core_properties.title == "Share deck"
    assert "Slideshow Studio" in prs.core_properties.author


def test_pptx_export_title_narration_fallback(tmp_path):
    """Slides without narration fall back to title + body in the notes."""
    from pptx import Presentation

    from app import document_export
    from app.models import Deck
    d = Deck()
    d.new_slide(title="Only a title", body="And a body line.")
    out = str(tmp_path / "fallback.pptx")
    document_export.export_pptx(d, out)
    prs = Presentation(out)
    notes = prs.slides[0].notes_slide.notes_text_frame.text
    assert "Only a title" in notes and "And a body line." in notes


def test_pptx_empty_deck_rejected(tmp_path):
    from app import document_export
    from app.models import Deck
    with pytest.raises(RuntimeError):
        document_export.export_pptx(Deck(), str(tmp_path / "none.pptx"))


# ------------------------------------------------------------------ #
# worker wiring (pdf / pptx modes)
# ------------------------------------------------------------------ #
def test_export_worker_pdf_mode(deck, tmp_path):
    from app.export_worker import ExportOptions, ExportWorker

    out = str(tmp_path / "worker.pdf")
    w = ExportWorker(deck, ExportOptions(mode="pdf", out_path=out,
                                         notes=True))
    got = {}
    w.finished_ok.connect(lambda p: got.update(path=p))
    w.failed.connect(lambda m: got.update(err=m))
    w.run()
    assert got.get("path") == out and "err" not in got
    assert os.path.isfile(out)
    import fitz
    assert fitz.open(out).page_count == 6


def test_export_worker_pptx_mode(deck, tmp_path):
    from app.export_worker import ExportOptions, ExportWorker

    out = str(tmp_path / "worker.pptx")
    w = ExportWorker(deck, ExportOptions(mode="pptx", out_path=out))
    got = {}
    w.finished_ok.connect(lambda p: got.update(path=p))
    w.failed.connect(lambda m: got.update(err=m))
    w.run()
    assert got.get("path") == out and "err" not in got
    assert os.path.isfile(out)


def test_document_scratch_is_cleaned(deck, tmp_path):
    """Both document exports leave nothing in the working folder."""
    from app import document_export, folders
    document_export.export_pdf(deck, str(tmp_path / "a.pdf"))
    document_export.export_pptx(deck, str(tmp_path / "b.pptx"))
    root = folders.temp_dir()
    assert [f for f in os.listdir(root) if f.startswith("docs-")] == []


# ------------------------------------------------------------------ #
# image import (photo slideshows)
# ------------------------------------------------------------------ #
def test_import_image(png_image):
    from app import importers

    slides = importers.import_image(png_image)
    assert len(slides) == 1
    s = slides[0]
    assert s.title == "Sample img"      # humanised filename
    assert s.image and os.path.isfile(s.image)
    assert s.body == "" and s.narration == ""


def test_import_image_jpg_and_gif(tmp_path):
    from PIL import Image

    from app import importers
    jpg = tmp_path / "sunset_beach.jpg"
    Image.new("RGB", (32, 32), (200, 120, 40)).save(str(jpg))
    gif = tmp_path / "loop.gif"
    Image.new("RGB", (32, 32), (10, 10, 10)).save(str(gif))
    s1 = importers.import_image(str(jpg))[0]
    s2 = importers.import_image(str(gif))[0]
    assert s1.title == "Sunset beach"
    assert s2.title == "Loop"
    assert os.path.isfile(s1.image) and os.path.isfile(s2.image)


def test_import_image_rejects_non_image(tmp_path):
    from app import importers
    junk = tmp_path / "song.mp3"
    junk.write_bytes(b"ID3")
    with pytest.raises(importers.ImportError_):
        importers.import_image(str(junk))


def test_import_file_dispatches_images(png_image):
    from app import importers
    slides = importers.import_file(png_image)
    assert len(slides) == 1 and slides[0].image


def test_folder_scan_includes_photos(photo_folder):
    from app.batch_dialog import scan_folder
    found = [os.path.basename(p) for p in scan_folder(str(photo_folder))]
    assert "vacation_day-1.jpg" in found and "logo.png" in found
    assert "notes.txt" in found
    assert "secret.png" not in found        # hidden dirs are skipped


def test_dropped_folder_expands_to_photos(photo_folder):
    from app import main_window, paths
    files = main_window.MainWindow._expand_drop([str(photo_folder)])
    exts = {os.path.splitext(p)[1].lower() for p in files}
    assert ".jpg" in exts and ".png" in exts and ".txt" in exts
    assert all(os.path.splitext(p)[1].lower() in paths.IMPORTABLE_EXTS
               for p in files)


# ------------------------------------------------------------------ #
# export dialog: the two new formats
# ------------------------------------------------------------------ #
def test_export_dialog_document_formats(qapp, deck):
    from PySide6.QtCore import QSettings

    from app.export_dialog import ExportDialog
    QSettings("ZaiStudio", "SlideshowStudio").setValue("exp/mode_idx", 0)
    dlg = ExportDialog(deck)
    assert dlg.mode_combo.count() == 5

    dlg.mode_combo.setCurrentIndex(3)       # PDF handout
    assert dlg.mode_combo.currentText().startswith("PDF handout")
    assert not dlg.notes_check.isHidden()
    assert dlg.res_combo.isHidden() and dlg.srt_check.isHidden()

    dlg.mode_combo.setCurrentIndex(4)       # PowerPoint
    assert dlg.notes_check.isHidden()
    assert dlg.res_combo.isHidden()

    dlg.mode_combo.setCurrentIndex(0)       # MP4 again
    assert dlg.notes_check.isHidden() and not dlg.res_combo.isHidden()

    # output suggestion follows the chosen format
    dlg.mode_combo.setCurrentIndex(3)
    dlg.out_edit.clear()
    dlg._suggest_out()
    assert dlg.out_edit.text().endswith(".pdf")
    dlg.mode_combo.setCurrentIndex(4)
    dlg.out_edit.clear()
    dlg._suggest_out()
    assert dlg.out_edit.text().endswith(".pptx")
    dlg.close()


def test_export_dialog_notes_setting_roundtrip(qapp, deck):
    from PySide6.QtCore import QSettings

    from app.export_dialog import ExportDialog
    s = QSettings("ZaiStudio", "SlideshowStudio")
    s.setValue("exp/mode_idx", 3)
    s.setValue("exp/notes", "true")
    dlg = ExportDialog(deck)
    assert dlg.notes_check.isChecked()
    dlg.notes_check.setChecked(False)
    dlg._save_settings()
    assert s.value("exp/notes") in (False, "false", "0")
    s.setValue("exp/mode_idx", 0)
    dlg.close()


def test_export_dialog_suggestion_refresh(qapp, deck):
    """Switching format refreshes auto-suggested paths (not user paths)."""
    from PySide6.QtCore import QSettings

    from app.export_dialog import ExportDialog
    QSettings("ZaiStudio", "SlideshowStudio").setValue("exp/mode_idx", 0)
    dlg = ExportDialog(deck)
    assert dlg.out_edit.text().endswith(".mp4")
    dlg.mode_combo.setCurrentIndex(3)           # stale .mp4 → .pdf
    assert dlg.out_edit.text().endswith(".pdf")
    dlg.mode_combo.setCurrentIndex(4)           # → .pptx
    assert dlg.out_edit.text().endswith(".pptx")
    # a path the user typed is never overwritten
    dlg.out_edit.setText("/tmp/keep-me.mp4")
    dlg.mode_combo.setCurrentIndex(0)
    assert dlg.out_edit.text() == "/tmp/keep-me.mp4"
    dlg.close()


# ------------------------------------------------------------------ #
# headless command line
# ------------------------------------------------------------------ #
def test_cli_version(capsys):
    from app import APP_VERSION, cli
    assert cli.run(["--version"]) == 0
    assert APP_VERSION in capsys.readouterr().out


def test_cli_usage_errors():
    from app import cli
    with pytest.raises(SystemExit) as e:      # argparse usage error
        cli.run(["--headless", "--format", "bogus"])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:      # headless without a project
        cli.run(["--headless"])
    assert e.value.code == 2


def test_cli_pdf_export(project_file, tmp_path, capsys):
    from app import cli
    out = str(tmp_path / "cli.pdf")
    assert cli.run([project_file, "--headless", "--format", "pdf",
                    "--notes", "--out", out]) == 0
    assert os.path.isfile(out)
    assert "Saved:" in capsys.readouterr().out


def test_cli_pptx_from_source(png_image, tmp_path):
    """The CLI converts raw source files (e.g. a photo) directly."""
    from app import cli
    out = str(tmp_path / "cli.pptx")
    assert cli.run([png_image, "--headless", "--format", "pptx",
                    "--out", out]) == 0
    assert os.path.isfile(out)


def test_cli_html_export(project_file, tmp_path):
    from app import cli
    out = str(tmp_path / "cli.html")
    assert cli.run([project_file, "--headless", "--format", "html",
                    "--out", out]) == 0
    assert os.path.isfile(out) and os.path.getsize(out) > 0


def test_cli_photo_folder(photo_folder, tmp_path):
    from app import cli
    out = str(tmp_path / "photos.pptx")
    assert cli.run([str(photo_folder), "--headless", "--format", "pptx",
                    "--out", out]) == 0
    from pptx import Presentation
    # 3 photos + 1 text file -> 4 slides
    assert len(Presentation(out).slides) == 4


def test_cli_bad_source_fails_cleanly(tmp_path, capsys):
    from app import cli
    rc = cli.run([str(tmp_path / "missing.slideshow"), "--headless",
                  "--format", "pdf", "--out", str(tmp_path / "x.pdf")])
    assert rc == 1
    assert "error:" in capsys.readouterr().err


def test_cli_bad_resolution(project_file, tmp_path, capsys):
    from app import cli
    rc = cli.run([project_file, "--headless", "--format", "mp4",
                  "--resolution", "8K", "--out", str(tmp_path / "x.mp4")])
    assert rc == 1
    assert "resolution" in capsys.readouterr().err


def test_main_entry_routes_headless(project_file, monkeypatch, tmp_path):
    """main.main() dispatches to the CLI when --headless is present."""
    import main as main_mod
    from app import cli
    calls = []
    monkeypatch.setattr(cli, "run", lambda argv: calls.append(argv) or 0)
    monkeypatch.setattr(main_mod.sys, "argv",
                        ["main.py", project_file, "--headless",
                         "--format", "pdf"])
    assert main_mod.main() == 0
    assert calls and calls[0][0] == project_file
