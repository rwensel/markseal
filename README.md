<p align="center">
  <img src="docs/images/banner.png" alt="MarkSeal — offline screenshot redaction" width="760">
</p>

<p align="center">
  <b>Find and redact sensitive text in screenshots without uploading them.</b><br>
  Local OCR suggests likely secrets. You review the boxes and export a pixel-accurate PNG.
</p>

<p align="center">
  <a href="https://github.com/rwensel/markseal/actions/workflows/tests.yml"><img src="https://github.com/rwensel/markseal/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="https://github.com/rwensel/markseal/releases/latest"><img src="https://img.shields.io/github/v/release/rwensel/markseal" alt="latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/rwensel/markseal" alt="MIT license"></a>
</p>

## Download

| Platform | Build | Notes |
|---|---|---|
| Windows x64 | [Markseal-Setup.exe](https://github.com/rwensel/markseal/releases/latest/download/Markseal-Setup.exe) | Unsigned 2.0.7 preview; no code-signing certificate is currently available, so Windows may show an unknown-publisher warning. |
| Linux x64 | [Markseal-linux-x64.tar.gz](https://github.com/rwensel/markseal/releases/latest/download/Markseal-linux-x64.tar.gz) | Untested PyInstaller build; extract and run `Markseal/Markseal`. |
| macOS arm64 | [Markseal-macos-arm64.zip](https://github.com/rwensel/markseal/releases/latest/download/Markseal-macos-arm64.zip) | Untested, unsigned, not notarized; Gatekeeper needs an override. |

All builds and `SHA256SUMS.txt` are on the [releases page](https://github.com/rwensel/markseal/releases). Or [build from source](docs/building.md).

## See it work

![Reviewing a deployment log and applying redaction](docs/images/review.gif)

## PDFs, page by page

Open a PDF with **Open image** or drop it on the window. MarkSeal renders the page locally at 200 DPI, then the usual review, OCR, and redaction tools work on the rendered page. Use **PREV** and **NEXT**, or PageUp and PageDown, to move between pages; each page keeps its own boxes and confirmation. **Save** writes the current page as a PNG using a page-specific name, and the coordinate log records `source_page`.

The page is capped at 40 million pixels to keep a very large PDF from exhausting memory. PDFs are opened one file at a time; folder mode remains image-only. Password-protected PDFs, PDF text extraction, and PDF output are not supported yet, and **VERIFY** is unavailable for PDF pages because the export has no image original to compare against.

![A PDF page with the page navigation bar](docs/images/pdf-page.png)

## Why MarkSeal

- **Your screenshots and PDFs never leave the machine.** OCR, pattern matching, PDF rendering, redaction, and export run locally. The only optional network use is the update check, which is off by default.
- **You decide what gets covered.** Suggestions start selected; click to exclude, drag to add, and turn on rule tags to see why each box appeared.
- **The output is verifiable.** Export a PNG plus an optional JSON coordinate log, then check it with the bundled audit tool.

## Features

- Local RapidOCR with presets for sharing, work logs, financial details, faces and codes, or everything.
- Reviewable boxes with include/exclude, rule tags, undo/redo, and keyboard navigation.
- Pixelate, solid black, blur, or erase; pixels outside the selected boxes are preserved.
- Full-image scan, region scan, screen capture, clipboard paste, and drag-and-drop.
- Open PDFs page by page: render locally at 200 DPI, navigate pages, and save the current redacted page as PNG.
- Folder scanning with **Scan all**, **Scan selected**, **Confirm all**, **Save reviewed**, queued/running rows, and cancel.
- Bounded parallel jobs: set **1–16 parallel image jobs**; each active worker owns a local OCR engine.
- Box reuse and anchor matching for screenshots with matching or shifted framing.
- **Learn your own identifiers.** Draw a box around a value and save a reusable blocked pattern for the IDs specific to your team.
- Six themes, including Split-flap Concourse and Midnight Transit Diagram.
- Optional update check and beta channel; nothing installs without a click.

## How it works

1. **Open** an image, paste it, or capture a region.
2. **Scan** and review the suggested boxes; include, exclude, or draw your own.
3. **Confirm**, then save or copy the redacted PNG.

## Teach it your own patterns

The built-in detectors cover common personal and engineering identifiers. MarkSeal can also learn your team's own identifiers from a scan area: an internal customer ID, a device serial, or an account code.

Open an image, go to **Settings → Blocked patterns**, and click **Learn from scan area**. Drag a tight box around one example. MarkSeal reads that area locally, shows the recognized text and a generated regular expression, and lets you choose fixed-text matching or a detected value class such as IPv4/IPv6, CIDR, UUID, email, URL, MAC, ISO date, integer, or long hex token. Review it, name it, and save; every future scan includes it. Nothing leaves the machine.

![Learning a blocked pattern from a selected area](docs/images/settings-blocked.png)

## Methods and themes

### Four ways to redact

Pixelate, solid black, blur, or erase. Switch on the live preview to see exactly what will be saved.

![Switching between Pixelate, Solid black, Blur, and Erase](docs/images/methods.gif)

### Six themes

From the default Split-flap Concourse to Railway Timetable Rack, Jet-age Ticket Wallet, Centre-rail Reference, Crouwel Grid Specimen, and Midnight Transit Diagram.

![Switching between MarkSeal themes](docs/images/themes.gif)

## Batch without the busywork

Open a folder, scan all or only the rows you select, confirm in bulk, and save every reviewed image. Rows show queued, running, saved, and partial states; **Cancel scan** stops queued work while keeping completed results.

Concurrency is yours to tune: **Settings → OCR → Parallel image jobs** accepts 1–16 images at once. Each active worker owns a local OCR engine, so higher values finish faster on a large machine but use more CPU and memory. The app uses a bounded worker pool, and the scan banner reports how many workers are active.

![Folder mode with queued and running rows](docs/images/batch.png)

## Screenshots

| Review suggestions | Applied preview |
|---|---|
| ![Suggested boxes on a deployment log](docs/images/review.png) | ![The same log after pixelating the selected boxes](docs/images/applied.png) |

## Documentation

- [Getting started](docs/getting-started.md) — install, open, scan, review, save.
- [Reviewing and redacting](docs/reviewing.md) — boxes, rules, zoom, capture, folders, reuse.
- [Settings](docs/settings.md) — OCR, presets, blocked patterns, output, themes, updates.
- [Building from source](docs/building.md) — local builds, tests, notices.
- [Privacy](PRIVACY.md) — what stays on the machine.
- [Third-party notices](THIRD_PARTY_NOTICES.txt) — bundled components and licenses.

## Privacy and security

MarkSeal has no telemetry, accounts, or upload integrations. The app reads the images you open, the files you export, and its local settings. The optional update check exchanges release metadata and the installer, never image data. See [Privacy](PRIVACY.md) for the full statement.

## Contributing

Bug reports and feature ideas are welcome in [Issues](https://github.com/rwensel/markseal/issues). For code changes, keep the app offline, run the test suite, and see [Building from source](docs/building.md).

If MarkSeal saves you a cleanup pass, a star helps other people find it.

## License

MIT. See [LICENSE](LICENSE). Third-party components and their licenses are listed in [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) and under **Settings → Updates → Third-party licenses**.
