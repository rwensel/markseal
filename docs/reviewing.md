# Reviewing and redacting

## Boxes and selection

Suggestions start selected. The theme accent marks selected boxes and the primary action; the stop color marks excluded boxes (amber and red in the default Split-flap theme).

- Click a box to exclude it; click again to include it.
- Click the X at a box's upper-right corner, or press Delete with the viewer focused, to remove it.
- Drag to draw a manual box. It starts selected.
- Boxes fully inside an already selected area are dropped, so the outer selected boundary wins and nested duplicates do not stack. This applies to scan suggestions and to copied or matched boxes.
- If boxes overlap, clicking affects the topmost one.

![A selected box and an excluded box](images/review-excluded.png)

## Rule tags

Turn on **Rule tags** in the viewer caption to inspect attribution. Hover a box, or select exactly one, to see its rule tag. The tag names the detection category, blocked pattern, or provenance such as Manual box, Copied box, or Anchor match. The choice is remembered across restarts. Tags are review-only and are never included in the exported image or coordinate log.

## Zoom and pan

Use the mouse wheel over the image to zoom around the pointer. Right-click and drag to pan while zoomed in. Zoom does not change the saved image. The caption shows the current percentage; the tooltip lists the keyboard shortcuts.

## Scan a region

For small text missed by a full-image scan, zoom in, click **Scan region**, and drag tightly around the text. A banner names the active mode and offers **Cancel**; Esc also cancels. The app scans an enlarged copy of the selected original pixels and adds boxes to the original image. A narrow region is treated as a single text line. An area scan does not mark the full image as scanned.

## Capture a region

Click **CAPTURE** in the toolbar to dim the screen and drag a rectangle. On release the selected region is loaded as an in-memory image you can scan, review, and save like any other screenshot. Nothing is written to disk until you save. Press Esc to cancel.

## Redaction method

Use the **Method** toggle in the viewer caption, or **Settings → Redaction**, to switch between Pixelate, Black, Blur, and Erase. The choice is saved immediately and applies to the confirmed preview, the copied image, and the saved PNG. The method applies across the folder and is remembered across restarts. Changing it returns reviewed folder images to review before export.

Pixels outside selected rectangles are preserved. Camera metadata is omitted from saved copies.

![Switching between the four redaction methods](images/methods.gif)

## Pixelation warning

Pixelation changes only the marked rectangles, using coarse blocks, but it can leave text or visual features recognizable or recoverable. Gaussian **Blur** is similar: blurred text can sometimes be recovered. For highly sensitive material use **Solid black**, and independently review before sharing. **Erase** fills the area with nearby pixels; check the result. This tool cannot guarantee removal of all sensitive information.

## Work through a folder

1. Use **Open folder** to list supported images directly inside a folder. Select a row to switch images and keep its boxes and selections for the session.
2. Use **Scan all** for the remaining images, or **Scan image** for the current one. Ctrl-click selects separate rows and Shift-click selects a range; **Scan selected** scans just those rows and keeps existing boxes. Progress, queued/running labels, and counts stay visible while jobs run.
3. Inspect each image, adjust its boxes, and click **Confirm**. **Confirm all** confirms every eligible image; it skips images with no selected boxes or errors. Partial scans require acknowledging the warning.
4. **Save reviewed** exports every reviewed image still awaiting export. Exports use PNG and refuse to overwrite existing files. A reviewed image with no selected boxes needs a separate confirmation before exporting an unredacted copy.
5. **Cancel scan** stops OCR and keeps completed results; **Scan all** continues with images that still need scanning.

Folder review status and markings last for the current session. Image files and optional logs are saved to disk. **Batch tools** holds Rescan all, Copy boxes to matching, and Match by anchor, with a count of how many can run now.

## Reuse fixed redaction areas

Draw or select the boxes for recurring areas on one image and click **Copy boxes to matching**. The app applies those rectangles at the same pixel coordinates on every other image with matching dimensions; existing boxes stay. Affected images need review before export. Use this when the framing and layout match, and check alignment before saving.

For images that shift slightly, select the boxes and click **Match by anchor**, then drag a rectangle around a distinctive, stable visual cue near them, such as a logo or label. The app searches the other photos locally and moves and scales the boxes relative to the match. It skips uncertain matches, competing repeated cues, and placements outside the image. Strong perspective changes, rotation, or layout changes may require manual placement.

## Audit exports

```powershell
.venv\Scripts\python.exe -m markseal.audit_exports "originals-folder" "export-folder"
```

The audit checks for unreadable PNGs, missing coordinate logs, changed pixels outside the logged rectangles, and wide boxes that warrant review. Add `--ocr` to compare a local RapidOCR Broad pass against the masks and look for readable matches in the exported images; add `--use-app-pattern` with `--ocr` to include the enabled blocked patterns. These are review candidates, not proof: visual review is still needed for readable identifiers OCR missed and for ordinary text under an oversized mask.

## Sharing

**Copy image** puts the confirmed preview on the local clipboard so you can paste it into chat, a ticket, documentation, or a sharing service you already use. **Save** writes a PNG and, when enabled, a coordinate log. MarkSeal has no upload integrations; sharing happens through your own clipboard or file workflow.
