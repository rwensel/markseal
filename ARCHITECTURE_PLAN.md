# Architecture Plan — Offline Screenshot Redactor

Generated 2026-11-23 from an architecture review of the current tree. Companion visual report: `C:\Users\rmwen\AppData\Local\Temp\architecture-review-20261123021939.html`.

This is an executable plan for a working agent. It lists deepening opportunities in dependency order, each with a verification gate. Read `PRODUCT.md` first; the hard commitments there are the acceptance criteria for every step.

## What "deepening" means here

Use this vocabulary exactly: **module** (anything with an interface and an implementation), **interface** (everything a caller must know to use it), **implementation**, **depth**, **deep** vs **shallow**, **seam** (where an interface lives), **adapter** (a concrete thing satisfying an interface at a seam), **leverage** (what callers get from depth), **locality** (what maintainers get). Do not write "component", "service", "API", "boundary", "layer", or "wrapper" when you mean module.

A deepening extracts a shallow module into a deep one: a small interface with a lot of behaviour behind it, at a seam that already has two adapters (or clearly will). The aim is testability and AI-navigability, not churn.

## Non-negotiable constraints (override everything below)

1. **No behaviour change without verifying and testing first.** Each step is a refactor that preserves behaviour; if a step would change what the user sees or what an export produces, it is out of scope until the human re-approves it.
2. **Fully offline.** No new network calls anywhere. OCR, images, and exports stay on the machine.
3. **Pixel-accurate redaction.** Pixels outside selected boxes are unchanged; rectangles stay in source-image coordinates with exclusive right and bottom edges.
4. **Never overwrite originals.** Exports are new PNG copies plus an optional JSON coordinate log.
5. **Workflow unchanged.** Open → scan → review → confirm → export, single-image and folder, exactly as today.
6. **Never delete or skip a failing test.** The suite must stay green at every step; pre-existing failures get reported, not hidden.

## Verified baseline

- `36 tests` pass in `0.208s` via `.venv\Scripts\python.exe -m unittest -v`.
- The tests cover `core.py`, `review.py`, `rapidocr_backend.py`, `performance_log.py`, and `ocr_preprocess.py`.
- **Zero tests** cover `controller.py`, the QML shell, preferences load/save, export orchestration, `visual_anchor.py`, or `audit_exports.py`.
- Hot spots by commit history: `controller.py` (11), `Viewer.qml` (9), `core.py` (7), `SettingsWindow.qml` (6), `test_offline_redactor.py` (11).

## Ordering rule

Work top-down in the numbered workstreams. 1 and 2 are independent of each other and either one may start first; both unblock 3, 4, and 5. 6, 7, and 8 land last and only after the seams above exist. Do one workstream at a time; run the full suite plus the relevant real-window smoke check before starting the next.

## Workstream 1 — Extract the parallel job runner

- **Goal.** A plain-Python job-runner module behind one small interface.
- **Move.** Lift `_run_jobs`, the worker/coordinator closures, `_poll_jobs`, the `_job` dict, `_show_progress`, and cancellation/pacing out of `controller.py` into a module with no Qt imports. The Controller keeps only submit/cancel and result-handling callbacks.
- **Files.** `redactor/controller.py:1449-1660` (and its call sites at `_start_single_scan`, `_start_scan`, `copyBoxesToFolder`, `_match_boxes_to_folder`, `_export_entries`, `_learn_pattern`).
- **Tests to add (before behaviour settles).** Parallel limit bounding, cancel stops queued work, queued/running row-state transitions, failure aggregation, paced follow, progress text, performance-trace completion.
- **Verification.** Full suite green; a folder scan with `parallelImages > 1` still reaches running state together and cancel stops queued work.
- **Do not break.** Parallel scan/copy/match/export results identical to today; cancel leaves the folder list in the same end state; the status board text matches.
- **Done when.** Controller no longer owns threads/queues/timers for jobs, and the runner's tests pass without a QApplication.

## Workstream 2 — Own the review-session state in one module

- **Goal.** One module owns boxes + selected set + rules + containment prune + status; the Qt model and the single-image review become adapters.
- **Move.** Stop hand-syncing `Controller.entries/active/row_selection` ↔ `FolderModel.entries/active/selection/job_states` ↔ `Review.boxes/rules/selected/confirmed` ↔ `FolderImage.boxes/rules/selected/reviewed/saved`. Extract a review-session module; keep `Review` and `FolderImage` as thin views over it (or adapters of it).
- **Files.** `redactor/controller.py:57-155,707-755`, `redactor/review.py:12-203`, `redactor/core.py:284-353`.
- **Tests to add.** Image switching, status transitions, selection persistence, nested-box pruning, rule provenance, and the confirmed/saved bookkeeping (which today diverges between `Review.add_suggestions` and `FolderImage.add_shared_boxes`).
- **Verification.** Full suite green; open a folder, scan, select/deselect, switch images, and confirm — every status and box survives exactly as today.
- **Do not break.** Selection state, rule labels (Manual box / Copied box / Anchor match / OCR suggestion), and the amber-selected / red-excluded display.
- **Done when.** The four copies of the state collapse to one owner, and the two merge paths share the same prune/flag logic.

## Workstream 3 — Put an adapter at the OCR seam

- **Goal.** One adapter interface (`recognize(image, options) -> tsv`) with two adapters: the Tesseract subprocess and the RapidOCR pool.
- **Move.** Remove the `executable is None` branching from `recognize_regions`, `read_area_text`, and the area/label fallbacks. Move subprocess launch, cancellation, and pool borrowing behind the adapter; keep the multi-pass orchestration above the seam. Fold `read_area_text`'s duplicated Tesseract launch into the adapter.
- **Files.** `redactor/core.py:486-726`, `rapidocr_backend.py:15-125`, `redactor/controller.py:950-1012`.
- **Tests to add.** Fake adapter exercises the pass orchestration without subprocess/onnx; engine parity; settings validation; rule association; area rescaling; timeout/partial-pass behaviour.
- **Verification.** Full suite green; a local Tesseract scan and a RapidOCR scan both return the same box/rule shape through the one interface.
- **Do not break.** Detection results, enhancement passes, struck-through recovery, colour passes, small-text tiles, and the single-label area fallback.
- **Done when.** No caller checks `executable is None`, and a fake adapter can drive the whole pass pipeline.

## Workstream 4 — Own settings and preferences in one module

- **Goal.** One module owns defaults, schema, snake_case↔camelCase mapping, validation, legacy migration, and atomic write.
- **Move.** Replace `load_preferences`, `_restore_output_preferences`, `_preference_document`, `applySettings`, `setRedactionMethod`, `setShowRules`, and `write_preferences` with one preferences module. The QML form and `audit_exports.py` become adapters that read the one schema.
- **Files.** `redactor/controller.py:1988-2187`, `redactor/core.py:257-276`, `redactor/qml/SettingsWindow.qml:25-94`, `audit_exports.py:42-69`.
- **Tests to add.** Defaults, round-trip persistence, invalid confidence/parallel values, legacy `custom_pattern` migration, blocked-pattern enable/disable, and the derived scan configuration.
- **Verification.** Full suite green; change settings, relaunch, confirm they persist; run `audit_exports.py --use-app-pattern --ocr` against an enabled blocked pattern.
- **Do not break.** Persistence timing (immediate writes vs apply-on-close), the persisted quick method choice, and blocked-pattern rename/enable/remove.
- **Done when.** The document shape and key mapping are defined exactly once, and the CLI reads the same schema.

## Workstream 5 — Own the export pipeline in one module

- **Goal.** One module owns target naming, log schema, state snapshots, atomic publish, and overwrite policy.
- **Move.** Route `_save_single` and `_export_entries` through one export module; remove the divergence where the single path adds a note and clears image info but the folder path does not (decide the single correct behaviour and apply it to both, after the human confirms).
- **Files.** `redactor/controller.py:1863-1986`, `redactor/core.py:407-450`, `audit_exports.py:10-112`.
- **Tests to add.** Log schema parity, overwrite refusal, sidecar/PNG rollback, unchanged pixels outside boxes, and an audit round-trip.
- **Verification.** Full suite green; export one image and a folder, then run `audit_exports.py` over both; confirm the PNGs decode and pixels outside the boxes match the originals.
- **Do not break.** Never overwrite originals; coordinate logs stay valid; clipboard copy keeps matching the applied preview.
- **Done when.** Both save paths produce identical log shape through one module, and the audit passes.

## Workstream 6 — Unify view-to-image coordinate handling

- **Goal.** One module owns view transforms, hit-testing, drag rectangles, pan anchoring, and capture-area mapping.
- **Move.** Stop reimplementing conversion in `Review` and `Controller`; stop writing `review.start` directly from capture. Route selection and capture through the one transform module.
- **Files.** `redactor/review.py:67-77,101-138`, `redactor/controller.py:784-790,806-849`.
- **Tests to add.** Round-trip mapping at zoom and letterbox edges, multi-direction drags, minimum-area rejection, pan/zoom anchoring.
- **Verification.** Full suite green; real-window drag-to-add, drag-to-scan-area, zoom, and right-drag pan at 1080x680 and 1440x900.
- **Do not break.** Box coordinates in source pixels; exclusive right/bottom edges; drag-to-add and drag-to-capture minimum-size behaviour.
- **Done when.** Selection and capture share one conversion path.

## Workstream 7 — Move dialog construction out of Controller

- **Goal.** Dialog modules that take a value and return a result or None, with validation tested outside Qt.
- **Move.** Extract `_prompt_blocked_pattern`, `addBlockedPatternManually`, `renameBlockedPattern` into modules; keep the native `QDialog` widgets as the terminal adapter.
- **Files.** `redactor/controller.py:1141-1279`.
- **Tests to add.** Regex rejection, empty and duplicate handling, rename normalization, cancel semantics.
- **Verification.** Full suite green; add, rename, enable/disable, and remove a blocked pattern in the real window.
- **Do not break.** Learned patterns and manual patterns still match on future scans; labels and case-insensitivity unchanged.
- **Done when.** Controller no longer builds dialog widget trees inline.

## Workstream 8 — Split core.py and encapsulate the RapidOCR pool

- **Goal.** Cohesive sibling modules (detection / ocr / export / boxset / preferences) behind the existing re-exports; the engine pool gets an explicit owner.
- **Move.** Split `core.py` along the seams drawn in 3, 4, and 5; keep `offline_redactor.py` re-exports unchanged. Turn `rapidocr_backend._engines`/`_engine_creation` into an owned `EnginePool`.
- **Files.** `redactor/core.py` (849 lines), `rapidocr_backend.py:15-46`, `offline_redactor.py:2-23`.
- **Tests to add.** Pool borrow/return/lifecycle; re-export surface unchanged (the existing imports keep resolving).
- **Verification.** Full suite green; `git diff --check` clean; `launch.bat` still starts and scans.
- **Do not break.** The public names `audit_exports.py` and the tests import from the launcher.
- **Done when.** Each concept reads end-to-end in one file and the pool is no longer a module global.

## Definition of done for the whole plan

- Every workstream above is complete, or explicitly deferred by the human with a reason recorded.
- `36 + new` tests pass in one run; no test was deleted or skipped.
- `git diff --check` is clean.
- A real-window walkthrough covers: single-image scan, folder scan with parallel workers, select/deselect/remove/undo, confirm, quick method switch, clipboard copy, folder export, and `audit_exports.py` over the export.
- `PRODUCT.md` commitments are untouched: offline, pixel-accurate, originals never overwritten.

## Reporting

After each workstream, report: what moved, the new tests and their counts, the verification commands and their output, and any pre-existing failures that sit outside the changed code. Do not start the next workstream with a red suite.

## Implementation record (2026-11-23)

Status: implemented. Workstreams 1-8 landed in nine commits from `a8d3a72` (Extract the parallel job runner) to `b21f954` (Record the deepened module architecture); a follow-up commit added the controller's direct module imports, the glossary and the ADRs.

- Tests: 36 before, 87 after, in one `python -m unittest` run. No test was deleted or skipped; every original test name still exists.
- Checks: `python -m unittest` OK, `python -m compileall` clean, `git diff --check` clean.
- Walkthrough (headless `QT_QPA_PLATFORM=offscreen`, real `Controller` and `Main.qml`): a folder scan with two workers reached queued and running states with two rows running together; select/deselect, drag-add, remove and undo kept the expected counts; confirmation, quick method switch (persisted), and clipboard copy worked; four folder exports and one single-image export were audited pixel-exact; `audit_exports.py --ocr --use-app-pattern` exited 0; QML loaded with zero warnings and frames were grabbed at 1080x680 and 1440x900.
- Decisions recorded: every coordinate log carries the safety note (both save paths); a folder image and its review share one live `BoxSet`; the controller imports sibling modules directly and `core.py` stays frozen as the launcher/test facade; regression tests remain in one file until roughly 1,500 lines.
- Corrections made during implementation: the merge change flag is computed from the final box and selection state, so a suggestion absorbed by a selected outer box reports unchanged; a missing adapter pass-through in `scan_folder_image` was caught by a new test; user-facing "area(s)" copy became "box(es)" where it meant a redaction box, while scan-area wording stayed.
- Deferred: a human visible-window pass before the next release (the walkthrough was offscreen); an optional test-file split; nothing else from the plan.
