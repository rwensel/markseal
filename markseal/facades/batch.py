"""Whole-folder scan, confirm, copy, match, and export workflows."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from ..export_copy import CopyRequest, ExportCopies, export_succeeded
from .batch_audit import BatchAudit
from .batch_scan import BatchScan
from .batch_tools import BatchTools


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
        self._audit_run = BatchAudit(self)
        self._scan = BatchScan(self)
        self._tools = BatchTools(self)

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
    def prepareAudit(self): self._audit_run.prepareAudit()

    @Slot()
    def chooseAuditOriginals(self): self._audit_run.chooseAuditOriginals()
    @Slot()
    def chooseAuditExports(self): self._audit_run.chooseAuditExports()

    @Slot()
    def startAudit(self): self._audit_run.startAudit()
    @Slot()
    def cancelAudit(self): self._audit_run.cancelAudit()
    @Slot()
    def saveAuditReport(self): self._audit_run.saveAuditReport()
    @Slot()
    def scanAll(self): self._scan.scanAll()
    @Slot()
    def scanSelected(self): self._scan.scanSelected()
    @Slot()
    def rescanAll(self): self._scan.rescanAll()
    def start_scan(self, entries, rescan=False, *, follow=False, area=None): self._scan.start_scan(entries, rescan, follow=follow, area=area)
    def scan_entry(self, entry, rescan=False, area=None): self._scan.scan_entry(entry, rescan, area)
    @Slot()
    def cancelScan(self): self._scan.cancelScan()
    @Slot()
    def copyBoxesToFolder(self): self._tools.copyBoxesToFolder()
    def match_boxes_to_folder(self, anchor): self._tools.match_boxes_to_folder(anchor)
    @Slot()
    def confirmAll(self): self._tools.confirmAll()
    def confirm_entries(self, entries, title): self._tools.confirm_entries(entries, title)
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
