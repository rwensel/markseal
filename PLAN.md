# Offline Screenshot Redactor — Modernization Plan & Handoff

## Status

Implemented as a PySide6 6.9 + Qt Quick (QML) app. The shell, viewer, folder sidebar, settings window, and signal board live in `redactor/qml/`; domain logic is in `redactor/core.py`, shared review state in `redactor/review.py`, and the QML bridge in `redactor/controller.py`. `offline_redactor.py` remains the launcher. Behavior is unchanged; the Tkinter interface is retired.

## One-line summary

Rebuild the Offline Screenshot Redactor as a cross-platform PySide6/Qt Quick (QML) desktop app, keeping behavior identical, wearing the "Split-flap Concourse, 2026" visual world.

## Confirmed decisions

- **Visual world:** Split-flap Concourse, modernized with 2026 depth (not flat).
- **Framework:** PySide6 + Qt Quick (QML) — binding.
- **Scope:** full app end-to-end (single-image, folder, settings, export).
- **Behavior:** unchanged — no new features, no new workflow steps.
- **Hard commitments:** fully offline; pixel-accurate redaction; never overwrite originals; must not read as cloud or consumer.

## Job and audience

Engineers who redact their own screenshots (configs, logs, dashboards) before pasting them into tickets, docs, or chat. Single-image and folder review are used equally. They know which secrets are in the image and need a fast, legible review loop.

## Outcome and proof

A PySide6/Qt Quick app whose review loop is instantly legible: the screenshot is the subject, the three redaction states are unambiguous, and scan → review → confirm → export is as fast as today. Success = an engineer scrubs and exports a screenshot without thinking about the interface.

## Selected direction — Split-flap Concourse, 2026

- **World:** mechanical departure-board DNA — charcoal/steel shell, condensed uppercase grotesque, amber + red signal colors, segmented flip tiles.
- **2026 treatment:** layered depth — soft shadows, frosted titlebar, raised buttons with a soft accent glow, inset screenshot card, dimensional flip tiles with a hinge seam.
- **Shell (standard, native):** top toolbar (Open / Scan / Undo / Confirm / Save), left sidebar (folder list, batch actions, progress), center viewer, bottom status line, settings as tabs.
- **Signature move:** the flip tile — amber on the active state, with a subtle flip transition on state change.

## Scope and boundaries

- Full app: single-image mode, folder mode, settings, export.
- No new features or workflow steps; no identifiers table or other invented surface.
- Fully offline; pixel-accurate (pixels outside selected boxes unchanged, camera metadata omitted); never overwrite originals.
- Must read as a local offline tool, never cloud-based or consumer-grade.

## States and ranges (carry over from incumbent)

No image; image open; scan running; partial scan; boxes selected / excluded / drawing; confirmed; reviewed / saved; export error; empty folder; cancel scan. Content ranges unchanged (one image to a whole folder).

## Interaction and layout

- Viewer dominates; sidebar and toolbar are secondary.
- Selection stays click-to-toggle, drag-to-add, X-to-remove (unchanged behavior).
- The flip-tile signature and the three-state box outlines are the only new visual grammar.
- Native desktop controls; keyboard reachability expected; interaction model unchanged.

## Constraints and open decisions

- PySide6 + Qt Quick (QML) binding; cross-platform (Windows/macOS/Linux); offline only.
- Resolved at build: Bahnschrift Condensed is the display face on Windows (Avenir Next Condensed and Roboto Condensed are the macOS/Linux fallbacks) with Inter/Segoe UI for body; the flip transition is 110ms out and 150ms in; the final tokens and component inventory are in DESIGN.md.

## Direction contract

**THESIS.** The review loop is a departure board: every state is a signal read at a glance, and the interface recedes into layered, mechanical depth. It refuses the flat neon-terminal costume and the generic SaaS-admin shell.

**OWN-WORLD.** Charcoal/steel layered shell; amber (#FFB000) active/selected, red (#B00020) cancelled/excluded, white lettering; condensed uppercase grotesque labels; dimensional flip tiles with a hinge seam. Recognizable with all content removed.

**STORY.** An engineer opens a screenshot, watches the scanner flip identifiers into amber boxes, clicks the false ones off (red), confirms, and exports a safe copy — the whole loop legible as board states.

**FIRST VIEWPORT.** Top frosted toolbar (primary Save on the right, amber); left folder list; center inset screenshot card with three-state boxes floating over it; bottom status line. The amber selected box and the flip tile are the first things the eye lands on.

**FORM.** Catalog world `signals-instruments-split-flap-concourse`, modernized. Seed reference: seed:297d2c7e94019ae4.

**FINISH.** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Files and references

- `PRODUCT.md` — durable product truth (users, purpose, constraints, commitments). Read first.
- `DESIGN.md` — the implemented visual system: final tokens, components, and rules.
- `DESIGN.incumbent.md` — the retired Tkinter system (design history only).
- `world-picker.html` — temporary visual comparison (14 candidate mockups; Split-flap Concourse is the chosen one).
- `offline_redactor.py` — launcher; re-exports the public core names used by `audit_exports.py`.
- `redactor/core.py`, `redactor/review.py`, `redactor/controller.py`, `redactor/app.py`, `redactor/qml/` — the PySide6/Qt Quick implementation; behavior to preserve.
- `rapidocr_backend.py`, `ocr_preprocess.py`, `visual_anchor.py`, `performance_log.py`, `audit_exports.py` — support modules; behavior to preserve.
- `README.md` — full user-facing behavior.
- `test_offline_redactor.py` — regression tests.
- `.impeccable/design.json` — local design sidecar; not shipped.

## What the implementation must preserve (from PRODUCT.md)

- Fully offline; OCR and images stay local.
- Pixel-accurate redaction; pixels outside selected boxes unchanged; camera metadata omitted; source-image pixel coordinates with exclusive right and bottom edges.
- Never overwrite originals; export PNG copies plus an optional JSON coordinate log.
- Detection: Tesseract + optional RapidOCR; pattern categories (emails, URLs, IPs, tickets, paths, hashes, secrets, infrastructure); presets Focused/Balanced/Broad plus a custom regex.
- Redaction methods: pixelation (coarse mosaic) and solid black.

## Implementation notes

- `offline_redactor.py` is a thin launcher and keeps re-exporting the public core names used by `audit_exports.py`.
- Single-image scanning runs on the same background worker pool as folder jobs; a viewer banner reports the current OCR stage (recognizing text, struck-through recovery, enhancement, color passes) and coarse progress, so the window stays responsive.
- Folder scans show queued/running rows with activity bars and a determinate job bar; parallel jobs leave the viewer on the current image, while a single job follows photos as before.
- File and message dialogs are native (`QFileDialog`, `QMessageBox`) so overwrite, discard, and partial-scan prompts stay behaviorally identical.
- Follow-up capabilities: configurable parallel image jobs (default one, bounded by processor count, Tesseract subprocesses and a pooled per-worker RapidOCR engine), per-image queued/running progress in the folder list, clipboard image paste, image/folder drag-and-drop, copying the confirmed redacted preview to the clipboard, a persisted quick Pixelate/Solid method toggle in the viewer caption, and containment pruning for nested selected suggestions. Sharing stays local: there are no network uploads or third-party sharing integrations.
- The interface ships no raster assets: the brand mark, flip tiles, shadows, and icons are drawn in QML, so there are no image provenance records to carry.
- Verified with `python -m unittest -v`, a real-window walkthrough of image review and folder export, an offscreen QML load with no warnings, a local Tesseract scan, and an `audit_exports.py` pass over an exported PNG.
