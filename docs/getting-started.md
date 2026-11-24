# Getting started

## Install

Download the build for your platform from the [latest release](https://github.com/rwensel/markseal/releases/latest):

- **Windows x64:** `Markseal-Setup.exe`. The 2.0.6 build is an unsigned preview; Windows code signing is provided by the SignPath Foundation, and signed builds will follow approval.
- **Linux x64:** `Markseal-linux-x64.tar.gz`. Extract it and run `Markseal/Markseal`. This build is untested.
- **macOS arm64:** `Markseal-macos-arm64.zip`. It contains `MarkSeal.app`; the build is untested, unsigned, and not notarized, so Gatekeeper requires an override.

The release also publishes `SHA256SUMS.txt`. Updates are opt-in and off by default.

## Run from source

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.\launch.bat
```

On Linux or macOS, use `.venv/bin/python` for the install and run `.venv/bin/markseal`. The app makes no network calls by default; only the opt-in update check contacts the update feed, and image data never leaves the machine.

## Open a screenshot

Use **Open image**, **Paste** (Ctrl+V), or drag an image anywhere onto the window. Dragging a folder opens folder mode. A copied image or a copied image file works with Paste.

## Scan and review

1. Click **Scan image**. The banner above the screenshot shows the OCR stage and progress while the rest of the window stays responsive.
2. Suggestions start selected. Click a box to exclude it, click again to include it, or press Delete / click the X to remove it.
3. Drag on the image to add a manual box. If you need only a small area, use **Scan region**.
4. Turn on **Rule tags** in the viewer caption to see why a box was suggested. The tags are review-only and are never exported.
5. Press **Confirm** to apply the selected boxes to the preview. **Revise** brings the outlines back if you need to change the selection.

The bottom signal board always shows selected, excluded, and total counts, plus whether the preview is applied or pending.

If a value keeps slipping through, teach it once: select it with **Settings → Blocked patterns → Learn from scan area** and save the generated expression. See [Blocked patterns](settings.md#blocked-patterns).

## Save and share

After confirming:

- **Save** writes a PNG and, when enabled in Settings, a JSON coordinate log. The original image is never overwritten.
- **Copy image** puts the confirmed preview on the clipboard.
- **Save reviewed** in folder mode exports every reviewed image that is still awaiting export.

Only selected boxes are applied and included in the log. Review the log before sharing it: it contains the source filename and coordinates.

## Keyboard

| Shortcut | Action |
|---|---|
| Ctrl+O / Ctrl+Shift+O | Open an image / folder |
| Ctrl+V | Paste an image |
| Ctrl+F | Scan the current image |
| Ctrl+Enter | Confirm the current selection |
| Ctrl+S | Save a confirmed image |
| Ctrl+C | Copy the confirmed image |
| Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y | Undo / redo the last added box |
| Ctrl+A / Ctrl+Shift+A | Select all / clear the selection |
| Ctrl+= / Ctrl+- / Ctrl+0 | Zoom in / out / fit |
| Shift+arrows | Pan while zoomed |
| Space | Include or exclude the focused box |
| Delete | Remove the focused box |
| Esc | Cancel an area or anchor drag |
| Alt+M | Open the More menu on a narrow window |

Tab reaches the toolbar, then the viewer. With the viewer focused, arrow keys move between boxes.

## If something fails

A scan, copy, or save failure appears in a banner above the signal board with **Retry**, **Logs**, and **Dismiss**. Native dialogs remain for file pickers and confirmations.

Next: [Reviewing and redacting](reviewing.md) · [Settings](settings.md)
