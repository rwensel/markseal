"""Whole-folder scan, confirm, copy, match, and export workflows."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Event

from PIL import Image
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .. import images, workflows
from ..export_copy import CopyRequest, ExportCopies, export_succeeded
from ..scan import Scan, ScanError
from ..preferences import PreferencesError, enabled_blocked_patterns, preferences_path


class BatchFacade(QObject):
    busyChanged = Signal()
    progressChanged = Signal()
    scanStageChanged = Signal()
    verifyResult = Signal(dict)
    auditChanged = Signal()

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self.session.jobs.busyChanged.connect(self.busyChanged)
        self.session.jobs.progressChanged.connect(self.progressChanged)
        self.session.jobs.scanStageChanged.connect(self.scanStageChanged)
        self.last_verify = None
        self._audit_originals = ''
        self._audit_exports = ''
        self._audit_run_ocr = False
        self._audit_use_patterns = False
        self._audit_results = []
        self._audit_summary = ''
        self._audit_has_run = False
        self._audit_running = False

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self.session.jobs.busy

    @Property(str, notify=busyChanged)
    def busyLabel(self):
        return self.session.jobs.busyLabel

    @Property(bool, notify=busyChanged)
    def canCancel(self):
        return self.session.jobs.canCancel

    @Property(str, notify=progressChanged)
    def progressText(self):
        return self.session.jobs.progressText

    @Property(int, notify=progressChanged)
    def progressValue(self):
        return self.session.jobs.progressValue

    @Property(int, notify=progressChanged)
    def progressMax(self):
        return self.session.jobs.progressMax

    @Property(str, notify=progressChanged)
    def progressDetail(self):
        return self.session.jobs.progressDetail

    @Property(str, notify=progressChanged)
    def progressCurrent(self):
        return self.session.jobs.progressCurrent

    @Property(str, notify=scanStageChanged)
    def scanStage(self):
        return self.session.jobs.scanStage

    @Property(str, notify=auditChanged)
    def auditOriginals(self):
        return self._audit_originals

    @Property(str, notify=auditChanged)
    def auditExports(self):
        return self._audit_exports

    @Property(bool, notify=auditChanged)
    def auditRunOcr(self):
        return self._audit_run_ocr

    @Property(bool, notify=auditChanged)
    def auditUsePatterns(self):
        return self._audit_use_patterns

    @Property('QVariantList', notify=auditChanged)
    def auditResults(self):
        return list(self._audit_results)

    @Property(str, notify=auditChanged)
    def auditSummary(self):
        return self._audit_summary

    @Property(bool, notify=auditChanged)
    def auditHasRun(self):
        return self._audit_has_run

    @Property(bool, notify=auditChanged)
    def auditRunning(self):
        return self._audit_running

    @Slot(str)
    def setAuditOriginals(self, path):
        self._audit_originals = str(path or '')
        self.auditChanged.emit()

    @Slot(str)
    def setAuditExports(self, path):
        self._audit_exports = str(path or '')
        self.auditChanged.emit()

    @Slot(bool)
    def setAuditRunOcr(self, enabled):
        self._audit_run_ocr = bool(enabled)
        if not self._audit_run_ocr:
            self._audit_use_patterns = False
        self.auditChanged.emit()

    @Slot(bool)
    def setAuditUsePatterns(self, enabled):
        self._audit_use_patterns = bool(enabled) and self._audit_run_ocr
        self.auditChanged.emit()

    @Slot()
    def prepareAudit(self):
        if not self._audit_originals and self.session.folder:
            self._audit_originals = str(self.session.folder)
        if not self._audit_exports:
            saved = next((entry.export_path for entry in self.session.entries
                          if entry.saved and entry.export_path is not None), None)
            if saved is not None:
                self._audit_exports = str(saved.parent)
            elif self._audit_originals:
                candidate = Path(self._audit_originals) / 'redacted'
                if candidate.is_dir():
                    self._audit_exports = str(candidate)
        self.auditChanged.emit()

    def _choose_audit_folder(self, title, current):
        path = QFileDialog.getExistingDirectory(None, title, current or '')
        return path or ''

    @Slot()
    def chooseAuditOriginals(self):
        path = self._choose_audit_folder('Select originals folder', self._audit_originals)
        if path:
            self.setAuditOriginals(path)

    @Slot()
    def chooseAuditExports(self):
        path = self._choose_audit_folder('Select export folder', self._audit_exports)
        if path:
            self.setAuditExports(path)

    def _audit_summary_text(self):
        total = len(self._audit_results)
        issues = sum(1 for item in self._audit_results
                     if item.get('issue') or item.get('outside_pixels_unchanged') is False)
        wide = sum(int(item.get('wide_boxes') or 0) for item in self._audit_results)
        clean = total - issues
        noun = 'export' if total == 1 else 'exports'
        issue_noun = 'issue' if issues == 1 else 'issues'
        box_noun = 'box' if wide == 1 else 'boxes'
        return f'{total} {noun} · {clean} clean · {issues} {issue_noun} · {wide} wide {box_noun}'

    @Slot()
    def startAudit(self):
        if self.session.jobs.busy or self._audit_running:
            return
        originals = Path(self._audit_originals).expanduser()
        exports = Path(self._audit_exports).expanduser()
        if not self._audit_originals or not originals.is_dir():
            self.alerts.info('Audit exports', 'Choose the folder that holds the original images.')
            return
        if not self._audit_exports or not exports.is_dir():
            self.alerts.info('Audit exports', 'Choose the folder that holds the exported PNGs.')
            return
        files = sorted(exports.glob('*.png'))
        if not files:
            self.alerts.info('Audit exports', 'No PNG exports found in the selected folder.')
            return
        if self._audit_use_patterns and not self._audit_run_ocr:
            self.alerts.info('Audit exports', 'Pattern checks need the OCR option.')
            return
        patterns = ()
        if self._audit_use_patterns:
            try:
                patterns = enabled_blocked_patterns(preferences_path())
            except (OSError, PreferencesError):
                self.alerts.error('Audit unavailable', 'No readable app settings found.')
                return
            if not patterns:
                self.alerts.info('Audit exports', 'Add or enable a blocked pattern first.')
                return
        self._audit_results = []
        self._audit_summary = ''
        self._audit_has_run = True
        self._audit_running = True
        self.auditChanged.emit()
        run_ocr = self._audit_run_ocr
        cancel = Event()
        copies = ExportCopies(self.session.preferences)

        def operation(path):
            return copies.verify(path, originals, patterns=patterns, run_ocr=run_ocr)

        def accept(index, result, error):
            if error:
                result = {
                    'export': files[index].name,
                    'outside_pixels_unchanged': None,
                    'logged_boxes': 0,
                    'wide_boxes': 0,
                    'masked_percent': 0.0,
                    'issue': error,
                }
            self._audit_results.append(result)
            self.auditChanged.emit()

        def finish():
            self._audit_running = False
            self._audit_summary = self._audit_summary_text()
            self.auditChanged.emit()
            self.alerts.set_status(self._audit_summary)
            return self._audit_summary

        started = self.session.jobs.run(
            'Auditing exports', files, operation, accept, finish,
            cancel=cancel, workers=1, report_failures=False,
        )
        if not started:
            self._audit_running = False
            self.auditChanged.emit()

    @Slot()
    def cancelAudit(self):
        if self._audit_running:
            self.session.jobs.cancel()

    @Slot()
    def saveAuditReport(self):
        if not self._audit_has_run or not self._audit_results:
            self.alerts.info('Save audit report', 'Run an audit first.')
            return
        suggested = str(Path.home() / 'markseal-audit.json')
        chosen, _ = QFileDialog.getSaveFileName(
            None, 'Save audit report', suggested, 'JSON report (*.json)'
        )
        if not chosen:
            return
        payload = {
            'originals': self._audit_originals,
            'exports': self._audit_exports,
            'run_ocr': self._audit_run_ocr,
            'use_patterns': self._audit_use_patterns,
            'summary': self._audit_summary,
            'files': self._audit_results,
        }
        try:
            Path(chosen).write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
        except OSError as error:
            self.alerts.error('Cannot save audit report', str(error))
            return
        self.alerts.set_status(f'Saved audit report to {chosen}')

    @Slot()
    def scanAll(self):
        self.start_scan(self.session.entries, follow=True)

    @Slot()
    def scanSelected(self):
        if self.session.jobs.busy:
            return
        selected = sorted(self.session.row_selection)
        if not selected:
            self.alerts.info('Scan selected',
                             'Select one or more images in the folder list first.')
            return
        self.start_scan([self.session.entries[index] for index in selected],
                        rescan=True, follow=True)

    @Slot()
    def rescanAll(self):
        if not self.session.jobs.busy and self.session.entries and self.alerts.ask(
                'Rescan all images?',
                'Keep existing boxes and add new suggestions. '
                'All rescanned images will need review again.'):
            self.start_scan(self.session.entries, rescan=True, follow=True)

    def start_scan(self, entries, rescan=False, *, follow=False, area=None):
        if self.session.jobs.busy:
            return
        self.session.store_active()
        plan = workflows.plan_scan(
            self.session.entries, entries, rescan=rescan, area=area
        )
        pending = plan.entries
        if not pending:
            self.alerts.info(
                'Folder scan',
                'Every image has been scanned or manually reviewed. '
                'Use Find likely identifiers to rescan an image.',
            )
            return
        try:
            scan = Scan(
                self.session.preferences,
                engine_factory=self.session.scan_engine,
            )
        except ScanError as error:
            if error.kind == 'unavailable':
                self.alerts.error(
                    'OCR unavailable', str(error), 'RETRY',
                    lambda: self.start_scan(
                        entries, rescan=rescan, follow=follow, area=area),
                )
            else:
                self.alerts.error(
                    'Invalid detection settings', str(error), 'OPEN SETTINGS',
                    self.session.facades.settings.requestSettings)
            return
        cancel = Event()
        processed = []
        area_completed = False
        review = self.session.facades.review

        def show_image(index):
            row = plan.rows[pending[index].path]
            self.session.facades.folder.activate_entry(int(row))

        def operation(job):
            path, stamp = job
            result = scan.file(path, stamp, cancel=cancel, area=area)
            return result.stamp, result.found, result.incomplete

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
            if (self.session.active is not None
                    and entry is self.session.entries[self.session.active]
                    and self.session.review.image is not None):
                if outcome.changed:
                    review.invalidate()
                    review.emit_view()
                detail = (f' Partial scan: {", ".join(outcome.incomplete)}.'
                          if outcome.incomplete else '')
                self.alerts.set_status(
                    f'{entry.path.name} · {outcome.count} new OCR suggestions.{detail} '
                    'Review before confirming.'
                )

        def track_result(index, result, error):
            accept(index, result, error)
            processed.append(pending[index])

        def finish():
            return workflows.scan_summary(
                processed, area=area, area_completed=area_completed
            )

        self.session.jobs.run(
            plan.label, list(plan.jobs), operation, track_result, finish,
            cancel=cancel, show_image=show_image if follow else None,
            metrics_settings=self.session.scan_metrics(), rows=plan.rows,
        )

    def scan_entry(self, entry, rescan=False, area=None):
        self.start_scan([entry], rescan=rescan, area=area)

    @Slot()
    def cancelScan(self):
        self.session.jobs.cancel()

    @Slot()
    def copyBoxesToFolder(self):
        if (self.session.jobs.busy or self.session.active is None
                or self.session.review.image is None):
            return
        boxes = self.session.review.selected_boxes()
        if not boxes:
            self.alerts.info('Copy selected boxes',
                             'Select or draw the boxes you want to copy first.')
            return
        targets = [entry for index, entry in enumerate(self.session.entries)
                   if index != self.session.active]
        if not targets:
            self.alerts.info('Copy selected boxes',
                             'Open a folder with at least two images.')
            return
        if not self.alerts.ask(
                'Copy selected boxes?',
                f'Copy {len(boxes)} selected box{"" if len(boxes) == 1 else "es"} '
                'to the same positions on other images of the same size? '
                'Check that the content lines up before confirming and saving.'):
            return
        size = self.session.review.image.size
        applied = skipped = unchanged = 0
        review = self.session.facades.review

        def operation(job):
            path, expected = job
            stamp = images.file_stamp(path)
            if expected is not None and stamp != expected:
                raise ValueError(
                    f'{path.name} changed. Reopen the folder before copying boxes.'
                )
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
            if (self.session.active is not None
                    and self.session.entries[self.session.active] is entry
                    and self.session.review.image is not None):
                review.invalidate()

        def finish():
            return (f'{applied} updated · {skipped} skipped (size or source changed) · '
                    f'{unchanged} already selected')

        self.session.jobs.run(
            'Copying boxes',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self.session.facades.folder.rows(),
        )

    def match_boxes_to_folder(self, anchor):
        try:
            from ..visual_anchor import locate_anchor, prepare_anchor, relocate_boxes
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
                'Anchor too small. Click Match boxes by visual anchor and drag around '
                'a larger area.'
            )
            return
        try:
            patch = prepare_anchor(self.session.review.image, anchor)
        except ValueError as error:
            self.alerts.set_status(str(error))
            return
        targets = [entry for index, entry in enumerate(self.session.entries)
                   if index != self.session.active]
        matched = skipped = 0
        review = self.session.facades.review

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
            if (changed and self.session.active is not None
                    and self.session.entries[self.session.active] is entry):
                review.invalidate()

        def finish():
            return f'{matched} matched · {skipped} skipped (no reliable placement)'

        self.session.jobs.run(
            'Matching visual anchor',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self.session.facades.folder.rows(),
        )

    @Slot()
    def confirmAll(self):
        if not self.session.jobs.busy and self.session.entries:
            self.confirm_entries(self.session.entries, 'Confirm all')

    def confirm_entries(self, entries, title):
        self.session.store_active()
        pending = workflows.eligible_for_confirmation(entries)
        if not pending:
            self.alerts.info(
                title,
                'No eligible images are awaiting confirmation. Check whether they are '
                'already reviewed, have no selected boxes, or have a scan error.',
            )
            return
        if not self.alerts.ask(
                title,
                workflows.confirmation_prompt(pending, self.session.preferences.method)):
            return
        for entry in pending:
            entry.confirm(True)
        self.session.facades.review.apply_confirmation()
        self.session.facades.folder.refresh_and_emit()
        count = len(pending)
        noun = 'image' if count == 1 else 'images'
        pronoun = 'it' if count == 1 else 'them'
        self.alerts.set_status(
            f'Confirmed {count} {noun}. Use Save reviewed to export {pronoun}.'
        )

    @Slot()
    def saveReviewed(self):
        if self.session.jobs.busy:
            return
        self.session.store_active()
        pending = [(index, entry) for index, entry in enumerate(self.session.entries)
                   if entry.reviewed and not entry.saved]
        if not pending:
            self.alerts.info('Save reviewed',
                             'Confirm the selection on each image you want to save.')
            return
        self.export_entries(pending)

    def save_active(self):
        entry = self.session.entries[self.session.active]
        self.export_entries([(self.session.active, entry)], individual=True)

    def export_entries(self, pending, individual=False):
        def choose(target):
            chosen, _ = QFileDialog.getSaveFileName(
                None, 'Save redacted copy', str(target), 'PNG image (*.png)'
            )
            return chosen or None

        def output_for(entry):
            watches = getattr(self.session.facades, 'watches', None)
            if watches is not None:
                directory_for = getattr(watches, 'output_for_source', None)
                if directory_for is not None:
                    directory = directory_for(entry.path)
                    if directory is not None:
                        return directory
            return self.session.output_directory

        copies = ExportCopies(self.session.preferences)
        try:
            plan = copies.plan(
                [CopyRequest.from_entry(entry) for _index, entry in pending],
                output_directory=output_for,
                choose=choose if individual else None,
            )
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            title = 'Cannot save image' if individual else 'Cannot save images'
            retry = self.save_active if individual else self.saveReviewed
            self.alerts.error(title, str(error), 'RETRY', retry)
            return
        if plan is None:
            return
        unredacted = plan.unredacted
        if unredacted and not self.alerts.ask(
                'Save unredacted copies?',
                f'{unredacted} reviewed image{"" if unredacted == 1 else "s"} '
                f'{"has" if unredacted == 1 else "have"} no selected boxes. '
                'Save them as unredacted PNG copies?'):
            return

        snapshots = [
            (planned.request.entry, copies.snapshot(planned))
            for planned in plan.jobs
        ]

        def operation(job):
            _entry, snapshot = job
            snapshot.target.parent.mkdir(parents=True, exist_ok=True)
            copies.write(snapshot, include_log=plan.include_log)

        def accept(index, result, error):
            planned = plan.jobs[index]
            entry = planned.request.entry
            target = planned.target
            snapshot = snapshots[index][1]
            if error:
                self.alerts.set_status(f'{entry.path.name} · {error}')
            elif export_succeeded(entry, snapshot):
                entry.mark_saved(target)
                entry.error = ''
                self.session.facades.review.last_export = target
                watches = getattr(self.session.facades, 'watches', None)
                if watches is not None:
                    watches.note_export(entry.path, target)
                self.alerts.set_status(f'Saved {target.name} to {target.parent}')

        self.session.jobs.run(
            'Saving', snapshots, operation, accept,
            metrics_settings={'method': self.session.preferences.method,
                              'coordinate_logs': plan.include_log},
            rows=self.session.facades.folder.rows(),
        )

    @Slot()
    def verifyReviewed(self):
        if self.session.jobs.busy:
            return
        self.session.store_active()
        saved = [entry for entry in self.session.entries
                 if entry.saved and entry.export_path is not None]
        copies = ExportCopies(self.session.preferences)
        files = []
        for entry in saved:
            target = entry.export_path
            if target.is_file():
                files.append(copies.verify(target, entry.path.parent))
        result = {
            'files': files,
            'all_ok': bool(files) and all(
                item['outside_pixels_unchanged'] and not item['issue'] for item in files),
        }
        self.last_verify = result
        self.verifyResult.emit(result)
        if not files:
            self.alerts.set_status(
                'No exported copies found to verify. Save reviewed images first.'
            )
        elif result['all_ok']:
            count = len(files)
            noun = 'export' if count == 1 else 'exports'
            self.alerts.set_status(
                f'Verified {count} {noun}: pixels outside redactions unchanged.'
            )
        else:
            problems = [
                f'{item["export"]}: '
                f'{item["issue"] or "pixels changed outside redactions"}'
                for item in files
                if item['issue'] or not item['outside_pixels_unchanged']
            ]
            self.alerts.error('Verify failed', '; '.join(problems))
