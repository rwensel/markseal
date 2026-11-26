"""Whole-folder scan, confirm, copy, match, and export workflows."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from .batch_audit import BatchAudit
from .batch_scan import BatchScan
from .batch_export import BatchExport
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
        self._export = BatchExport(self)

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
        self._audit_run.prepareAudit()

    @Slot()
    def chooseAuditOriginals(self):
        self._audit_run.chooseAuditOriginals()

    @Slot()
    def chooseAuditExports(self):
        self._audit_run.chooseAuditExports()

    @Slot()
    def startAudit(self):
        self._audit_run.startAudit()

    @Slot()
    def cancelAudit(self):
        self._audit_run.cancelAudit()

    @Slot()
    def saveAuditReport(self):
        self._audit_run.saveAuditReport()

    @Slot()
    def scanAll(self):
        self._scan.scanAll()

    @Slot()
    def scanSelected(self):
        self._scan.scanSelected()

    @Slot()
    def rescanAll(self):
        self._scan.rescanAll()

    def start_scan(self, entries, rescan=False, *, follow=False, area=None):
        self._scan.start_scan(entries, rescan, follow=follow, area=area)

    def scan_entry(self, entry, rescan=False, area=None):
        self._scan.scan_entry(entry, rescan, area)

    @Slot()
    def cancelScan(self):
        self._scan.cancelScan()

    @Slot()
    def copyBoxesToFolder(self):
        self._tools.copyBoxesToFolder()

    def match_boxes_to_folder(self, anchor):
        self._tools.match_boxes_to_folder(anchor)

    @Slot()
    def confirmAll(self):
        self._tools.confirmAll()

    def confirm_entries(self, entries, title):
        self._tools.confirm_entries(entries, title)

    @Slot()
    def saveReviewed(self):
        self._export.saveReviewed()

    def save_active(self):
        self._export.save_active()

    def export_entries(self, pending, individual=False):
        self._export.export_entries(pending, individual)

    @Slot()
    def verifyReviewed(self):
        self._export.verifyReviewed()
