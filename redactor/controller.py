from __future__ import annotations

import io
import re
from pathlib import Path
from queue import Queue
from threading import Event

from PIL import Image
from PySide6.QtCore import Property, QBuffer, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from . import export
from . import images
from . import ocr
from .facades import (
    Alerts, FolderFacade, JobCenter, ReviewFacade, SessionState, SettingsFacade,
)
from .facades.alerts import box_hint
from .ui.models import DisplayImageProvider
from . import workflows









class Controller(QObject):
    statusChanged = Signal()
    errorChanged = Signal()
    busyChanged = Signal()
    progressChanged = Signal()
    scanStageChanged = Signal()

    def __init__(self, preferences_file=None, parent=None):
        super().__init__(parent)
        self.session = SessionState(preferences_file)
        self.alerts = Alerts(self)
        self.jobs = JobCenter(self.session, self)
        self._settings = SettingsFacade(self.session, self.alerts, self)
        self._review = ReviewFacade(self.session, self.alerts, self)
        self._folder = FolderFacade(self.session, self.alerts, self)
        self.session.alerts = self.alerts
        self.session.jobs = self.jobs
        self.session.facades.settings = self._settings
        self.session.facades.review = self._review
        self.session.facades.folder = self._folder
        self._review.batch = self
        self._settings.on_method_changed = self._review.method_changed
        self._settings.retry_learn = self._review.beginLearnPattern
        self.alerts.statusChanged.connect(self.statusChanged)
        self.alerts.errorChanged.connect(self.errorChanged)
        self.jobs.busyChanged.connect(self.busyChanged)
        self.jobs.progressChanged.connect(self.progressChanged)
        self.jobs.scanStageChanged.connect(self.scanStageChanged)
        self.jobs.jobStatesQueued.connect(self._folder.set_job_states)
        self.jobs.jobStarted.connect(
            lambda row: self._folder.set_job_state(row, 'running'))
        self.jobs.jobCleared.connect(
            lambda row: self._folder.set_job_state(row, ''))
        self.jobs.jobStatesCleared.connect(self._folder.clear_job_states)
        self.jobs.rowsChanged.connect(self._folder.refresh_and_emit)
        self._review.reviewChanged.connect(self._folder.refresh_and_emit)
        self._folder.selectionChanged.connect(self._review.selection_changed)
        self.jobs.before_start = self._review.cancel_capture
        self._settings.load_preferences()
        if not self.alerts.status_text:
            self.alerts.set_status(box_hint(self.session.preferences.theme))

    @Property(QObject, constant=True)
    def settings(self):
        return self._settings

    @Property(QObject, constant=True)
    def review(self):
        return self._review

    @Property(QObject, constant=True)
    def folder(self):
        return self._folder

    def display_qimage(self):
        return self._review.display_qimage()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self.alerts.status_text

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self.jobs.busy

    @Property(str, notify=busyChanged)
    def busyLabel(self):
        return self.jobs.busyLabel

    @Property(str, notify=errorChanged)
    def errorText(self):
        return self.alerts.error_text

    @Property(str, notify=errorChanged)
    def errorDetail(self):
        return self.alerts.error_detail

    @Property(str, notify=errorChanged)
    def errorActionText(self):
        return self.alerts.error_action_text

    @Slot()
    def dismissError(self):
        self.alerts.dismiss()

    @Slot()
    def runErrorAction(self):
        self.alerts.run_action()

    @Property(bool, notify=busyChanged)
    def canCancel(self):
        return self.jobs.canCancel

    @Property(str, notify=progressChanged)
    def progressText(self):
        return self.jobs.progressText

    @Property(int, notify=progressChanged)
    def progressValue(self):
        return self.jobs.progressValue

    @Property(int, notify=progressChanged)
    def progressMax(self):
        return self.jobs.progressMax

    @Property(str, notify=progressChanged)
    def progressDetail(self):
        return self.jobs.progressDetail

    @Property(str, notify=progressChanged)
    def progressCurrent(self):
        return self.jobs.progressCurrent

    @Property(str, notify=scanStageChanged)
    def scanStage(self):
        return self.jobs.scanStage

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            None, 'Open image', '',
            'Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*.*)',
        )
        return Path(path) if path else None

    def _choose_folder(self, title):
        path = QFileDialog.getExistingDirectory(None, title)
        return Path(path) if path else None

    def _prepare_image_open(self):
        if self.jobs.busy:
            return False
        if not self._folder.can_leave():
            return False
        if not self.session.entries and self.session.review.boxes:
            if not self.alerts.ask('Open another image', 'Discard the current unsaved markings?'):
                return False
        return True

    def _present_image(self, image, path, pasted=False):
        self._review.cancel_capture()
        if self._folder.has_entries():
            self._folder.clear()
        self._review.load_image(image, path, pasted=pasted)
        self.alerts.set_status(
            f'{self._review.imageName}: find suggestions or drag to add a box, then confirm.'
        )

    @Slot()
    def openImage(self):
        if not self._prepare_image_open():
            return
        chosen = self._choose_image()
        if chosen is None:
            return
        try:
            with Image.open(chosen) as source:
                image = source.convert('RGB')
        except Exception as error:
            self.alerts.error('Cannot open image', str(error))
            return
        self._present_image(image, chosen)

    @Slot()
    def openFolder(self):
        if self.jobs.busy:
            return
        chosen = self._choose_folder('Open image folder')
        if chosen is None:
            return
        self._folder.open_path(chosen)

    @Slot('QVariantList')
    def openDropped(self, urls):
        if self.jobs.busy:
            return
        paths = []
        for value in urls or []:
            url = value if isinstance(value, QUrl) else QUrl(str(value))
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        images = [path for path in paths
                  if path.is_file() and path.suffix.lower() in images.IMAGE_SUFFIXES]
        if images:
            if not self._prepare_image_open():
                return
            try:
                with Image.open(images[0]) as source:
                    image = source.convert('RGB')
            except Exception as error:
                self.alerts.error('Cannot open image', str(error))
                return
            self._present_image(image, images[0])
            return
        folders = [path for path in paths if path.is_dir()]
        if folders:
            self._folder.open_path(folders[0])
            return
        self.alerts.info('Drop an image', 'Drop a PNG, JPEG, BMP, TIFF image, or an image folder.')

    def _clipboard_image(self):
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        if data.hasUrls():
            for url in data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_file() and path.suffix.lower() in images.IMAGE_SUFFIXES:
                        with Image.open(path) as source:
                            return source.convert('RGB'), path, False
        if data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, 'PNG')
                raw = bytes(buffer.data())
                buffer.close()
                with Image.open(io.BytesIO(raw)) as source:
                    return source.convert('RGB'), Path('pasted-image.png'), True
        return None

    @Slot()
    def pasteImage(self):
        if self.jobs.busy:
            return
        try:
            loaded = self._clipboard_image()
        except Exception as error:
            self.alerts.error('Cannot paste image', str(error))
            return
        if loaded is None:
            self.alerts.info('Paste image', 'The clipboard does not contain an image.')
            return
        if not self._prepare_image_open():
            return
        image, path, pasted = loaded
        self._present_image(image, path, pasted=pasted)

    @Slot()
    def scanAll(self):
        self._start_scan(self.session.entries, follow=True)

    @Slot()
    def scanSelected(self):
        if self.jobs.busy:
            return
        selected = sorted(self.session.row_selection)
        if not selected:
            self.alerts.info('Scan selected', 'Select one or more images in the folder list first.')
            return
        self._start_scan([self.session.entries[index] for index in selected], rescan=True, follow=True)

    @Slot()
    def rescanAll(self):
        if not self.jobs.busy and self.session.entries and self.alerts.ask(
                'Rescan all images?',
                'Keep existing boxes and add new suggestions. All rescanned images will need review again.'):
            self._start_scan(self.session.entries, rescan=True, follow=True)

    def _start_scan(self, entries, rescan=False, *, follow=False, area=None):
        if self.jobs.busy:
            return
        self.session.store_active()
        plan = workflows.plan_scan(self.session.entries, entries, rescan=rescan, area=area)
        pending = plan.entries
        if not pending:
            self.alerts.info(
                'Folder scan',
                'Every image has been scanned or manually reviewed. '
                'Use Find likely identifiers to rescan an image.',
            )
            return
        try:
            engine = self._scan_engine()
            settings = self._scan_settings()
        except OSError as error:
            self.alerts.error('OCR unavailable', str(error), 'RETRY',
                        lambda: self._start_scan(entries, rescan=rescan, follow=follow, area=area))
            return
        except (ValueError, re.error) as error:
            self.alerts.error('Invalid detection settings', str(error), 'OPEN SETTINGS',
                              self.session.facades.settings.requestSettings)
            return
        cancel = Event()
        enhanced = self.session.preferences.enhanced_ocr
        color_assisted = self.session.preferences.color_ocr
        processed = []
        area_completed = False

        def show_image(index):
            row = rows[pending[index].path]
            self._folder.activate_entry(int(row))

        def operation(job):
            path, stamp = job
            return ocr.scan_folder_image(
                path, stamp, engine, settings, enhanced, cancel,
                color_assisted=color_assisted, area=area,
            )

        def accept(index, result, error):
            nonlocal area_completed
            entry = pending[index]
            if error:
                if area is None:
                    entry.error = 'Scan failed'
                self.alerts.set_status(f'{entry.path.name} · {error}')
                return
            outcome = workflows.apply_scan_result(entry, result, area=area)
            if outcome.error:
                return
            area_completed = area is not None
            if self.session.active is not None and entry is self.session.entries[self.session.active] and self.session.review.image is not None:
                if outcome.changed:
                    self._review.invalidate()
                    self._review.emit_view()
                detail = (f' Partial scan: {", ".join(outcome.incomplete)}.'
                          if outcome.incomplete else '')
                self.alerts.set_status(
                    f'{entry.path.name} · {outcome.count} new OCR suggestions.{detail} Review before confirming.'
                )

        def track_result(index, result, error):
            accept(index, result, error)
            processed.append(pending[index])

        def finish():
            return workflows.scan_summary(processed, area=area, area_completed=area_completed)

        self.jobs.run(
            plan.label, list(plan.jobs), operation, track_result, finish,
            cancel=cancel, show_image=show_image if follow else None,
            metrics_settings=self._scan_metrics(), rows=plan.rows,
        )

    @Slot()
    def cancelScan(self):
        self.jobs.cancel()

    @Slot()
    def copyBoxesToFolder(self):
        if self.jobs.busy or self.session.active is None or self.session.review.image is None:
            return
        boxes = self.session.review.selected_boxes()
        if not boxes:
            self.alerts.info('Copy selected boxes', 'Select or draw the boxes you want to copy first.')
            return
        targets = [entry for index, entry in enumerate(self.session.entries) if index != self.session.active]
        if not targets:
            self.alerts.info('Copy selected boxes', 'Open a folder with at least two images.')
            return
        if not self.alerts.ask(
                'Copy selected boxes?',
                f'Copy {len(boxes)} selected box(es) to the same positions on other images of the same size? '
                'Check that the content lines up before confirming and saving.'):
            return
        size = self.session.review.image.size
        applied = skipped = unchanged = 0

        def operation(job):
            path, expected = job
            stamp = images.file_stamp(path)
            if expected is not None and stamp != expected:
                raise ValueError(f'{path.name} changed. Reopen the folder before copying boxes.')
            with Image.open(path) as image:
                matches = image.size == size
            if images.file_stamp(path) != stamp:
                raise ValueError(f'{path.name} changed while reading.')
            return stamp, matches

        def accept(index, result, error):
            nonlocal applied, skipped, unchanged
            if error:
                return
            entry = targets[index]
            stamp, matches = result
            outcome = workflows.copy_boxes_to_entry(entry, boxes, stamp, matches)
            if outcome == 'skipped':
                skipped += 1
                return
            if outcome == 'unchanged':
                unchanged += 1
                return
            applied += 1
            if self.session.active is not None and self.session.entries[self.session.active] is entry and self.session.review.image is not None:
                self._review.invalidate()

        def finish():
            return (f'{applied} updated · {skipped} skipped (size or source changed) · '
                    f'{unchanged} already selected')

        self.jobs.run(
            'Copying boxes',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self._folder.rows(),
        )

    def _match_boxes_to_folder(self, anchor):
        try:
            from .visual_anchor import locate_anchor, prepare_anchor, relocate_boxes
        except ImportError:
            self.alerts.error(
                'Visual matching unavailable',
                'Install the project dependencies with pip install -e . and restart.',
            )
            return
        boxes = self.session.review.selected_boxes()
        if not boxes:
            self.alerts.set_status('Select boxes to match across the folder.')
            return
        left, top, right, bottom = anchor
        if right - left < 20 or bottom - top < 20:
            self.alerts.set_status(
                'Anchor too small. Click Match boxes by visual anchor and drag around a larger area.'
            )
            return
        try:
            patch = prepare_anchor(self.session.review.image, anchor)
        except ValueError as error:
            self.alerts.set_status(str(error))
            return
        targets = [entry for index, entry in enumerate(self.session.entries) if index != self.session.active]
        matched = skipped = 0

        def operation(job):
            path, expected = job
            image, stamp = images.read_folder_image(path, expected)
            match = locate_anchor(image, patch)
            placed = relocate_boxes(boxes, anchor, match, image.size) if match else []
            return stamp, placed

        def accept(index, result, error):
            nonlocal matched, skipped
            entry = targets[index]
            if error:
                return
            stamp, placed = result
            matched_here, changed = workflows.match_boxes_to_entry(entry, placed, stamp)
            if not matched_here:
                skipped += 1
                return
            matched += 1
            if changed and self.session.active is not None and self.session.entries[self.session.active] is entry:
                self._review.invalidate()

        def finish():
            return f'{matched} matched · {skipped} skipped (no reliable placement)'

        self.jobs.run(
            'Matching visual anchor',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self._folder.rows(),
        )

    @Slot()
    def confirmAll(self):
        if not self.jobs.busy and self.session.entries:
            self._confirm_entries(self.session.entries, 'Confirm all')

    def _confirm_entries(self, entries, title):
        self.session.store_active()
        pending = workflows.eligible_for_confirmation(entries)
        if not pending:
            self.alerts.info(
                title,
                'No eligible images are awaiting confirmation. Check whether they are already '
                'reviewed, have no selected boxes, or have a scan error.',
            )
            return
        if not self.alerts.ask(title, workflows.confirmation_prompt(pending, self.session.preferences.method)):
            return
        for entry in pending:
            entry.reviewed = True
        self._review.apply_confirmation()
        self._folder.refresh_and_emit()
        self.alerts.set_status(
            f'Confirmed {len(pending)} image(s). Use Save reviewed to export them.'
        )

    @Slot()
    def saveReviewed(self):
        if self.jobs.busy:
            return
        self.session.store_active()
        pending = [(index, entry) for index, entry in enumerate(self.session.entries)
                   if entry.reviewed and not entry.saved]
        if not pending:
            self.alerts.info('Save reviewed', 'Confirm the selection on each image you want to save.')
            return
        self._export_entries(pending)

    def _export_entries(self, pending, individual=False):
        def choose(target):
            chosen, _ = QFileDialog.getSaveFileName(
                None, 'Save redacted copy', str(target), 'PNG image (*.png)'
            )
            return chosen or None

        try:
            plan = workflows.plan_exports(
                pending,
                output_directory=self.session.output_directory,
                template=self.session.preferences.filename_template,
                include_log=self.session.preferences.include_log,
                choose=choose if individual else None,
            )
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            self.alerts.error('Cannot save images', str(error), 'RETRY', self.saveReviewed)
            return
        if plan is None:
            return
        jobs = list(plan.jobs)
        unredacted = plan.unredacted
        if unredacted and not self.alerts.ask(
                'Save unredacted copies?',
                f'{unredacted} reviewed image(s) have no selected boxes. '
                'Save them as unredacted PNG copies?'):
            return

        include_log = self.session.preferences.include_log
        snapshots = [
            (entry, export.snapshot(entry.path, target, entry.boxes, entry.selected,
                                    entry.method, stamp=entry.stamp))
            for entry, target in jobs
        ]

        def operation(job):
            entry, snapshot = job
            snapshot.target.parent.mkdir(parents=True, exist_ok=True)
            export.write_copy(snapshot, include_log=include_log)

        def accept(index, result, error):
            entry, target = jobs[index]
            snapshot = snapshots[index][1]
            if error:
                self.alerts.set_status(f'{entry.path.name} · {error}')
            elif workflows.export_succeeded(entry, snapshot):
                entry.saved = True
                entry.error = ''
                self.alerts.set_status(f'Saved {target.name} to {target.parent}')

        self.jobs.run(
            'Saving', snapshots, operation, accept,
            metrics_settings={'method': self.session.preferences.method, 'coordinate_logs': include_log},
            rows=self._folder.rows(),
        )

    def save_active(self):
        entry = self.session.entries[self.session.active]
        self._export_entries([(self.session.active, entry)], individual=True)

    def scan_entry(self, entry, rescan=False, area=None):
        self._start_scan([entry], rescan=rescan, area=area)

    def match_boxes_to_folder(self, anchor):
        self._match_boxes_to_folder(anchor)

    def confirm_entries(self, entries, title):
        self._confirm_entries(entries, title)
