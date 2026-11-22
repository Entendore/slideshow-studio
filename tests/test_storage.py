"""Storage: app paths, .slideshow project workspace, smart memory."""
import json
import os
import zipfile

import pytest

from app import memory, paths, workspace
from app.models import Deck, Slide, VoiceSettings


# ------------------------------------------------------------------- paths
def test_app_dir_contains_main_entry():
    assert os.path.isfile(os.path.join(paths.app_dir(), "main.py"))


def test_examples_folder_ships_importable_decks():
    ex = paths.examples_dir()
    assert os.path.isdir(ex)
    files = paths.list_examples()
    assert len(files) >= 6
    assert all(os.path.isfile(f) for f in files)
    # README.txt sorts first so it tops the menu
    assert os.path.basename(files[0]) == "README.txt"


def test_describe_example_labels():
    label = paths.describe_example("/x/demo-tour.slideshow")
    assert "Demo tour" in label and "project" in label
    assert "PowerPoint" in paths.describe_example("/x/a.pptx")
    assert "Markdown" in paths.describe_example("/x/a.md")
    assert "PDF" in paths.describe_example("/x/a.pdf")


def test_sanitize_stem_strips_illegal_characters():
    assert paths.sanitize_stem("a<b>c") == "a_b_c"
    out = paths.sanitize_stem('d:"e/f\\g|h?i*j')
    assert out == "d__e_f_g_h_i_j"          # each illegal char becomes _
    assert not set('<>:"/\\|?*') & set(out)  # no illegal characters remain
    assert paths.sanitize_stem("   ") == "slideshow"
    assert paths.sanitize_stem("") == "slideshow"
    assert paths.sanitize_stem("  ok  ") == "ok"


def test_default_output_path_avoids_collisions():
    first = paths.default_output_path("collide-test", "mp4")
    stem = os.path.splitext(os.path.basename(first))[0]
    for suffix in ("", "-2", "-3"):
        open(os.path.join(paths.output_dir(), f"{stem}{suffix}.mp4"),
             "a").close()
    second = paths.default_output_path("collide-test", "mp4")
    assert second.endswith("-4.mp4")
    for suffix in ("", "-2", "-3", "-4"):
        try:
            os.remove(os.path.join(paths.output_dir(), f"{stem}{suffix}.mp4"))
        except OSError:
            pass


def test_importable_exts_cover_all_sources():
    for ext in (".pptx", ".ppt", ".pdf", ".html", ".htm", ".txt", ".md",
                ".markdown", ".slideshow"):
        assert ext in paths.IMPORTABLE_EXTS


# --------------------------------------------------------------- workspace
def _deck_with_media(png):
    d = Deck()
    d.name = "StorageDeck"
    s1 = d.new_slide(title="With image", narration="n1")
    s1.image = png
    d.new_slide(title="Plain", narration="n2")
    return d


def test_project_roundtrip_repoints_media(png_image):
    d = _deck_with_media(png_image)
    path = os.path.join(paths.output_dir(), "pytest_proj.slideshow")
    workspace.save_project(d, path)
    assert os.path.isfile(path)
    d2 = workspace.load_project(path)
    assert d2.name == "StorageDeck"
    assert d2.project_path == path
    img = d2.slides[0].image
    assert img and os.path.isabs(img) and os.path.isfile(img)
    assert d2.slides[1].title == "Plain"
    # re-save the loaded copy: paths are absolute now
    path2 = path.replace("pytest_proj", "pytest_proj2")
    workspace.save_project(d2, path2)
    d3 = workspace.load_project(path2)
    assert len(d3.slides) == 2
    os.remove(path)
    os.remove(path2)


def test_project_stores_and_restores_music(tmp_path, tone_wav):
    d = Deck()
    d.music_path = tone_wav
    d.music_volume = 0.25
    d.new_slide(title="s")
    path = str(tmp_path / "music_proj.slideshow")
    workspace.save_project(d, path)
    d2 = workspace.load_project(path)
    assert d2.music_path and os.path.isfile(d2.music_path)
    assert abs(d2.music_volume - 0.25) < 1e-6


def test_load_project_rejects_non_project_zip(tmp_path):
    p = tmp_path / "bad.slideshow"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("other.json", "{}")
    with pytest.raises(ValueError):
        workspace.load_project(str(p))


def test_load_project_rejects_garbage(tmp_path):
    p = tmp_path / "garbage.slideshow"
    p.write_bytes(b"not a zip at all")
    with pytest.raises(Exception):
        workspace.load_project(str(p))


def test_load_project_flattens_zip_path_traversal(tmp_path):
    p = tmp_path / "evil.slideshow"
    with zipfile.ZipFile(p, "w") as zf:
        data = Deck().to_dict()
        zf.writestr("project.json", json.dumps(data))
        zf.writestr("media/../../evil_escape.txt", b"x")
    workspace.load_project(str(p))
    media_root = os.path.dirname(workspace.media_dir())
    assert not os.path.isfile(os.path.join(media_root, "evil_escape.txt"))


def test_stage_media_copies_into_workspace(png_image):
    staged = workspace.stage_media(png_image)
    assert os.path.isfile(staged)
    assert staged.startswith(workspace.media_dir())
    assert staged != png_image


def test_stage_image_saves_png():
    from PySide6.QtGui import QColor, QImage
    img = QImage(40, 30, QImage.Format.Format_RGB32)
    img.fill(QColor("#112233"))
    staged = workspace.stage_image(img)
    assert staged.endswith(".png") and os.path.isfile(staged)
    loaded = QImage(staged)
    assert not loaded.isNull()


def test_workspace_layout_helpers():
    ws = workspace.workspace_dir()
    assert os.path.isdir(ws)
    assert workspace.media_dir().startswith(ws)
    assert workspace.narr_cache_dir().startswith(ws)
    assert workspace.piper_dir().startswith(ws)
    assert workspace.autosave_path().startswith(ws)
    assert workspace.session_path().startswith(ws)


# ------------------------------------------------------------------ memory
def test_session_snapshot_roundtrip(make_deck):
    d = make_deck(3, "SessionDeck")
    d.project_path = "/tmp/fake/project.slideshow"
    assert memory.save_session(d, index=2, tab=1) is True
    info = memory.session_info()
    assert info is not None
    assert info["slides"] == 3 and info["index"] == 2 and info["tab"] == 1
    assert info["name"] == "SessionDeck"
    assert info["path"] == "/tmp/fake/project.slideshow"
    deck, meta = memory.load_session()
    assert len(deck.slides) == 3 and meta["index"] == 2
    memory.clear_session()
    assert memory.session_info() is None
    assert memory.load_session() is None
    # the snapshot never mutates the live deck's project path
    assert d.project_path == "/tmp/fake/project.slideshow"


def test_per_deck_state_remembered_and_forgotten():
    memory.save_deck_state("/tmp/fake/a.slideshow", index=4, tab=2)
    st = memory.load_deck_state("/tmp/fake/a.slideshow")
    assert st == {"index": 4, "tab": 2}
    memory.forget_deck_state("/tmp/fake/a.slideshow")
    assert memory.load_deck_state("/tmp/fake/a.slideshow") == {}
    memory.save_deck_state("", 1, 1)          # empty path is a no-op


def test_narration_cache_stats_prune_and_clear():
    import time
    d = workspace.narr_cache_dir()
    f_old = os.path.join(d, "old.mp3")
    f_new = os.path.join(d, "new.mp3")
    for f in (f_old, f_new):
        with open(f, "wb") as fh:
            fh.write(b"x" * 600)
    old_t = time.time() - 90 * 86400
    os.utime(f_old, (old_t, old_t))
    count, total = memory.narration_cache_stats()
    assert count >= 2 and total >= 1200
    assert memory.prune_narration_cache(days=60) >= 1
    assert not os.path.isfile(f_old) and os.path.isfile(f_new)
    removed = memory.clear_narration_cache()
    assert removed >= 1
    assert memory.narration_cache_stats()[0] == 0
    assert memory.prune_narration_cache(days=0) == 0   # disabled


def test_reopen_last_toggle_roundtrip():
    saved = memory.reopen_last_enabled()
    try:
        memory.set_reopen_last_enabled(False)
        assert memory.reopen_last_enabled() is False
        memory.set_reopen_last_enabled(True)
        assert memory.reopen_last_enabled() is True
    finally:
        memory.set_reopen_last_enabled(saved)
