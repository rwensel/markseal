"""The current image's review: boxes, selection, viewport, and clipboard."""
from __future__ import annotations

import re
from pathlib import Path
from queue import Queue

from PIL import Image
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QFileDialog

from .. import export, images, ocr, redaction
from ..audit_exports import verify_export
from ..performance_log import PerformanceRun


class ReviewFacade(QObject):
    imageChanged = Signal()
    imageRevisionChanged = Signal()
    reviewChanged = Signal()
    viewChanged = Signal()
    captureChanged = Signal()
    confirmLabelChanged = Signal()
    verifyResult = Signal(dict)

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self.capture = 'none'
        self.drag = None
        self._panning = False
        self.image_revision = 0
        self._display_qimage = QImage()
        self.batch = None
        self.last_export = None
        self.last_verify = None

    @Property(bool, notify=imageChanged)
    def hasImage(self):
        return self.session.review.image is not None

    @Property(str, notify=imageChanged)
    def imageName(self):
        if self.session.pasted_image:
            return 'Pasted image'
        return self.session.review.path.name if self.session.review.path else ''

    @Property(str, notify=imageChanged)
    def imageSizeText(self):
        if self.session.review.image is None:
            return ''
        width, height = self.session.review.image.size
        return f'{width} × {height}'

    @Property(int, notify=imageRevisionChanged)
    def imageRevision(self):
        return self.image_revision

    @Property(int, notify=imageChanged)
    def imageWidth(self):
        return self.session.review.image.width if self.session.review.image else 0

    @Property(int, notify=imageChanged)
    def imageHeight(self):
        return self.session.review.image.height if self.session.review.image else 0

    @Property(list, notify=reviewChanged)
    def boxes(self):
        boxes = []
        for index, box in enumerate(self.session.review.boxes):
            labels = tuple(self.session.review.rules.get(box, ())) or ('Manual box',)
            label = labels[0] if len(labels) == 1 else f'{labels[0]} +{len(labels) - 1}'
            boxes.append({
                'x1': box[0], 'y1': box[1], 'x2': box[2], 'y2': box[3],
                'selected': index in self.session.review.selected,
                'rules': list(labels), 'ruleLabel': label,
            })
        return boxes

    @Property(int, notify=reviewChanged)
    def selectedCount(self):
        return len(self.session.review.selected)

    @Property(int, notify=reviewChanged)
    def excludedCount(self):
        return len(self.session.review.boxes) - len(self.session.review.selected)

    @Property(int, notify=reviewChanged)
    def totalBoxes(self):
        return len(self.session.review.boxes)

    @Property(bool, notify=reviewChanged)
    def confirmed(self):
        return self.session.review.confirmed

    @Property(str, notify=confirmLabelChanged)
    def confirmLabel(self):
        count = len(self.session.row_selection) if self.session.entries else 0
        return f'CONFIRM {count}' if count > 1 else 'CONFIRM'

    @Property(float, notify=viewChanged)
    def viewScale(self):
        return self.session.review.scale

    @Property(float, notify=viewChanged)
    def viewOffsetX(self):
        return self.session.review.offset_x

    @Property(float, notify=viewChanged)
    def viewOffsetY(self):
        return self.session.review.offset_y

    @Property(int, notify=viewChanged)
    def zoomPercent(self):
        return round(self.session.review.zoom * 100)

    @Property(bool, notify=viewChanged)
    def panning(self):
        return self._panning

    @Property(bool, notify=viewChanged)
    def dragActive(self):
        return self.drag is not None

    @Property(float, notify=viewChanged)
    def dragX(self):
        return self.drag[0] if self.drag else 0

    @Property(float, notify=viewChanged)
    def dragY(self):
        return self.drag[1] if self.drag else 0

    @Property(float, notify=viewChanged)
    def dragWidth(self):
        return self.drag[2] if self.drag else 0

    @Property(float, notify=viewChanged)
    def dragHeight(self):
        return self.drag[3] if self.drag else 0

    @Property(str, notify=captureChanged)
    def captureMode(self):
        return self.capture

    def display_qimage(self):
        return self._display_qimage

    def refresh_display(self):
        image = self.session.review.image
        if image is not None and self.session.review.confirmed:
            image = redaction.apply_redactions(
                image, self.session.review.selected_boxes(), self.session.preferences.method
            )
        if image is None:
            self._display_qimage = QImage()
        else:
            self._display_qimage = self._pil_to_qimage(image)
        self.image_revision += 1
        self.imageRevisionChanged.emit()

    def _pil_to_qimage(self, image):
        if image.mode != 'RGB':
            image = image.convert('RGB')
        raw = image.tobytes('raw', 'RGB')
        return QImage(
            raw, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
        ).copy()

    def emit_review(self):
        self.reviewChanged.emit()

    def emit_view(self):
        self.viewChanged.emit()

    def review_status(self):
        name = self.session.review.path.name if self.session.review.path else ''
        return (f'{name}: {len(self.session.review.selected)} selected of '
                f'{len(self.session.review.boxes)}. Confirm to apply.')

    def load_image(self, image, path, pasted=False):
        self.session.pasted_image = pasted
        self.session.review.load(image, path)
        self.refresh_display()
        self.imageChanged.emit()
        self.emit_review()
        self.emit_view()

    def adopt_entry(self, entry):
        self.session.pasted_image = False
        self.session.review.path = entry.path
        self.session.review.boxset = entry.boxset
        self.session.review.confirmed = entry.reviewed
        self.session.review.viewport.clear()

    def set_entry_image(self, image):
        self.session.review.image = image
        if image is not None:
            self.session.review.viewport.reset(image.size)
            self.refresh_display()

    def invalidate(self):
        self.session.review.confirmed = False
        self.refresh_display()
        self.emit_review()

    def apply_confirmation(self):
        if self.session.active is not None and self.session.review.image is not None:
            self.session.review.confirmed = self.session.entries[self.session.active].reviewed
            self.refresh_display()
            self.emit_review()

    def method_changed(self):
        if not self.session.entries:
            if self.session.review.confirmed:
                self.refresh_display()
            return
        method = self.session.preferences.method
        for entry in self.session.entries:
            if entry.method != method:
                entry.method = method
                entry.reviewed = entry.saved = False
        self.session.review.confirmed = False
        self.refresh_display()
        self.emit_review()
        self.alerts.set_status(
            f'{method} will be used across the folder. '
            'Confirm the updated redactions before saving.'
        )

    def selection_changed(self):
        self.confirmLabelChanged.emit()

    @Slot(int, int)
    def setViewSize(self, width, height):
        self.session.review.set_view_size(width, height)
        self.emit_view()

    @Slot(int, int)
    def press(self, x, y):
        if self.capture != 'none' and self.session.review.image is not None:
            self.session.review.viewport.begin_drag(x, y)
            self.drag = (x, y, 0, 0)
            self.emit_view()
            return
        self.session.review.press(x, y)

    @Slot(int, int)
    def move(self, x, y):
        if self.session.review.viewport.pan_origin is not None:
            if self.session.review.pan_move(x, y):
                self.emit_view()
            return
        rect = self.session.review.viewport.drag_rect(x, y)
        if rect is not None:
            self.drag = rect
            self.emit_view()

    @Slot(int, int)
    def release(self, x, y):
        if self._panning:
            if self.session.review.pan_end():
                self._panning = False
                self.viewChanged.emit()
            return
        if (self.capture != 'none' and self.session.review.viewport.drag_origin is not None
                and self.session.review.image is not None):
            capture = self.capture
            anchor = self.session.review.viewport.drag_region(x, y)
            self.cancel_capture()
            if capture == 'area':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    self.alerts.set_status(
                        'Area too small. Click Scan area and draw around the text again.'
                    )
                elif self.session.active is None:
                    self.start_single_scan(area=anchor)
                else:
                    self.batch.scan_entry(
                        self.session.entries[self.session.active], rescan=True, area=anchor
                    )
            elif capture == 'learn':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    self.alerts.set_status(
                        'Area too small. Draw a tight box around the text you want to block.'
                    )
                else:
                    self.session.facades.settings.learn_pattern(anchor)
            else:
                self.batch.match_boxes_to_folder(anchor)
            return
        self.drag = None
        action = self.session.review.release(x, y)
        if action != 'none':
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.alerts.set_status(self.review_status())
        self.emit_view()

    @Slot(int, int, int)
    def zoomAt(self, x, y, delta):
        if self.session.review.zoom_at(x, y, 1 if delta > 0 else -1):
            self.emit_view()

    @Slot(int)
    def zoomStep(self, direction):
        if self.session.review.image is None:
            return
        viewport = self.session.review.viewport
        if self.session.review.zoom_at(
                viewport.view_width / 2, viewport.view_height / 2, direction):
            self.emit_view()

    @Slot()
    def zoomFit(self):
        if self.session.review.image is None:
            return
        viewport = self.session.review.viewport
        viewport.zoom = 1.0
        viewport.refit()
        self.emit_view()

    @Slot(int, int)
    def panStep(self, dx, dy):
        if self.session.review.image is None or self.session.review.zoom <= 1.0:
            return
        viewport = self.session.review.viewport
        viewport.offset_x += dx
        viewport.offset_y += dy
        viewport.clamp_offsets()
        self.emit_view()

    @Slot()
    def selectAllBoxes(self):
        if self.session.review.select_all():
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.alerts.set_status(self.review_status())

    @Slot()
    def selectNoBoxes(self):
        if self.session.review.select_none():
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.alerts.set_status(self.review_status())

    @Slot(int, int)
    def beginPan(self, x, y):
        if self.session.review.pan_begin(x, y):
            self._panning = True
            self.viewChanged.emit()

    @Slot(int, int)
    def movePan(self, x, y):
        if self.session.review.pan_move(x, y):
            self.viewChanged.emit()

    @Slot()
    def endPan(self):
        if self.session.review.pan_end():
            self._panning = False
            self.viewChanged.emit()

    @Slot(int)
    def toggleBox(self, index):
        if self.session.review.confirmed:
            return
        if self.session.review.toggle_box(index):
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.alerts.set_status(self.review_status())

    @Slot(int)
    def removeBox(self, index):
        if self.session.review.confirmed:
            return
        if self.session.review.remove_box(index):
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.emit_view()
            self.alerts.set_status(
                f'{self.session.review.path.name}: box removed. '
                f'{len(self.session.review.selected)} selected of '
                f'{len(self.session.review.boxes)}.'
            )

    @Slot()
    def undo(self):
        if self.session.review.undo():
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.emit_view()
        if self.session.review.image is not None:
            self.alerts.set_status(self.review_status())

    @Slot()
    def editBoxes(self):
        if self.session.review.image is None or not self.session.review.confirmed:
            return
        self.session.review.confirmed = False
        self.refresh_display()
        self.session.store_active()
        self.emit_review()
        self.alerts.set_status(
            'Click an X to remove a box. Confirm selection when ready.'
        )

    @Slot()
    def clearBoxes(self):
        if not self.session.review.boxes:
            return
        if not self.alerts.ask('Clear boxes', 'Remove all suggested and manually drawn boxes?'):
            return
        self.session.review.clear()
        self.refresh_display()
        self.session.store_active()
        self.emit_review()
        self.emit_view()
        self.alerts.set_status('Boxes cleared. Scan again or drag to add an area.')

    @Slot()
    def confirmSelection(self):
        if self.session.jobs.busy or self.session.review.image is None:
            return
        selected = sorted(self.session.row_selection) if self.session.entries else ()
        if len(selected) > 1:
            self.batch.confirm_entries(
                [self.session.entries[index] for index in selected],
                'Confirm selected images',
            )
            return
        self.session.review.confirmed = True
        self.refresh_display()
        self.session.store_active()
        self.emit_review()
        self.alerts.set_status(
            f'{len(self.session.review.selected)} boxes applied in preview. '
            'Save, or click to change your selection.'
        )

    @Slot()
    def redactAll(self):
        review = self.session.review
        if self.session.jobs.busy or review.image is None or review.confirmed:
            return
        if not review.boxes:
            return
        review.select_all()
        review.confirmed = True
        self.refresh_display()
        self.session.store_active()
        self.emit_review()
        self.alerts.set_status(
            f'All {len(review.selected)} boxes applied in preview. '
            'Save, or click to change your selection.'
        )

    @Slot()
    def cancelCapture(self):
        if self.capture != 'none':
            self.cancel_capture()
            self.alerts.set_status('Area selection canceled.')

    def cancel_capture(self):
        if self.capture != 'none' or self.drag is not None:
            self.capture = 'none'
            self.drag = None
            self.session.review.viewport.cancel_drag()
            self.captureChanged.emit()
            self.emit_view()

    @Slot()
    def find(self):
        if self.session.jobs.busy or self.session.review.image is None:
            return
        if self.session.active is not None:
            self.batch.scan_entry(self.session.entries[self.session.active], rescan=True)
            return
        self.start_single_scan()

    def start_single_scan(self, area=None):
        if self.session.review.image is None or self.session.jobs.busy:
            return
        try:
            engine = self.session.scan_engine()
            settings = self.session.scan_settings()
        except OSError as error:
            self.alerts.error('OCR unavailable', str(error), 'RETRY',
                              lambda: self.start_single_scan(area=area))
            return
        except (ValueError, re.error) as error:
            self.alerts.error('Invalid detection settings', str(error), 'OPEN SETTINGS',
                              self.session.facades.settings.requestSettings)
            return
        stages = Queue()
        info = {'added': None, 'incomplete': [], 'error': None}
        label = 'Scanning area' if area is not None else 'Scanning image'

        def operation(job):
            incomplete = []
            found = ocr.recognize_regions(
                self.session.review.image, engine, settings,
                self.session.preferences.enhanced_ocr,
                color_assisted=self.session.preferences.color_ocr, incomplete=incomplete,
                area=area, progress=stages.put,
            )
            return None, found, incomplete

        def accept(index, result, error):
            if error is not None:
                info['error'] = error
                self.alerts.set_status(f'Scan failed: {error}')
                return
            _, found, incomplete = result
            added = self.session.review.add_suggestions(found)
            self.refresh_display()
            self.session.store_active()
            self.emit_review()
            self.emit_view()
            info['added'] = added
            info['incomplete'] = incomplete
            detail = f' Incomplete OCR passes: {", ".join(incomplete)}.' if incomplete else ''
            self.alerts.set_status(
                f'{added} selected suggestions added.{detail} Review the entire image.'
            )

        def finish():
            if info['error'] is not None:
                return 'Scan failed'
            return f'{info["added"] or 0} new OCR suggestions'

        def complete():
            if info['error'] is not None:
                self.alerts.error(
                    'Local OCR failed', f'Text recognition failed: {info["error"]}',
                    'RETRY', lambda: self.start_single_scan(area=area),
                )
                return
            if info['added'] is None:
                return
            detail = (f' Incomplete OCR passes: {", ".join(info["incomplete"])}.'
                      if info['incomplete'] else '')
            self.alerts.info(
                'Review required',
                f'Added {info["added"]} selected boxes.{detail} '
                'Review the image before confirming.',
            )

        self.alerts.set_status(
            'Scanning the selected area. Progress is shown above the screenshot.'
            if area is not None
            else 'Scanning image. Progress is shown above the screenshot.'
        )
        self.session.jobs.run(
            label, [self.session.review.path], operation, accept, finish,
            metrics_settings=self.session.scan_metrics(), stage_queue=stages,
            complete=complete, report_failures=False,
        )

    @Slot()
    def beginScanArea(self):
        if self.session.jobs.busy or self.session.review.image is None:
            return
        self.cancel_capture()
        self.capture = 'area'
        self.captureChanged.emit()
        self.alerts.set_status(
            'Drag around the text to scan. For small labels, draw a tight box around '
            'a single row. Esc cancels.'
        )

    @Slot()
    def beginAnchorCapture(self):
        if (self.session.jobs.busy or self.session.active is None
                or self.session.review.image is None):
            return
        if not self.session.review.selected or len(self.session.entries) < 2:
            self.alerts.info(
                'Match by visual anchor',
                'Select redaction boxes on one image in a folder with at least two images.',
            )
            return
        self.cancel_capture()
        self.editBoxes()
        self.capture = 'anchor'
        self.captureChanged.emit()
        self.alerts.set_status(
            'Drag around a distinctive logo or label near the boxes. Esc cancels.'
        )

    @Slot()
    def beginLearnPattern(self):
        if self.session.jobs.busy or self.session.review.image is None:
            return
        self.cancel_capture()
        self.capture = 'learn'
        self.captureChanged.emit()
        self.alerts.set_status(
            'Drag around the text to block. The area is read locally and turned into '
            'a pattern. Esc cancels.'
        )

    @Slot()
    def copyRedacted(self):
        if self.session.review.image is None:
            return
        if not self.session.review.confirmed:
            self.alerts.set_status('Confirm selection to copy the redacted image.')
            return
        if not self.session.review.selected and not self.alerts.ask(
                'No redactions', 'No areas are selected. Copy the unredacted image?'):
            return
        if self._display_qimage.isNull():
            self.alerts.error('Copy failed', 'The preview is not available.',
                              'RETRY', self.copyRedacted)
            return
        QGuiApplication.clipboard().setImage(self._display_qimage.copy())
        if self.session.review.selected:
            self.alerts.set_status(
                f'Copied the redacted image with {len(self.session.review.selected)} '
                'box(es) to the clipboard.'
            )
        else:
            self.alerts.set_status('Copied the unredacted image to the clipboard.')

    @Slot()
    def save(self):
        if self.session.jobs.busy or self.session.review.image is None:
            return
        if self.session.active is None:
            self.save_single()
            return
        self.session.store_active()
        entry = self.session.entries[self.session.active]
        if self.session.review.image is None or not entry.reviewed:
            self.alerts.set_status('Confirm the selection on this image before saving.')
            return
        self.batch.save_active()

    def save_single(self):
        if self.session.review.image is None:
            return
        if not self.session.review.confirmed:
            self.alerts.set_status('Confirm the selection before saving.')
            return
        if not self.session.review.selected and not self.alerts.ask(
                'No redactions', 'No areas are selected. Save an unredacted copy?'):
            return
        initial = self.session.review.path.stem + '_redacted.png'
        chosen, _ = QFileDialog.getSaveFileName(
            None, 'Save redacted copy', initial, 'PNG image (*.png)'
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.resolve() == self.session.review.path.resolve():
            self.alerts.error('Choose a different file',
                              'The original image cannot be overwritten.')
            return
        include_log = self.session.preferences.include_log
        trace = PerformanceRun('Saving image', 1, {
            'method': self.session.preferences.method, 'coordinate_logs': include_log,
        })
        self.session.jobs.begin_manual('Saving copy')
        self.alerts.set_status('Saving the redacted copy…')
        QGuiApplication.processEvents()
        error = None
        try:
            with trace.image(0):
                job = export.snapshot(
                    self.session.review.path, target, self.session.review.boxes,
                    self.session.review.selected, self.session.preferences.method,
                    image=self.session.review.image, pasted=self.session.pasted_image,
                )
                export.write_copy(job, include_log=include_log, overwrite=True)
        except Exception as exc:
            error = exc
        finally:
            trace.finish()
            self.session.jobs.end_manual()
        if error is not None:
            self.alerts.error('Save failed', str(error), 'RETRY', self.save)
            return
        self.last_export = target
        note = ' and coordinate log' if include_log else ''
        self.alerts.info(
            'Saved',
            f'Saved the redacted PNG{note}. Review before sharing; '
            'pixelated text can sometimes be recovered.',
        )

    @Slot()
    def verifyCurrent(self):
        source = self.session.review.path
        if self.session.pasted_image or source is None:
            self.alerts.set_status(
                'Cannot verify a pasted image: there is no original file to compare.'
            )
            return
        path = self.last_export
        if path is None or not Path(path).is_file():
            self.alerts.set_status('Save the redacted copy first, then verify it.')
            return
        result = verify_export(Path(path), Path(source).parent)
        self.last_verify = result
        self.verifyResult.emit(result)
        name = Path(path).name
        if result['issue']:
            self.alerts.error('Verify failed', f'{name}: {result["issue"]}')
        elif result['outside_pixels_unchanged']:
            self.alerts.set_status(
                f'Verified {name}: pixels outside redactions unchanged.'
            )
        else:
            self.alerts.error('Verify failed', f'{name}: pixels outside redactions changed.')
