# Offline Screenshot Redactor

Double-click `launch.bat` to run the app using the project’s `.venv`. To recreate the environment, run `python -m venv .venv` and then `.venv\Scripts\python.exe -m pip install -r requirements.txt`. Python 3 is required. The program does not make network calls and sends image data to OCR only through a local process.

Open an image and use Find likely identifiers to draw suggested boxes. Suggestions start selected (green). Click a box to exclude it from redaction (orange), or click again to select it. Click the X at a box’s upper-right corner to remove it. After confirming, use **Edit boxes** to show the outlines and X buttons again. Drag to add a manually drawn box; it starts selected. If boxes overlap, clicking affects the topmost box. Click Confirm selection to apply pixelation in the preview, then save a PNG copy and its JSON coordinate log. Only selected boxes are applied and included in the log. Changing a selection after confirmation requires confirming again. The original image is not overwritten. The log contains the source filename and coordinates; inspect it before sharing. Undo removes the most recently added box.

Use the mouse wheel over the image to zoom in or out around the pointer. Right-click and drag to move around while zoomed in. Zoom does not change the saved image.

## Work through a folder

1. Use **Open folder** to list the supported images directly inside a folder. Select a row to switch images and keep its boxes and selections during the session.
2. Use **Scan all** to check the remaining images in the background, or **Find likely identifiers** for the current image. **Scan all** and **Rescan all** follow each photo in the viewer and briefly show its suggested boxes before moving on. A scan marks an image **Scanned · review needed**, even when it suggests zero boxes.
3. Inspect each image, adjust its boxes, and click **Confirm selection** to mark it **Reviewed**, or use **Confirm all** to confirm the selected boxes on every eligible image at once. Confirm all skips images with no selected boxes and images with errors.
4. Use **Settings → Folder output** to choose an output folder, filename template, and whether to include coordinate logs. The default is the input folder’s `redacted` subfolder and `{stem}_redacted.png`. Use `{stem}` for the original name without its extension, `{ext}` for the original extension without the dot, and `{index}` for its position in the folder. For example, `reviewed_{index:03d}` produces names such as `reviewed_001.png`.
5. **Save redacted copy** opens a save dialog for the current image. **Save reviewed images** exports all reviewed images still awaiting export and marks them **Saved**. Exports use PNG and refuse to overwrite existing files. A reviewed image with no selected boxes requires a separate confirmation before exporting an unredacted copy.

The folder panel shows a progress bar, the current filename, and a completion summary for scans, box copying, visual matching, and exports. Folder counts stay visible while jobs run. **Cancel scan** stops OCR and keeps completed results. Use **Scan all** to continue with images that still need to be scanned.

Folder review status and markings are kept for the current session. Image files and optional logs are saved to disk.

## Reuse fixed redaction areas

Draw or select the boxes for recurring areas on one image and click **Copy selected boxes to folder**. The app selects those rectangles at the same pixel coordinates on every other image with matching dimensions. Existing boxes stay in place. Images affected by the copy need review before export, and your previously exported files are unchanged. Use this for images with the same framing and layout, and check the alignment before saving.

For images that shift slightly between shots, select the redaction boxes and click **Match boxes by visual anchor**. Drag a separate rectangle around a distinctive, stable visual cue near those boxes, such as a logo or a label. The app searches the other photos locally and moves and scales the selected boxes relative to the matched cue. It skips uncertain matches, repeated cues with competing matches, and placements that would go outside the image. Review each result. Strong perspective changes, rotation, or layout changes may require manual placement.

## Find likely identifiers

Open **Settings → Detection** to adjust scanning preferences. Apply or close the Settings window with its X to save your preferences locally. The app restores them the next time it opens. Cancel or Escape discards edits.

Tesseract OCR is available in `tools/tesseract` in this project. The app checks that location first, then PATH and standard system locations. Image processing runs offline. The project-local copy can be restored by extracting a trusted Tesseract Windows package to that folder. Click **Find likely identifiers** to mark OCR words matching the enabled patterns. **Focused** enables email, URL, IP address, credential, and infrastructure patterns (including configuration keys, deployment files, certificate paths, and common secret references); **Balanced** adds tickets, username paths and hashes; **Broad** also enables long identifiers. Open **Settings → Detection** to choose types or enter a custom Python regular expression. The custom pattern is used alongside enabled types. Changing a preset resets the type checkboxes but keeps the custom pattern.

**Min OCR confidence** filters individual recognized words from 0 to 100; it measures text-recognition confidence, not the probability that content is sensitive. A higher threshold can reduce noisy boxes but can also hide faint sensitive text. **Suggest all detected text** bypasses pattern filtering and marks every word above the confidence threshold; turn it off for fewer suggestions. Changes affect the next scan. **Enhanced OCR** adds a second pass with noise reduction, contrast adjustment, and a different text layout mode. It takes longer, and may recover additional text in photos of screens. Try it on an individual image before scanning a large folder. **Color-assisted OCR** keeps the original scan and adds a local-contrast pass plus up to two color-contrast passes. This can help when text and background are similar in brightness but differ in color. The additional versions exist only in memory, and suggestions use the original image coordinates. Enable it for difficult images or rescans, since extra passes take longer. Extra passes use copies capped at 2400 pixels on the longest side and share a 35-second budget. If an extra pass times out, completed suggestions are kept and the image is marked as a partial scan. Confirm partial scans individually after reviewing them. **Rescan all (keep boxes)** uses the current settings on every image and returns successful scans to review. Scans add boxes to the current ones; use **Clear boxes** to start over before rescanning. The application does not download or install OCR.

For small text missed by a full image scan, zoom in and click **Scan area**, then drag tightly around the text. The app scans an enlarged copy of the selected original pixels and adds boxes to the original image. A narrow region is treated as a single text line. An area scan does not mark the full image as scanned.

Suggestions are incomplete: OCR may miss small, blurred or skewed text; pattern matching can miss names, organization names, repository identifiers, unusual domains and secrets. Results can include false positives. Always inspect the entire output and add missing rectangles manually. A zero-suggestion result does not establish that an image is safe.

## Redaction method

Use **Settings → Redaction** to choose pixelation or solid black. The method applies across the folder and is remembered across app restarts. Changing it returns the images to review before export. Solid black removes image detail inside the chosen boxes and is more appropriate for sensitive information. Pixels outside selected rectangles are preserved in the PNG. Camera metadata is omitted from saved copies.

## Pixelation warning

Pixelation changes only marked rectangles, using coarse blocks, but it can leave text or visual features recognizable or recoverable. For highly sensitive material use irreversible opaque fills instead, and independently review before sharing. This tool cannot guarantee removal of all sensitive information.

## Backlog

- Modernize the desktop UI after the core review workflow is stable. Evaluate Python with PySide6 and Qt Quick for a cross-platform path, or C# with WinUI 3 if Windows is the only target. Focus on keyboard navigation, clear review states, and an export preview.
