import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from markseal import export
from markseal.controller import Controller


class AuditFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.controller = Controller(preferences_file=self.root / 'settings.json')
        self.addCleanup(self.controller.deleteLater)
        self.batch = self.controller.batch
        self.controller.alerts.info = lambda *args, **kwargs: None
        self.errors = []
        self.controller.alerts.error = (
            lambda title, text='', *args, **kwargs: self.errors.append((title, text))
        )

    def make_export(self, name='a', include_log=True):
        originals = self.root / 'originals'
        exports = self.root / 'exports'
        originals.mkdir(exist_ok=True)
        exports.mkdir(exist_ok=True)
        source = originals / f'{name}.png'
        target = exports / f'{name}_redacted.png'
        Image.new('RGB', (80, 60), 'white').save(source)
        image = Image.new('RGB', (80, 60), 'white')
        job = export.snapshot(source, target, [(10, 10, 30, 30)], frozenset([0]),
                              'Pixelate', image=image)
        export.write_copy(job, include_log=include_log)
        return originals, exports, target

    def wait_for_batch(self, timeout_ms=10000):
        if not self.batch.busy:
            return
        loop = QEventLoop()

        def finished():
            if not self.batch.busy:
                loop.quit()

        self.batch.busyChanged.connect(finished)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()
        self.batch.busyChanged.disconnect(finished)
        self.assertFalse(self.batch.busy, 'audit batch did not finish')

    def test_audit_surface_is_exposed_on_batch(self):
        for name in ('auditOriginals', 'auditExports', 'auditRunOcr', 'auditUsePatterns',
                     'auditResults', 'auditSummary', 'auditHasRun', 'auditRunning'):
            self.assertTrue(hasattr(self.batch, name), name)
        for name in ('chooseAuditOriginals', 'chooseAuditExports', 'prepareAudit',
                     'setAuditOriginals', 'setAuditExports', 'setAuditRunOcr',
                     'setAuditUsePatterns', 'startAudit', 'cancelAudit',
                     'saveAuditReport'):
            self.assertTrue(hasattr(self.batch, name), name)

    def test_audit_reports_a_clean_export(self):
        originals, exports, _ = self.make_export()
        self.batch.setAuditOriginals(str(originals))
        self.batch.setAuditExports(str(exports))
        self.batch.startAudit()
        self.wait_for_batch()

        self.assertEqual(self.errors, [])
        self.assertTrue(self.batch.auditHasRun)
        self.assertFalse(self.batch.auditRunning)
        self.assertEqual(len(self.batch.auditResults), 1)
        result = self.batch.auditResults[0]
        self.assertEqual(result['export'], 'a_redacted.png')
        self.assertEqual(result['issue'], None)
        self.assertTrue(result['outside_pixels_unchanged'])
        self.assertIn('1 export', self.batch.auditSummary)

    def test_audit_reports_a_missing_coordinate_log(self):
        originals, exports, target = self.make_export(include_log=False)
        self.batch.setAuditOriginals(str(originals))
        self.batch.setAuditExports(str(exports))
        self.batch.startAudit()
        self.wait_for_batch()

        self.assertEqual(self.errors, [])
        self.assertEqual(len(self.batch.auditResults), 1)
        self.assertIn('coordinate log missing', self.batch.auditResults[0]['issue'])

    def test_patterns_are_cleared_when_ocr_is_off(self):
        self.batch.setAuditRunOcr(True)
        self.batch.setAuditUsePatterns(True)
        self.assertTrue(self.batch.auditUsePatterns)
        self.batch.setAuditRunOcr(False)
        self.assertFalse(self.batch.auditUsePatterns)

    def test_audit_report_is_json(self):
        originals, exports, _ = self.make_export()
        self.batch.setAuditOriginals(str(originals))
        self.batch.setAuditExports(str(exports))
        self.batch.startAudit()
        self.wait_for_batch()
        report = self.root / 'audit.json'
        with patch('markseal.facades.batch_audit.QFileDialog.getSaveFileName',
                   return_value=(str(report), 'JSON report (*.json)')):
            self.batch.saveAuditReport()
        self.assertTrue(report.is_file())
        data = json.loads(report.read_text(encoding='utf-8'))
        self.assertEqual(data['originals'], str(originals))
        self.assertEqual(data['exports'], str(exports))
        self.assertEqual(len(data['files']), 1)
        self.assertIn('summary', data)


if __name__ == '__main__':
    unittest.main()
