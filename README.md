# Slideshow Studio

A cross-platform **PySide6** desktop app for making, editing and narrating
slide decks — and exporting them to **MP4 video** with natural
**text-to-speech** narration (Microsoft neural voices via `edge-tts`), a
**standalone HTML slideshow**, a **PDF handout** (with printable notes
pages) or a real **PowerPoint .pptx** — with a headless command-line mode
for scripts and CI.

![screenshot](docs/screenshot.png)

## Features

| Area | Details |
|------|---------|
| **Professional UI** | Cohesive dark **and light** themes built from one design-token palette (Ctrl+T switches), a hand-drawn line-icon set, collapsible inspector cards, card-style slide thumbnails, a **zoomable canvas** (Ctrl+wheel, pan by drag, Fit / 100%), grouped icon toolbar, scrolling side panels, and window/splitter state that persists between sessions |
| **Layout templates** | New slides start from **five ready-made layouts** — Title slide, Title + content, Bullet list, Quote, Section header — via *Slide ▸ Add slide from template*; the default **+** uses Title + content |
| **Video overlays** | Deck-wide, WYSIWYG in canvas, thumbnails and the MP4: **slide numbers** (bottom-right), a **progress bar** along the bottom edge, and a small **watermark text** (bottom-left) for branding |
| **Import** | `.pptx` (text, pictures, speaker notes) · `.pdf` (page image + text) · `.html` (split at h1/h2/h3, **formatting preserved**) · `.txt` / `.md` (Markdown-ish) · legacy `.ppt` (auto-converts via LibreOffice if installed) · **photos** (`.png/.jpg/.jpeg/.bmp/.webp/.gif` — one slide each, filename becomes the title) · **drag & drop** files — or a whole **folder of sources / photo folder** — onto the window |
| **Rich text bodies** | Slide bodies are editable in three views: **Visual** word-processor (bold/italic/underline/strike, bullet & numbered lists, alignment, colours, highlights, links), **HTML source** editor of the sanitised markup subset, and classic **Plain text**. Everything pasted is sanitised automatically — scripts, event handlers and external resources can never enter a deck |
| **Text script mode** | Edit the **whole deck as one plain-text script** (`# Title`, body lines, `~ narration`) in a live word-count editor — **Apply** updates titles/bodies/narrations while images, voices, motion and durations stay on their slides; untouched blocks even keep HTML formatting. Export/import the script as a `.txt` file, or **Find & replace** (Ctrl+F) across every title, body and narration — HTML tags are never touched |
| **WYSIWYG** | One shared renderer draws the editor canvas, list thumbnails and the exported video frames — what you type is exactly what ships |
| **Motion** | Per-slide **Ken Burns** effects — zoom in/out, pan in four directions, combined zoom+pan, with an intensity slider (applied on MP4 export) |
| **Transitions** | Crossfade, fade to black, dissolve, wipes, slides, circle open — with adjustable duration, **deck-wide or per slide** (each slide can override how it enters, or force a hard cut; applied on MP4 export) |
| **Narration** | **Three TTS engines**, mixable per slide: **edge-tts** (Microsoft neural voices, online, free), **Piper** (fully local/offline ONNX voices, model files auto-download once), **Qwen TTS** (Alibaba Qwen3-TTS via your DashScope API key). Per-slide voice, rate, volume, pitch — or a deck-wide default. One-click voice preview and *apply voice to all slides*. Deck-wide **narration tools**: fill every empty narration from the slide text, or clear them all (both one undo step). Narration falls back to title + body text (HTML is stripped) when empty |
| **TTS text cleaning** | The text that is *spoken* is sanitized first (slide text is never modified): emoji & pictographs stripped, markdown marks removed, URLs replaced with “link”, unicode punctuation/symbols mapped to speakable words (arrows, ×, °, dashes…), common abbreviations expanded (e.g. → “for example”). Each step can be toggled per deck, and the inspector shows a live “Speaks: …” preview |
| **Subtitles** | Auto-generated `.srt` next to the exported file, and/or **burned into the video** (adjustable size) |
| **Themes** | 6 presets + full custom designer: solid/gradient background, title/body fonts, sizes, colors, accent bar, alignment, image dim overlay |
| **Playback** | In-app preview player: slides advance in sync with their TTS audio, with pause/resume — and a live **narration waveform** under the canvas: the loudness shape of the current slide's audio with a playhead, highlighted already-played part, **click or drag to seek** while playing; when idle it shows the selected slide's **cached** narration (never any network) |
| **Export presets** | Every option in the export dialog — format, resolution, audio codec, pause, transition + length, subtitles (save / burn / size), PDF notes pages, music mixing, auto-open — can be stored as a **named preset** and recalled with one click. Ships with nine factory presets (**YouTube 1080p**, *Quick preview 720p*, *Cinematic crossfade*, *Burned subtitles*, **Podcast MP3**, *Archive WAV*, *Web page*, **PDF handout + notes**, *PowerPoint + notes*); *Save…* / *Delete* manage your own, any manual edit flips the selector back to *(custom)* so it always tells the truth, and the last selection is remembered between runs |
| **Present mode** | **F6** runs the deck **full-screen like a real talk** — narration plays through the speakers, auto-advances when a slide's audio ends (toggle with **A**), optional on-screen **subtitles** (**S**), a **presenter notes panel** (**N**) showing the speaker notes plus a live per-slide clock, ←/→/Space/click navigation, Esc exits |
| **Rehearse timings** | **Tools ▸ Rehearse timings…** runs the deck like a talk (silent — you are the narrator) with a big stopwatch per slide and the total run time; when you finish, a summary shows every slide's recorded time and **Apply** writes them as each slide's **minimum duration** — exports then pace the deck exactly as you rehearsed it, and narration is never cut short (a slide with audio lasts `max(audio, duration)`) |
| **Export** | MP4 (480p–1440p, H.264 + AAC) · audio-only MP3/WAV · **HTML slideshow** — a single self-contained web page (theme backgrounds, embedded images, speaker notes, keyboard/touch navigation, fullscreen, print) · **PDF handout** — one 16:9 page per slide, optionally interleaved with **notes pages** (slide thumbnail + the text that would be spoken) · **PowerPoint (.pptx)** — 16:9 deck with the rendered slide full-bleed and the narration pre-filled as **speaker notes**, presentable and editable in PowerPoint / Google Slides / LibreOffice · **Slide stills** — `File ▸ Export current slide as image…` writes the slide you are editing as a 2000-px PNG/JPG (overlays included) and `Edit ▸ Copy slide image` (Ctrl+Shift+C) puts it straight on the clipboard. HTML/PDF/PPTX need no ffmpeg and no internet |
| **Headless CLI** | `python main.py deck.slideshow --headless --format mp4 --out video.mp4` — the exact GUI pipeline (renderer, TTS, ffmpeg) on the offscreen Qt platform, for scripts, cron jobs and CI. Formats: `mp4`, `mp3`, `wav`, `html`, `pdf`, `pptx`; options for `--out`, `--notes` (PDF), `--no-music`, `--srt`, `--resolution`, `--voice` override, `--version`. Sources can be projects, any importable file, or a whole folder (a photo folder becomes a slideshow); exit codes 0/1/2 make it automation-friendly |
| **Batch export** | **File ▸ Batch export…** (Ctrl+Shift+E) queues many slideshows and renders them all in one run: pick files (multi-select), scan a whole **folder** for importable decks, or add the deck currently open. Mixes `.slideshow` projects with PPTX/PDF/HTML/TXT/MD sources; one shared format for the whole batch (MP4 / MP3 / WAV / HTML) with resolution, transition, pause, music and `.srt` options; **per-file status & details** (Done / Failed with the error), collision-safe unique output names, overall progress, cancel-after-current-job, and a finish summary |
| **Guided workflow** | A **pipeline bar above the canvas** tracks your progress from input to finished video — **1 Import → 2 Narrate → 3 Preview → 4 Export MP4** — highlighting the current step with a next-action hint; every chip is a one-click shortcut (Narrate even auto-fills empty narrations). The **Export dialog** gains *Play* (watch the result immediately), *Open the output folder when finished*, and *Export again* after a completed run |
| **Quick convert** | **File ▸ Quick convert to MP4…** (Ctrl+M) is the fast lane from input to output: drop or pick files (`.slideshow` projects, PPTX, PDF, HTML, TXT, MD — or a whole folder), press **Convert ▸**, and every file becomes a finished narrated MP4 (+ optional `.srt`) in the output folder — slides imported, empty narrations auto-written from slide text, optional voice override, resolution/transition/pause options, live progress, cancel-after-current, and **Play last** / **Open folder** when done |
| **Folder management** | **File ▸ Input & output folders…** is one place for where files come from and where they go: set the **input folder** (import / script / project / save dialogs start there), the **output folder** (exports land there by default) and an **output layout** — flat, **one subfolder per deck**, or **date-stamped (YYYY-MM-DD)** subfolders. Both folders show live file/size stats and writable validation, and a **recently used folders** list remembers every folder you pick in any dialog (set as input / set as output / open / remove / clear). File ▸ Open input folder / Open output folder reveal either one. Drop a whole **folder of sources** on the window and every importable deck inside is imported |
| **Temp folder management** | Every job's scratch files (rendered PNG frames, video segments, converted documents) live in a managed **working folder** — `tmp/` inside the **current working directory** by default, with a graceful fallback chain (cwd › app folder › system temp) when the launch directory is read-only, and an optional custom folder in *File ▸ Input & output folders…*. Finished exports clean up after themselves; **leftovers older than a day are pruned at startup** (crashed runs leave nothing behind), a **Clean up now** button and **Tools ▸ Clean temp folder** reclaim space on demand, *File ▸ Open temp folder* reveals it, and a clean exit removes the folder entirely when it is empty — no `tmp/` litter in your working directory |
| **Music** | Optional looped background music mixed under the narration, with auto-ducking (side-chain compression) |
| **Projects** | Save/reopen `.slideshow` files (ZIP with deck JSON + all media), **recent projects** menu, and **autosave every 2 min with one-click recovery** |
| **Smart memory** | The studio **reopens where you left off**: the deck on screen at exit (saved or not) comes back on the next start — selected slide and inspector tab included — with a **Tools ▸ Reopen last session** action and a *Reopen last deck at startup* toggle. Each project's place (slide + tab) is remembered individually, and old narration-cache entries are pruned automatically |
| **Voice models & caches** | **Tools ▸ Voice models & caches…** manages everything the speech engines need in one non-modal dialog: the full **Piper catalog** with per-model size + status, **download with live progress** (threaded, ≈60 MB models), **delete to reclaim disk space**, open the models folder, **refresh the edge voice list cache**, and **clear the narration cache** — plus Qwen endpoint/key state at a glance |
| **Examples & output** | Ships **ready-made sample decks** in the bundled `examples/` folder — a text script, a Markdown deck, an HTML page, a PPTX with speaker notes, a PDF and a fully configured demo project (motion, overlays, narration). Load any of them via **File ▸ Import example**. Exports default to your configured **output folder** — the app's bundled `output/` folder (auto-created; *File ▸ Open output folder* reveals it) until you pick your own in *File ▸ Input & output folders…* |
| **Diagnostics** | **Help ▸ Diagnostics…** opens a non-modal report: app / Python / Qt / PySide6 versions, ffmpeg + ffprobe + LibreOffice detection, TTS engine status (edge-tts version, cached voice count, Piper models downloaded, Qwen key/endpoint), workspace & narration-cache usage, voice models, session snapshot, input/output/working-folder state and **live deck stats** (slides, narrations written, motion, overlays, engine/voice). One click copies the whole report to the clipboard for bug reports |

## Install

```bash
# 1. Python 3.10+ and ffmpeg are required
python -m pip install -r requirements.txt
```

### ffmpeg (required for MP4/MP3/WAV export)

- **Windows**  `winget install ffmpeg`   (or download from <https://ffmpeg.org>)
- **macOS**    `brew install ffmpeg`
- **Linux**    `sudo apt install ffmpeg`

Editing, importing, rendering and **HTML export** work without ffmpeg;
MP4/MP3/WAV export does not.

### Run

```bash
python main.py
```

## How to use

1. **Import** — `File ▸ Import slides…` (Ctrl+I) or drag PPTX/PDF/HTML/TXT/MD
   files — or images — onto the window. Choose *Replace* or *Append* when your
   deck already has slides. New here? Start from a bundled sample: `File ▸ Import example`
   loads one of the ready-made decks from the `examples/` folder next to the
   app — including `demo-tour.slideshow`, which arrives with motion, video
   overlays and narration already configured.
   The **pipeline bar** above the canvas tracks where you are —
   *Import → Narrate → Preview → Export MP4* — and every step is a
   one-click shortcut to the next action. In a hurry? **Ctrl+M** skips the
   editor entirely and turns input files straight into narrated MP4s.
2. **Edit** — pick a slide in the left list; edit title, body and narration in
   the *Slide* tab. The body editor has three views (picker on the right of
   its toolbar):
   - **Visual** — a mini word processor: B / I / U / S, bullet & numbered
     lists, alignment, text colour, highlight, links, clear formatting
     (Ctrl+B / Ctrl+I / Ctrl+U work too). Pasted web content is sanitised.
   - **HTML source** — edit the markup directly. Supported tags: `p`,
     `h1-h3`, `b strong i em u s del sub sup`, `ul ol li`, `blockquote`,
     `pre code`, `br`, `a href`, `span/font` colours, and the style keys
     `color`, `background-color`, `text-align`, `font-weight`,
     `font-style`, `text-decoration`. Typography (family/size) always
     follows the theme and long text auto-shrinks to fit.
   - **Plain text** — the classic mode: blank line = new paragraph.
   Use *Deck & Theme* for styling, default voice and background music.
   Made a mistake? **Ctrl+Z** (redo: Ctrl+Y) undoes locally in the editor
   first, then the deck.

   **Text script mode** — `Script ▸ Script editor…` (Ctrl+Shift+T) opens a
   non-modal editor that shows the entire deck as one plain-text document:

   ```text
   # Slide title
   Body text. A blank line starts a new paragraph.

   ~ Narration spoken by the TTS voice.

   ---

   # Next slide
   ```

   `~` (or `Narration:` / `Notes:`) lines set the narration; a leading `\`
   escapes a special first character. The toolbar shows live slide/word
   counts. **Apply to deck** (Ctrl+Return) parses the script back — matched
   slides keep their images, voices, motion and durations, and blocks you
   didn't touch keep their HTML formatting. **Refresh**, **Import script…**
   and **Export script…** round-trip `.txt` files (the TXT importer
   understands the same format). **Ctrl+F** finds and replaces text across
   every title, body and narration at once.
3. **Motion** — in the *Slide* tab, pick a Ken Burns preset (zoom / pan) and
   intensity; it is animated when the video is exported.
4. **Voice** — the *Deck & Theme* tab picks the narration **engine** and its
   default voice:
   - **Microsoft Edge voices (online)** — 400+ neural voices, free, needs
     internet. Supports rate / volume / pitch.
   - **Piper (local, offline)** — 16 built-in voice profiles; the model file
     (≈60 MB) downloads automatically on first use, then synthesis runs with
     no internet at all. Rate and volume apply; pitch is not available.
     **Tools ▸ Voice models & caches…** downloads or deletes models with
     live progress at any time.
   - **Qwen TTS (DashScope)** — paste your DashScope API key
     (International or China endpoint). Long narrations are chunked at
     sentence boundaries and merged automatically; rate/volume/pitch are
     not applied by this engine.
   The *Slide* tab can override the engine and voice per slide. Adjust rate /
   volume / pitch, hit **▶ Preview voice** to listen, or **Apply voice to all
   slides**. Right under the narration box a live **“Speaks: …”** preview
   shows the cleaned text the engine will read.
5. **Preview** — **▶ Play deck** (Ctrl+P or F5) plays the whole deck with
   narration in sync; **⏸ Pause** holds and resumes. The **waveform strip**
   under the canvas draws the narration's loudness shape with a moving
   playhead — click or drag anywhere on it to seek inside the current
   slide's audio. When you are not playing, it shows the selected slide's
   cached narration (it appears once the audio has been synthesized by a
   preview, so nothing ever touches the network from here).
6. **Present** — **F6** (or the monitor button in the control bar) starts
   full-screen presentation mode: each slide's narration plays, the deck
   auto-advances when the audio ends (toggle with **A**), **S** shows the
   narration as on-screen subtitles, ←/→/Space or click navigate, Esc exits.
7. **Save** — Ctrl+S saves a portable `.slideshow` project file. The app
   autosaves every 2 minutes and offers recovery after a crash
   (*File ▸ Restore autosave*). When you exit, the deck on screen is also
   remembered as a **session snapshot** and comes back on the next start
   (*Tools ▸ Reopen last session*, or let it happen automatically).
8. **Export** — Ctrl+E: pick **MP4**, **MP3/WAV**, **HTML slideshow**,
   **PDF handout** or **PowerPoint (.pptx)**.
   In a hurry? Pick a **preset** first — *YouTube 1080p*, *Podcast MP3*,
   *PDF handout + notes* … — and the whole dialog configures itself;
   *Save…* stores your current combination under any name (your presets
   survive restarts, and editing anything manually flips the selector to
   *(custom)*).
   For video: resolution, pause length, transition, subtitles and music
   options; progress and cancel supported. Tick *Save subtitles* to also get
   an `.srt` file (perfect for YouTube), or *Burn subtitles* to draw them
   into the picture. The suggested destination follows your **output
   folder** settings (*File ▸ Input & output folders…*): the bundled
   `output/` folder by default, or your own folder — honoured exactly, or
   organised into per-deck / date-stamped subfolders; the last folder you
   exported to is remembered too.
   When the export finishes, **Play** watches the result in your default
   player, **Open folder** reveals it, and the button turns into
   **Export again** — optionally opening the folder automatically.
   The **HTML slideshow** is one portable `.html` file:
   open in any browser, navigate with ← → / space / click / swipe, press
   **F** for fullscreen, **N** for speaker notes, **P** to print the whole
   deck. It embeds your theme colours, fonts and slide images — no ffmpeg,
   no internet, no dependencies.
   The **PDF handout** is one 16:9 page per slide at print quality; tick
   *Interleave notes pages* and every slide is followed by a page with its
   thumbnail and the text that would be spoken — great for courses,
   meetings and conference handouts. The **PowerPoint export** writes a
   real `.pptx`: each slide is the studio render full-bleed and the
   narration sits in the speaker-notes pane, so the deck stays editable in
   PowerPoint, Google Slides or LibreOffice. Both build from the same
   renderer as the canvas — what you see is what ships.
9. **Quick convert** — `File ▸ Quick convert to MP4…` (Ctrl+M): the
   shortest path from input to MP4. Add files (multi-select), drop them on
   the dialog, or add a whole folder; each file is imported, its empty
   narrations are auto-written from the slide text (toggleable), and a
   finished MP4 — with optional `.srt` subtitles — lands in the output
   folder. Voice override, resolution, transition and pause options are
   there if you want them; **Convert ▸** does the rest with live progress,
   per-file status, cancel-after-current and **Play last** when done.
10. **Batch export** — `File ▸ Batch export…` (Ctrl+Shift+E): click *Add
   files…* (multi-select), *Add folder…* (scans the folder for every
   importable slideshow, including `.slideshow` projects) or *Add current
   deck*. Choose one output format for the whole queue — **MP4**, **MP3**,
   **WAV** or **HTML** — plus resolution / transition / pause / music /
   `.srt` options, and an output folder (defaults to your configured
   output folder).
   **Start batch export** renders each deck sequentially with live overall
   progress and a per-file status column (Done, Failed — with the error in
   *Details*, or Skipped after a cancel). Output names are collision-safe
   (`Deck.mp4`, `Deck-2.mp4`, …), each deck keeps its own theme, voices,
   motion and narration, and all your format choices are remembered for
   the next batch.
11. **Folders** — `File ▸ Input & output folders…` keeps your file traffic
   in one place. The **input folder** is where the import, script and
   project dialogs start browsing; the **output folder** is where exports
   land; and the **output layout** decides whether everything sits flat in
   that folder or is organised into **one subfolder per deck** or
   **date-stamped (YYYY-MM-DD)** subfolders — so a week of exports never
   becomes one unsorted pile. Both rows show live file counts + sizes and
   warn about missing or read-only folders; every folder you pick in any
   dialog joins the **recently used** list for one-click reuse. *File ▸
   Open input folder* / *Open output folder* reveal them, and dropping a
   whole folder of sources on the window imports every deck inside.
12. **Temp folder** — the same manager dialog also owns the **working
    folder** where temporary render files go: `tmp/` inside the directory
    the app was started from. Point it anywhere with *Browse…* or press
    *Reset* to return to the default; *Open* reveals it, **Clean up now**
    deletes leftovers instantly, and stale scratch is pruned automatically
    at startup. Exports, quick convert, batch runs and document imports
    all keep their scratch there — and delete it again when done.
13. **Present, rehearse & grab stills** — **F6** presents full-screen with
    narration; press **N** for the **presenter notes panel** (speaker notes
    plus a live per-slide clock in the corner of the screen — the audience
    never sees it). To nail down pacing, run **Tools ▸ Rehearse timings…**:
    a silent full-screen runner with a big stopwatch — go through the deck
    as if you were talking, press **Esc**, check the per-slide summary and
    hit **Apply to slides** to store each time as that slide's **minimum
    duration** (one Ctrl+Z undoes it; exports never cut narration short —
    a slide with audio lasts `max(audio, duration)`). And when someone
    asks for "just slide 5", `File ▸ Export current slide as image…`
    saves it as a 2000-px PNG/JPG, or Ctrl+Shift+C copies it to the
    clipboard for pasting anywhere.
14. **Command line** — everything above also runs headless:

    ```bash
    python main.py deck.slideshow --headless --format mp4 --out video.mp4
    python main.py talk.pptx      --headless --format pdf --notes
    python main.py photos/        --headless --format mp4          # photo folder
    python main.py --version
    ```

    `--format` is one of `mp4`, `mp3`, `wav`, `html`, `pdf`, `pptx`; add
    `--no-music`, `--srt`, `--resolution`, `--voice ID` or `--out FILE` as
    needed. Progress prints on stdout, results go to `output/` (or your
    folder settings) unless `--out` is given, and the exit code is 0 on
    success, 1 on failure and 2 on usage errors — so cron jobs and CI
    pipelines can rely on it. `python main.py deck.slideshow` (without
    `--headless`) simply opens the project in the editor.

## Folder layout

```
slideshow-studio/
├── main.py            # run this (GUI; add --headless for CLI export)
├── app/               # application modules (41 modules, see MANIFEST.md)
├── tests/             # 385-test pytest suite (python scripts/run_tests.py)
├── pytest.ini         # pytest config (slow / online markers)
├── MANIFEST.md        # complete project inventory
├── examples/          # bundled sample decks — File ▸ Import example
│   ├── getting-started.txt      # text-script deck with ~ narration lines
│   ├── product-launch.md        # Markdown deck
│   ├── team-update.html         # HTML page → rich-text slides
│   ├── solar-power.pptx         # PowerPoint import incl. speaker notes
│   ├── quantum-computing.pdf    # PDF import: pages become plates
│   ├── demo-tour.slideshow      # full project: motion + overlays + voice
│   └── README.txt               # guide (itself a valid slide script)
└── output/            # bundled default for exports (File ▸ Input & output
│                       #   folders… can point exports anywhere else)

# tmp/                 # working folder for temporary render files — created
#                       #   on demand in the directory you start the app
#                       #   from, pruned at startup and removed on clean exit
```

`File ▸ Open examples folder` / `File ▸ Open output folder` / `File ▸
Open temp folder` reveal each folder in your file manager, and `File ▸
Input & output folders…` sets your own input, output and working folders
(with per-deck or date-stamped export layout). Drop your own
PPTX/PDF/HTML/TXT — or a whole folder of them — anywhere: import works
from any location, and the scratch it produces never leaves the managed
`tmp/` working folder.

### Keyboard shortcuts

| Keys | Action |
|------|--------|
| Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S | New · Open · Save · Save as |
| Ctrl+I / Ctrl+E | Import · Export |
| Ctrl+M | Quick convert to MP4 (files in → MP4s out, one dialog) |
| Ctrl+Shift+E | Batch export (queue many decks in one run) |
| Ctrl+Z / Ctrl+Y | Undo · Redo |
| Ctrl+F | Find & replace across the deck |
| Ctrl+Shift+V | Paste clipboard image as slide background |
| Ctrl+Shift+C | Copy slide image (2000-px render) to the clipboard |
| Ctrl+Shift+T | Script editor (whole deck as text) |
| Ctrl+Shift+A / Ctrl+D / Ctrl+Delete | Add · Duplicate · Delete slide |
| Ctrl+Up / Ctrl+Down | Move slide up / down |
| Ctrl+P / F5 | Play deck · Play deck |
| F6 | Present deck full-screen (S subtitles · N notes · A auto-advance · Esc exit) |
| Tools ▸ Rehearse timings… | Rehearse runner (←/→ / Space navigate · Esc finish & apply) |
| Ctrl+= / Ctrl+- / Ctrl+0 / Ctrl+1 | Canvas zoom in · out · fit · 100% |
| Ctrl+T | Toggle dark / light theme |
| PageUp / PageDown via list focus | Browse slides |

### Text import formats

- **TXT / MD**: lines starting with `#` start a new slide (title). A line
  with only `---` also starts a new slide. `~ text` (or `Narration:` /
  `Notes:`) sets that slide's narration; otherwise narration is title +
  body. A leading `\` escapes a structural character, so bodies can start
  with a literal `#` or `~`. Without any headings, paragraphs are grouped
  three per slide.
  This is the same format the **Script editor** exports, so decks round-trip
  through plain text files.
- **HTML**: every `h1/h2/h3` starts a new slide; paragraphs, lists, quotes and
  tables under it become the body — **with formatting intact** (bold, italic,
  colours, lists, links are carried into the editable rich-text body;
  scripts, styles and event handlers are stripped).
- **PDF**: every page becomes a slide — rendered page as background, extracted
  text as editable content and narration.
- **PPTX**: first text shape becomes the title, remaining text the body;
  speaker notes (if any) become the narration; the first picture is kept as
  the slide background. Bold / italic / underlined runs and indented bullets
  are preserved as rich-text HTML bodies.
- **PPT (legacy)**: requires LibreOffice (`soffice`) for automatic
  conversion; otherwise re-save as `.pptx` in PowerPoint.
- **Images** (`.png .jpg .jpeg .bmp .webp .gif`): one photo → one slide —
  the image becomes the slide background, the filename becomes the title
  (`sunset_beach-2.jpg` → “Sunset beach 2”), and narration stays empty so
  the deck voice speaks the title (or add your own). Drop a folder of
  photos on the window — or feed a photo folder to the CLI — and you have
  a narrated photo slideshow.

## Command-line export

```text
python main.py <project-or-source> --headless --format {mp4|mp3|wav|html|pdf|pptx}
                [--out FILE] [--notes] [--no-music] [--srt]
                [--resolution PRESET] [--voice ID] [--version]
```

The source can be a `.slideshow` project, any importable file
(PPTX/PDF/HTML/TXT/MD/image) or a folder (every importable file inside
becomes slides — a folder of photos becomes a photo slideshow). Rendering
runs on Qt's offscreen platform, so no display is needed; MP4/MP3/WAV
additionally need ffmpeg, TTS follows each deck's voices (override
deck-wide with `--voice`). Exit codes: `0` exported, `1` export failed,
`2` usage error.

## Testing

The project ships two automated layers — no GUI or display is required for
either (Qt runs off-screen):

```bash
pip install pytest pytest-timeout
python scripts/run_tests.py            # full pytest suite (385 tests)
python scripts/run_tests.py -m "not slow and not online"   # quick pass
```

The development workspace additionally carries a 79-check end-to-end smoke
suite (`scripts/smoke_test.py` next to the project) that exercises the whole
app in one pass, including six real ffmpeg exports, a batch run, a
quick-convert run and the headless CLI.

| Layer | Scope | Runtime |
|-------|-------|---------|
| pytest suite (`tests/`, 385 tests) | every module: models, sanitiser, importers (incl. images), storage/memory, renderer, all three TTS engines (offline + one online check), MP4/MP3/WAV pipelines, per-slide transitions + mixed transition graphs, rehearse timings, presenter notes, HTML export, PDF handout + PPTX export, headless CLI, **export presets + waveform** (peaks decode, async loader, seek, dialog integration), main window, panels, player, present mode, diagnostics, model manager, batch export, guided workflow + quick convert | ~10 min with all ffmpeg exports (`slow`); ~4 min without |
| smoke suite (`scripts/smoke_test.py`, 79 checks) | one long end-to-end pass over the whole app incl. 6 real exports, a batch run, a quick-convert run and CLI exports | ~4 min |

The pytest suite is hermetic: Qt runs on the off-screen platform, settings
and the media workspace are redirected to a sandbox, and TTS is replaced by
a generated tone, so nothing touches your real data. Tests marked `slow`
exercise the real ffmpeg pipelines; `online` marks the single test that
calls Microsoft's edge-tts service. See `MANIFEST.md` for the per-file
coverage map.

## Project file format

`.slideshow` is a plain ZIP:

```
project.json        # deck (slides, theme, voices, music settings)
media/<id>.png      # slide background images
media/music.mp3     # background music (optional)
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "ffmpeg NOT found" | Install ffmpeg for MP4/MP3/WAV; HTML, PDF and PPTX export work regardless |
| TTS fails / no audio | edge-tts needs internet access to Microsoft's speech service. Check firewall/proxy |
| Legacy `.ppt` import fails | Install LibreOffice or convert to `.pptx` first |
| Voice list empty / stale | Press *↻ Refresh edge voice list* in the Deck tab |
| Piper says "engine not installed" | `pip install piper-tts`, then pick a Piper voice again |
| Piper voice missing | It downloads automatically on first use; check your connection to huggingface.co — or pre-download it from **Tools ▸ Voice models & caches…** |
| Qwen TTS rejected the key | Check the API key and that the *International/China* endpoint matches where it was created |
| Fonts look different on export | Rendering uses system fonts; if a chosen font is missing, Qt silently substitutes |
| Formatting disappeared from an import | Bodies over the 1800-character limit fall back to clipped plain text by design |
| Anything else misbehaves | **Help ▸ Diagnostics…** → *Copy report* and include the text in your issue — it lists versions, tool paths and engine status |

## Tech notes

- The GUI is built from a **single design-token palette** (`app/styles.py`):
  two complete themes (dark / light) render from one QSS template, including
  generated checkbox/combo glyph assets, so the two themes can never drift
  apart. Icons are drawn at runtime with QPainter (`app/icons.py`) — a
  consistent 24-grid line style with no binary assets.
- The canvas (`app/canvas.py`) zooms from 8% to 400% with Ctrl+wheel anchored
  at the cursor, pans by dragging when zoomed, and re-renders through the
  same shared painter as the export, so even at 100% you are looking at the
  exact export pixels.
- TTS engines live in `app/tts.py` behind one dispatch: voice ids carry their
  engine as a prefix (`piper:en_US-lessac-medium`, `qwen:Cherry`, bare =
  edge), so decks can mix engines slide-by-slide and stay backward
  compatible. Piper synthesis caches loaded ONNX voices in-process; Qwen
  chunks narration to the 600-character API limit at sentence boundaries and
  merges the WAV parts losslessly.
- Narration text is cleaned by `app/tts_sanitize.py` before synthesis; the
  cleaned text plus the cleaning options are part of the narration cache key,
  so toggling an option re-synthesizes exactly what changed.
- All slide rendering (thumbnails, canvas, video frames) goes through one
  painter (`app/render.py`) in a virtual 1600×900 space, so the export is
  pixel-identical to the preview. Deck-level overlays (slide numbers,
  progress bar, watermark) are part of that painter via
  `render.overlay_info()`, so they ship in the MP4 exactly as previewed.
- Layout templates (`app/templates.py`) build pre-filled slides; the default
  **+** inserts “Title + content”, and the *Slide* menu offers all five.
- Present mode (`app/present.py`) re-uses the shared renderer, synthesizes
  each slide's narration on demand (cache-first) in a background thread and
  advances automatically at end of media. The presenter notes panel (key
  **N**) shows the speaker notes and a live per-slide clock; both it and
  the subtitle strip reposition on every resize.
- Rehearse timings (`app/rehearse.py`) is a present-mode sibling with a
  stopwatch: navigation banks the time spent on each slide (revisits add
  up), `Esc` emits the recorded seconds and the main window offers the
  apply step as a single undoable operation.
- Per-slide transitions are stored on the slide ("" = deck default, a
  transition name, or "None" = hard cut) and resolved by the export worker
  per join; a graph that mixes cuts with fades normalises both xfade
  operands to a common time base + frame rate (`settb` + `fps`) because
  ffmpeg rejects a raw `concat → xfade` chain otherwise. Duration
  overrides act as a *minimum*: a slide with narration lasts
  `max(audio + pad, duration)`, so rehearsed pacing survives TTS.
- Rich-text bodies are stored as a sanitised HTML subset (`app/htmlfmt.py`)
  that is exactly what Qt's rich-text engine renders; the same subset is
  re-used verbatim by the HTML slideshow export, so deck markup survives the
  round trip app → editor → browser.
- The body editor (`app/html_editor.py`) keeps three synced views
  (visual / HTML source / plain) and routes every write — typing, pasting,
  mode conversion — through the sanitiser, so stored decks only ever contain
  the whitelisted tags and style keys.
- TTS output is cached by content hash in the app-data workspace, so repeated
  previews and exports don't re-synthesize unchanged slides; transient
  network failures are retried automatically. Entries older than 60 days are
  pruned at startup, and the model manager can clear everything on demand.
- Smart memory (`app/memory.py`) keeps three crash-safe layers: a **session
  snapshot** (`.slideshow` written at exit + metadata), **per-deck state**
  (slide + tab keyed by project path) and **cache hygiene**; restoring is
  one function call with no dialogs on the startup path.
- The model manager (`app/models_dialog.py`) downloads Piper voices in a
  `QThread` with byte-level progress callbacks threaded through
  `tts.download_piper_voice`, so the UI stays responsive during ~60 MB
  downloads.
- The MP4 pipeline: render PNG → per-slide segment (`-loop 1` still image +
  AAC narration, padded; slides with motion render at 2× and are animated
  with `zoompan`) → stream-copy concat **or** an `xfade`/`acrossfade` chain
  when transitions are enabled → optional final pass burning subtitles
  (`subtitles` filter / libass) and/or mixing ducked music.
- Undo/redo uses full-deck snapshots (capped at 100) with typing bursts
  coalesced into a single step; autosave writes a scratch `.slideshow` every
  2 minutes without touching your project path.
- Text script mode (`app/script_mode.py`) is a pure-Python serializer/parser
  with escaping, so decks ⇄ text round-trips are lossless for every editable
  field; script Apply only rewrites slides whose text actually changed.
  Find & replace edits HTML bodies inside text nodes only (BeautifulSoup),
  so markup, attributes and URLs can never be corrupted by a replacement.
- ffmpeg stderr is captured and shown in export error dialogs, so filter
  problems are diagnosable without a console.
- Batch export (`app/batch_dialog.py`) drives the regular export pipeline
  sequentially from the GUI thread: each job loads its deck (ZIP project or
  importer), computes a collision-safe output name up front, and runs its
  own `ExportWorker` thread; the next job starts from the worker's
  `finished` signal, so failures never break the queue. HTML jobs skip
  ffmpeg entirely via the inline exporter, and all `batch/*` options
  persist in QSettings like the single-export dialog.
- Document exports (`app/document_export.py`) render every slide through
  the shared painter at 2000 px wide into the managed working folder, then
  embed the pages with PyMuPDF (PDF, 960×540 pt 16:9 pages, notes pages
  with auto-shrinking text) or python-pptx (13.33×7.5 in slides, narration
  into the notes pane). Both take `check` callables, so cancelling a
  document export is as instant and clean as cancelling a video.
- The headless CLI (`app/cli.py`) shares the exact GUI pipeline:
  `ExportWorker.run()` is invoked synchronously on the offscreen Qt
  platform with progress wired to stdout, so a CLI export and a GUI export
  of the same deck produce byte-comparable output. Importers, the folder
  scanner and the drop handler share one extension list
  (`paths.IMPORTABLE_EXTS`), so anything the GUI can import the CLI can
  convert.
- Export presets (`app/presets.py`) are plain data — a `Preset` object
  serialises to one JSON dict, and the whole list lives under a single
  QSettings key. Bad values degrade to defaults in `Preset.from_dict()`
  (unknown format → MP4, unparseable numbers → defaults, booleans accept
  "true"/1/yes), so a hand-edited INI can never crash the dialog. The
  factory set is seeded once into storage on first use; after that the
  factory presets are ordinary editable presets like any other.
- The waveform strip (`app/waveform.py`) decodes audio to raw mono PCM on
  ffmpeg's stdout (no temp files) and buckets it into 900 peak values in
  0..1; the decode runs on a `QThread` whose run loop only reports the
  newest requested path, so flipping quickly through slides never floods
  the UI with stale waveforms. The widget normalises peaks to the tallest
  bar (quiet narrations stay readable), highlights the played part with
  the theme accent colour and converts clicks/drags into `seekRequested`
  fractions the player maps onto `QMediaPlayer.setPosition()`. When idle
  the bar only ever reads the *cached* narration file, so it is strictly
  offline.
