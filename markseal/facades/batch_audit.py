import json
from pathlib import Path
from threading import Event

from PySide6.QtWidgets import QFileDialog

from ..export_copy import ExportCopies
from ..preferences import PreferencesError, enabled_blocked_patterns, preferences_path


class BatchAudit:
    def __init__(self, owner):
        self.owner = owner

    def prepareAudit(self):
        owner = self.owner
        if not owner._audit_originals and owner.session.folder:
            owner._audit_originals = str(owner.session.folder)
        if not owner._audit_exports:
            saved = next((entry.export_path for entry in owner.session.entries
                          if entry.saved and entry.export_path is not None), None)
            if saved is not None:
                owner._audit_exports = str(saved.parent)
            elif owner._audit_originals:
                candidate = Path(owner._audit_originals) / 'redacted'
                if candidate.is_dir():
                    owner._audit_exports = str(candidate)
        owner.auditChanged.emit()

    def _choose_audit_folder(self, title, current):
        owner = self.owner
        path = QFileDialog.getExistingDirectory(None, title, current or '')
        return path or ''

    def chooseAuditOriginals(self):
        owner = self.owner
        path = self._choose_audit_folder('Select originals folder', owner._audit_originals)
        if path:
            owner.setAuditOriginals(path)

    def chooseAuditExports(self):
        owner = self.owner
        path = self._choose_audit_folder('Select export folder', owner._audit_exports)
        if path:
            owner.setAuditExports(path)

    def _audit_summary_text(self):
        owner = self.owner
        total = len(owner._audit_results)
        issues = sum(1 for item in owner._audit_results
                     if item.get('issue') or item.get('outside_pixels_unchanged') is False)
        wide = sum(int(item.get('wide_boxes') or 0) for item in owner._audit_results)
        clean = total - issues
        noun = 'export' if total == 1 else 'exports'
        issue_noun = 'issue' if issues == 1 else 'issues'
        box_noun = 'box' if wide == 1 else 'boxes'
        return f'{total} {noun} · {clean} clean · {issues} {issue_noun} · {wide} wide {box_noun}'

    def startAudit(self):
        owner = self.owner
        if owner.session.jobs.busy or owner._audit_running:
            return
        originals = Path(owner._audit_originals).expanduser()
        exports = Path(owner._audit_exports).expanduser()
        if not owner._audit_originals or not originals.is_dir():
            owner.alerts.info('Audit exports', 'Choose the folder that holds the original images.')
            return
        if not owner._audit_exports or not exports.is_dir():
            owner.alerts.info('Audit exports', 'Choose the folder that holds the exported PNGs.')
            return
        files = sorted(exports.glob('*.png'))
        if not files:
            owner.alerts.info('Audit exports', 'No PNG exports found in the selected folder.')
            return
        if owner._audit_use_patterns and not owner._audit_run_ocr:
            owner.alerts.info('Audit exports', 'Pattern checks need the OCR option.')
            return
        patterns = ()
        if owner._audit_use_patterns:
            try:
                patterns = enabled_blocked_patterns(preferences_path())
            except (OSError, PreferencesError):
                owner.alerts.error('Audit unavailable', 'No readable app settings found.')
                return
            if not patterns:
                owner.alerts.info('Audit exports', 'Add or enable a blocked pattern first.')
                return
        owner._audit_results = []
        owner._audit_summary = ''
        owner._audit_has_run = True
        owner._audit_running = True
        owner.auditChanged.emit()
        run_ocr = owner._audit_run_ocr
        cancel = Event()
        copies = ExportCopies(owner.session.preferences)

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
            owner._audit_results.append(result)
            owner.auditChanged.emit()

        def finish():
            owner._audit_running = False
            owner._audit_summary = self._audit_summary_text()
            owner.auditChanged.emit()
            owner.alerts.set_status(owner._audit_summary)
            return owner._audit_summary

        started = owner.session.jobs.run(
            'Auditing exports', files, operation, accept, finish,
            cancel=cancel, workers=1, report_failures=False,
        )
        if not started:
            owner._audit_running = False
            owner.auditChanged.emit()

    def cancelAudit(self):
        owner = self.owner
        if owner._audit_running:
            owner.session.jobs.cancel()

    def saveAuditReport(self):
        owner = self.owner
        if not owner._audit_has_run or not owner._audit_results:
            owner.alerts.info('Save audit report', 'Run an audit first.')
            return
        suggested = str(Path.home() / 'markseal-audit.json')
        chosen, _ = QFileDialog.getSaveFileName(
            None, 'Save audit report', suggested, 'JSON report (*.json)'
        )
        if not chosen:
            return
        payload = {
            'originals': owner._audit_originals,
            'exports': owner._audit_exports,
            'run_ocr': owner._audit_run_ocr,
            'use_patterns': owner._audit_use_patterns,
            'summary': owner._audit_summary,
            'files': owner._audit_results,
        }
        try:
            Path(chosen).write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
        except OSError as error:
            owner.alerts.error('Cannot save audit report', str(error))
            return
        owner.alerts.set_status(f'Saved audit report to {chosen}')
