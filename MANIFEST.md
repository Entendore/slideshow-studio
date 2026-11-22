# Slideshow Studio — Project Manifest

Complete inventory of the project as of **version 2.7**. For the user-facing
guide see [README.md](README.md); for the narrative summary see the
completion report (`slideshow-studio-completion-report.pdf` in the release
folder).

- **What it is** — a cross-platform PySide6 desktop studio for building,
  editing, narrating and exporting slide decks (MP4 / MP3 / WAV / standalone
  HTML / **PDF handout** / **PowerPoint .pptx**) with three text-to-speech
  engines — plus a **headless command-line export** for scripts and CI.
- **Size** — ~15,900 lines of application code in `app/`, 385 automated
  tests in `tests/`, 79-check end-to-end smoke suite in the dev `scripts/`.
- **Inputs** — `.slideshow` projects, `.pptx`, `.ppt`, `.pdf`, `.html`,
  `.txt`, `.md`, **images** (`.png/.jpg/.jpeg/.bmp/.webp/.gif` — one photo
  per slide) plus drag & drop of files or whole folders.

---

## 1. Root files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — creates the QApplication, ensures `output/` exists, opens the studio (optionally restoring the last session); with `--headless` routes to the command-line exporter, `python main.py deck.slideshow` opens the project in the editor |
| `README.md` | Feature guide, install/run instructions, import formats, shortcuts, tech notes |
| `MANIFEST.md` | This file — full project inventory |
| `pytest.ini` | Pytest configuration: test paths + `slow` / `online` markers |
| `requirements.txt` | Runtime dependencies (PySide6, edge-tts, python-pptx, PyMuPDF, beautifulsoup4) |
| `app/` | Application package (41 modules, see §2) |
| `tests/` | Pytest suite (18 files, 385 tests, see §3) |
| `scripts/` | `run_tests.py` — headless runner for the pytest suite |
| `examples/` | **Input folder** — bundled sample decks (see §4) |
| `output/` | Bundled default destination for exports (auto-created; *File ▸ Input & output folders…* can point exports anywhere) |
| `docs/` | Screenshots and a sample HTML export (see §5) |

## 2. Application modules (`app/`)

| Module | Lines | Responsibility |
|--------|------:|----------------|
| `__init__.py` | 3 | Package marker + `APP_VERSION` ("2.7") |
| `main_window.py` | 2238 | Main window: menus, toolbar, three-pane layout, guided workflow bar, undo/redo, recents, autosave, session restore, drag & drop (files and folders, incl. photo folders and dropped projects), folder-manager wiring incl. temp-folder actions and startup temp pruning, rehearse-timings + slide-still export, **narration waveform strip under the canvas with idle/cached + playback modes and click-to-seek (v2.7)**, all dialogs wiring |
| `models.py` | 338 | Data model — `Deck` / `Slide` / `Theme` / `VoiceSettings`, motion presets, **canonical transition names + per-slide transition override (v2.6)**, preset themes, JSON (de)serialisation |
| `workspace.py` | 160 | `.slideshow` project files (ZIP: project.json + media), workspace/media/narration-cache/piper folders, autosave & session paths |
| `importers.py` | 690 | Import dispatch + PPTX (notes, pictures, rich runs), legacy PPT (via LibreOffice), PDF (page plates + text), HTML (document-order walk), TXT/MD (script format), **images** (photo → slide, staged + titled); all scratch files go through the managed working folder |
| `render.py` | 307 | The one shared painter (1600×900 design space) for canvas, thumbnails and video frames; deck-level overlays (numbers, progress bar, watermark) |
| `canvas.py` | 352 | Zoomable WYSIWYG canvas (8–400 %, Ctrl+wheel anchored, pan by drag, paste image background, drop import) |
| `slide_list.py` | 171 | Thumbnail list with reordering, drag & drop, per-slide marker icons, context menu |
| `inspector.py` | 509 | Per-slide inspector: title, three-view body, narration + "Speaks:" preview, voice/engine override with slider gating, motion, **per-slide enter-transition (v2.6)**, duration, background image |
| `deck_panel.py` | 593 | Deck & Theme panel: preset themes, overlays, TTS engine + default voice, Qwen key/endpoint, cleaning toggles, narration tools, music, piper status |
| `export_dialog.py` | 661 | Single-deck export dialog: MP4 / audio / HTML / **PDF handout (with notes pages) / PowerPoint**, **named export presets (combo + Save…/Delete, factory seed, last-selection memory, *(custom)* auto-flip on manual edits, v2.7)**, resolution, transition, pause, subtitles, music, output suggestion honouring the folder settings; post-export Play / open-folder-when-finished / Export again; `exported` signal for the workflow bar |
| `presets.py` | 224 | **Named export presets (v2.7)**: `Preset` model (14 export options, JSON round-trip, bad-value degradation), nine factory presets, QSettings persistence with one-time factory seeding + corrupt-storage reset, upsert/find helpers, one-line `describe()` summaries |
| `waveform.py` | 288 | **Narration waveform strip (v2.7)**: ffmpeg PCM decode → 900 peak buckets in 0..1, `WaveformLoader` QThread that only reports the newest requested path, `WaveformBar` widget (theme-aware mirrored peak bars, played-part highlight, playhead cursor, hint messages, click/drag-to-seek signal, clean shutdown) |
| `export_worker.py` | 608 | `ExportWorker` QThread pipeline: render → TTS → per-slide libx264/AAC segments → concat or xfade chain with **per-slide transition overrides incl. mixed cut/fade graphs (`transition_graph`, v2.6)** → subtitle burn-in / ducked music mix; **duration overrides act as a minimum** when narration exists; audio-only MP3/WAV; **document modes (pdf/pptx) delegated to document_export, no ffmpeg needed**; scratch lives in the managed working folder and is removed when the job ends |
| `rehearse.py` | 266 | **Rehearse timings (v2.6)**: full-screen silent runner with a big per-slide stopwatch + total run time, present-mode navigation, time banking (revisits add up), `finishedRun` signal + summary formatter for the apply step |
| `document_export.py` | 200 | **PDF handout & PowerPoint export (v2.5)**: every slide rendered through the shared painter at 2000 px into the managed working folder, then PyMuPDF pages (960×540 pt 16:9, optional interleaved notes pages with thumbnail + spoken text) or python-pptx slides (full-bleed picture + narration in the speaker-notes pane); progress + check callables, scratch always cleaned |
| `cli.py` | 199 | **Headless command-line export (v2.5)**: argparse (`--headless --format mp4|mp3|wav|html|pdf|pptx`, `--out/--notes/--no-music/--srt/--resolution/--voice/--version`), offscreen Qt, project/file/folder sources, synchronous `ExportWorker` run with stdout progress, exit codes 0/1/2 |
| `batch_dialog.py` | 779 | Batch export queue (files / folder scan / current deck), per-job status, collision-safe names, cancel-after-current, persisted options; browse dialogs start in the configured input/output folders |
| `quick_convert.py` | 612 | Quick convert dialog (Ctrl+M): input files / folder / drag-drop → narrated MP4s in one run — auto-narration from slide text, voice override, sequential workers, per-file status, Play last / Open folder; output defaults to the configured output folder |
| `folders.py` | 825 | **Input, output & working-folder management (v2.3/v2.4)**: settings-backed input folder, output root and layout policy (flat / per-deck / date-stamped), organised + collision-safe output paths, browse-start-dir resolution, recent-folders memory, folder validation/stats — plus **temp management (v2.4)**: working folder defaulting to `tmp/` in the current directory, custom override, fallback chain (cwd › app › system temp), pid-safe scratch dirs/files, age-filtered cleanup, startup prune, clean-exit tidy-up — all edited in the File ▸ Input & output folders… dialog |
| `workflow.py` | 124 | Guided pipeline bar: Import → Narrate → Preview → Export MP4 chips with done/current/todo states, next-action hint, one-click stage shortcuts |
| `html_export.py` | 298 | Standalone self-contained HTML slideshow (embedded images as data URLs, theme CSS, notes, keyboard/touch nav, fullscreen, print) |
| `htmlfmt.py` | 345 | Sanitised rich-text subset: whitelist tags/styles, formatting-span normalisation, html⇄plain, auto-fit QTextDocument builder |
| `html_editor.py` | 496 | Three-view body editor (visual word processor / HTML source / plain text) with sanitised paste and mode conversion |
| `script_mode.py` | 198 | Pure-Python deck ⇄ text-script serializer/parser with escaping + word/speak-time stats |
| `script_editor.py` | 255 | Script editor dialog: whole deck as one text document, live stats, apply/refresh/import/export, find hook |
| `find_replace.py` | 287 | Deck-wide find & replace; HTML bodies edited inside text nodes only (markup-safe) |
| `subtitles.py` | 102 | `.srt` builder: sentence-boundary cue splitting, transition-aware start offsets |
| `tts.py` | 677 | Engine dispatch + catalogs: edge-tts (online, voice cache), Piper (offline ONNX, model download/delete), Qwen TTS (DashScope, chunked); content-hash narration cache |
| `tts_sanitize.py` | 213 | Spoken-text cleaner: emoji, markdown, URLs, unicode symbols, abbreviations — each step toggleable |
| `media.py` | 115 | ffmpeg/ffprobe detection, cancellation-aware `run()` with stderr tails, duration probing |
| `memory.py` | 202 | Smart memory: session snapshot, per-deck place memory, narration-cache pruning/clear, reopen-at-startup toggle |
| `models_dialog.py` | 331 | Voice models & caches manager: 16-voice Piper catalog with download/delete + progress, edge cache refresh, narration cache clear |
| `diagnostics.py` | 324 | Diagnostics report (versions, tools, engines, storage, folders incl. input/output/layout/working-temp folder, live deck stats incl. **transition overrides + minimum durations (v2.6)**) + copy-to-clipboard dialog with open-folder shortcuts |
| `player.py` | 235 | In-app preview player: background pre-synthesis, slide-advance in sync with narration, pause/resume, **position/duration + current-narration signals and fractional seeking for the waveform strip (v2.7)** |
| `present.py` | 424 | Full-screen present mode: auto-advance, on-screen subtitles, **presenter notes panel with live per-slide clock (N, v2.6)**, keyboard/click nav |
| `templates.py` | 77 | Five layout templates (Title, Title+content, Bullet list, Quote, Section header) |
| `icons.py` | 335 | Runtime-drawn line-icon set (no binary assets), recolourable |
| `styles.py` | 585 | Design-token palette → complete dark/light QSS themes + generated glyph assets (incl. workflow-bar chips) |
| `widgets.py` | 113 | Reusable layout kit: `SectionCard` (collapsible), `PanelButton`, `HRule` |
| `paths.py` | 95 | App-relative `examples/` + `output/` resolution, filename sanitation, example helpers, shared importable-extension list (incl. images) |

## 3. Test suite (`tests/`)

351 pytest tests. Run everything with
`python scripts/run_tests.py` (or `python -m pytest`); skip the slow ffmpeg
exports with `-m "not slow"`; `online` marks the one network-dependent test.

| File | Tests | Covers |
|------|------:|--------|
| `conftest.py` | — | Offscreen QApplication, sandboxed QSettings/QStandardPaths, offline TTS stubs, tone/PNG fixtures, event-spin helper |
| `test_models.py` | 22 | Deck/Slide/Theme/VoiceSettings round-trips, clamped edits, engine prefixes, five layout templates |
| `test_htmlfmt.py` | 16 | Sanitiser (scripts/handlers/external resources stripped), style whitelist, html⇄plain, heuristics |
| `test_text_tools.py` | 32 | SRT cues & timing, TTS text cleaning steps, script-mode round-trip with escaping, format-safe find & replace |
| `test_importers.py` | 16 | TXT/MD rules incl. escapes and chunking, HTML splitting + stripping, PDF pages, PPTX notes/pictures/bold runs, dispatch errors, all bundled examples |
| `test_storage.py` | 18 | Paths & name sanitation, project save/load incl. media/music, traversal guard, autosave paths, session snapshot, per-deck state, cache prune/clear |
| `test_render.py` | 19 | Shared renderer (solid/gradient/HTML/image/placeholder), overlay pixels, icon catalog, dark/light QSS, SectionCard behaviour |
| `test_media_tts.py` | 23 | ffmpeg run/cancel/probe, engine catalogs, voice-list cache & offline fallback, narration-cache round-trip, Piper install cycle + real offline synthesis, Qwen key/chunking/mocked HTTP, online edge-tts check |
| `test_export.py` | 13 | ExportWorker MP4 (motion, transitions, burned subtitles, music mix), MP3/WAV + `.srt` sidecars, cancel-before-start, empty-deck error, standalone HTML export |
| `test_gui_main.py` | 31 | MainWindow: deck ops, undo/redo coalescing, imports, save/reload, recents, autosave, session restore, menus, dialogs (script/find/export/diagnostics/shortcuts), fill/clear narrations, zoom |
| `test_gui_panels.py` | 22 | Inspector bindings + per-engine slider gating + spoken preview, deck panel (engines, Qwen key, cleaning, overlays, presets, voices), canvas paste/zoom, slide list, three-view body editor incl. sanitised paste |
| `test_player_present.py` | 10 | Preview player lifecycle (synth thread, pause, end-of-media advance, empty deck) and full-screen present mode navigation/toggles |
| `test_features.py` | 18 | Diagnostics sections/copy, voice-model manager (catalog, install/delete, signals, cache clears), batch queue (dedupe, scan, gating, settings, HTML & MP4 end-to-end runs, cancel) |
| `test_workflow.py` | 14 | Guided pipeline bar (states, tips, clicks), workflow lifecycle in the main window (import → narrate → preview → export, undoable narrate step), quick convert (gating, list ops, deck prep, settings, MP4 end-to-end run with failure + cancel paths), export dialog post-export actions (Play, exported signal, open-when-finished) |
| `test_folders.py` | 18 | Folder settings layer (input/output/layout round-trips, layout subfolders, organised + collision-safe paths, suggestion priority, recents incl. cap/dedupe/gone-folders, validation, stats, browse-dir fallbacks), folder-manager dialog (save/reset/recent actions/validation), main-window wiring (manager open, open-input-folder hint + reveal, import dialog starts in the input folder, folder-drop expansion), export-dialog suggestion honouring the output settings, quick-convert default output, diagnostics folder rows |
| `test_temp.py` | 16 | **Working (temp) folder (v2.4)**: cwd default + custom override round-trip, fallback chain (unusable cwd → app folder → system temp) with recorded reason, pid-safe scratch dirs/paths, cleanup (full + age-filtered), safety guards (`/`, home, home parent), auto-clean + remove-if-empty (default only), export worker + PDF/PPTX importers routed through the manager (scratch staged and removed), folder-manager temp group (stats, validation, reset, Clean-up-now), main-window menu actions + startup prune + closeEvent tidy-up, diagnostics working-folder row incl. fallback note |
| `test_share_automate.py` | 28 | **Share & automate (v2.5)**: PDF handout export (pages, 16:9 geometry, embedded images, metadata, interleaved notes pages with caption + spoken text, progress callback, cancel mid-render with scratch cleaned, empty-deck rejection), PowerPoint export (slide count, 16:9 EMU, full-bleed pictures, speaker notes incl. title+body fallback, core properties, cancel), worker wiring for the pdf/pptx modes, image import (PNG/JPG/GIF → staged slides with humanised titles, dispatch, non-image rejection), folder scan + drop expansion incl. photos, export dialog (5 formats, notes checkbox visibility + settings round-trip, .pdf/.pptx output suggestions), headless CLI (`--version`, PDF/HTML/PPTX exports, photo-folder conversion, bad source → 1, usage errors → 2, `main.main()` routing) |
| `test_present_pro.py` | 35 | **Present like a pro (v2.6)**: rehearse window (time banking, revisit accumulation, finish signal, empty-deck safety, main-window apply/discard flow with undo, closeEvent cleanup, summary formatter), presenter notes panel (toggle, narration + fallback content, empty-slide hint, live clock, reset per slide, timer stop on close, hint text), per-slide transitions (model round-trip + validation, label→ffmpeg mapping, transition-graph builder incl. mixed cut/fade graphs with operand normalisation, worker join resolution deck-default vs override, inspector combo round-trip, diagnostics rows), slide → image (2000-px PNG file export, clipboard copy, menu actions + shortcut, no-slide safety), minimum-duration semantics (`max(audio + pad, override)`), slow end-to-end MP4 with a per-slide transition and a mixed cut+fade batch |
| `test_presets_wave.py` | 34 | **Presets & waveform (v2.7)**: `Preset` round-trips + bad-value degradation + `describe()` per mode, upsert/find purity, factory seed once into QSettings + reload + corrupt-JSON reset + edit persistence, export dialog (factory list + descriptions as tooltips, preset applies values/visibility, last-preset remembered + restored on reopen, manual edit flips to *(custom)*, save upsert via stubbed QInputDialog incl. overwrite, empty-name ignored, delete persists + custom no-op, running state disables preset controls), waveform peaks (shape/range/bucket counts, silence ≈ 0, missing file raises), `WaveformBar` (paint in hint/data/playing states, clamped progress, QTest click/drag seek, click-without-data ignored), async loader (deliver + stale-result guard + failure report), `show_path` (async load, same-path playhead reset, empty clears, stale `_on_loaded` dropped), player position/duration signals + clamped `seek_fraction`, main window (bar present + wired, idle refresh reads cached narration with correct engine extension and cache-size rule, play-state flag) |

## 4. Input folder (`examples/`) — bundled sample decks

Loaded via **File ▸ Import example**; the batch exporter and importers can
consume them as-is. `README.txt` sorts first on purpose so it tops the menu.

| File | Slides | Format | What it demonstrates |
|------|-------:|--------|----------------------|
| `README.txt` | 3 | text script | Folder guide that is itself a valid slide script (`#` headings, `~` narration) |
| `getting-started.txt` | 5 | text script | The plain-text deck format: headings, body paragraphs, `~ narration` lines |
| `product-launch.md` | 4 | Markdown | Markdown import with narration lines |
| `team-update.html` | 4 | HTML | `h1/h2` slide splitting with rich-text bodies (bold, lists) preserved |
| `solar-power.pptx` | 3 | PowerPoint | PPTX import incl. speaker notes → narration and picture background |
| `quantum-computing.pdf` | 3 | PDF | Page-render plates with extracted text/narration |
| `demo-tour.slideshow` | 5 | project | Fully configured project: Ken Burns motion, slide numbers + progress bar + watermark overlays, per-slide narration, one rich (HTML) body |

## 5. Docs (`docs/`)

| File | Content |
|------|---------|
| `screenshot.png` | Main window, dark theme |
| `screenshot-light.png` | Light theme |
| `screenshot-script.png` | Script editor |
| `screenshot-diagnostics.png` | Diagnostics report |
| `screenshot-engines.png` | Engine/voice controls |
| `screenshot-models.png` | Voice models & caches manager |
| `screenshot-batch.png` | Batch export dialog |
| `screenshot-quick.png` | Quick convert dialog |
| `screenshot-folders.png` | Input & output folders manager |
| `screenshot-export.png` | Export dialog with the PDF handout format + notes pages (v2.5) |
| `screenshot-present.png` | Present mode with the presenter notes panel + slide clock (v2.6) |
| `screenshot-rehearse.png` | Rehearse-timings runner with the per-slide stopwatch (v2.6) |
| `screenshot-presets.png` | Export dialog with the YouTube 1080p preset applied (v2.7) |
| `sample-export.html` | Example of the standalone HTML slideshow export |

## 6. Development scripts (outside the shipped package)

| Script | Purpose |
|--------|---------|
| `scripts/smoke_test.py` | 79-check end-to-end smoke suite (imports, rendering, TTS, 6 ffmpeg exports, batch run, quick-convert run, folder + temp management, PDF/PPTX export, image import, headless CLI, rehearse + notes + per-slide transitions + slide stills, export presets + waveform) |
| `scripts/run_tests.py` | Headless runner for the pytest suite (env setup + pytest passthrough) |
| `scripts/run_v16/v17/v19/v20_tests.py` | Fast per-version iteration subsets kept from earlier releases |
| `scripts/make_examples.py` | Regenerates the 7 bundled examples idempotently |
| `scripts/make_samples.py` | Builds the raw import samples used by tests |
| `scripts/make_screenshot.py` + per-feature shot scripts | Regenerate `docs/*.png` headlessly |
| `scripts/verify_packaged_v20.py` | Sanity-checks the packaged copy in `download/` (updated per release — v2.7 ships `verify_packaged_v27.py`) |

## 7. Version history

| Version | Release focus |
|---------|---------------|
| 1.0 | Core studio: import PPT/PDF/HTML/TXT, three-pane editor, MP4 export with edge-tts narration, preview player, background music |
| 1.1–1.5 | Incremental polish: project save/load, recents, autosave, audio-only export, subtitles, motion/transitions |
| 1.6 | Rich-text bodies (sanitised HTML subset + three-view editor), HTML slideshow export, script mode with find & replace, three TTS engines (edge / Piper / Qwen), TTS text cleaning, present mode, templates, professional themed UI |
| 1.7 | Bundled `examples/` input folder + `output/` destination wired into the GUI (import examples, open folders, default export destination) |
| 1.8 | Help ▸ Diagnostics report with copy-to-clipboard |
| 1.9 | Smart memory (session snapshot, per-deck place memory, cache hygiene) + Voice models & caches manager |
| 2.0 | Batch export queue (files / folders / current deck → MP4/MP3/WAV/HTML with per-job status) |
| 2.1 | Quality release: 240-test pytest suite, `MANIFEST.md`, completion report; packaging refreshed |
| 2.2 | Guided input→MP4 workflow: pipeline bar (Import → Narrate → Preview → Export MP4), Quick convert dialog (Ctrl+M), export dialog post-export actions; 254-test suite |
| 2.3 | Professional input & output folder management: File ▸ Input & output folders… manager (input folder, output root, flat/per-deck/date-stamped layout, live stats + validation, recent folders), organised export paths, dialogs start in the configured folders, folder-drop import; 272-test suite |
| 2.4 | Professional temp folder management: managed working folder in the **current working directory** (`tmp/`), custom override + graceful fallback chain, every pipeline scratch file routed through it, startup prune of stale leftovers, Clean-up-now + Tools ▸ Clean temp folder, File ▸ Open temp folder, diagnostics row, clean-exit tidy-up; 287-test suite |
| 2.5 | **Share & automate**: **PDF handout export** (16:9 pages, optional interleaved notes pages) and **PowerPoint .pptx export** (rendered slides + narration as speaker notes) — both without ffmpeg, with cancel + progress; **image import** (photos become slides; folders of photos become slideshows via drag & drop or scan); **headless CLI export** (`python main.py deck.slideshow --headless --format mp4/pdf/pptx/…` with voice override, `.srt`, resolution, exit codes for CI); export dialog gains the two formats + notes option; dropped `.slideshow` projects import their slides; 315-test suite, 72-check smoke suite |
| 2.6 | **Present like a pro & finer control**: **Rehearse timings** (Tools ▸ Rehearse timings… — silent full-screen runner with a per-slide stopwatch, summary + one-undo Apply that stores each time as the slide's **minimum duration**, `max(audio, duration)` semantics so narration is never cut); **presenter notes** in present mode (N — speaker notes + live per-slide clock); **per-slide transition overrides** (inspector combo: deck default / any transition / forced hard cut, resolved per join in the export worker, mixed cut+fade graphs normalised for ffmpeg); **slide stills** (File ▸ Export current slide as image… 2000-px PNG/JPG, Edit ▸ Copy slide image Ctrl+Shift+C); diagnostics gains transition-override + minimum-duration counts; 351-test suite, 76-check smoke suite |
| 2.7 | **Presets & waveform**: **named export presets** — every export-dialog option stored under a memorable name with nine factory presets (YouTube 1080p, Podcast MP3, PDF handout + notes, …), Save/Delete management, one-click recall, *(custom)* auto-flip on manual edits, last selection restored between runs, corrupt-storage reset; **narration waveform strip** under the canvas — live loudness shape of the playing slide's audio with playhead + played-part highlight, click/drag to seek, idle view of the selected slide's cached narration (strictly offline, stale-result-guarded async decode); player publishes position/duration + current-narration signals; 385-test suite, 79-check smoke suite |
