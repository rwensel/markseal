"""Batch facade: scans, confirm-all, copy, and reviewed exports."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from markseal.boxset import BoxList
from markseal.controller import Controller
from tests.support import FakeEngine

TSV = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
       '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n')


class BatchFacadeTests(unittest.TestCase):
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
        self.controller.alerts.ask = lambda *args, **kwargs: True
        self.controller.alerts.info = lambda *args, **kwargs: None
        self.errors = []
        self.controller.alerts.error = (
            lambda title, text='', *args, **kwargs: self.errors.append((title, text))
        )

    def make_folder(self, count=2, size=(60, 40)):
        source = self.root / 'images'
        source.mkdir(exist_ok=True)
        for index in range(count):
            Image.new('RGB', size, 'white').save(source / f'{index}.png')
        return source

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
        self.assertFalse(self.batch.busy, 'batch job did not finish')

    def test_facade_exposes_the_batch_surface(self):
        for name in ('busy', 'busyLabel', 'canCancel', 'progressText',
                     'progressValue', 'progressMax', 'progressDetail',
                     'progressCurrent', 'scanStage'):
            self.assertTrue(hasattr(self.batch, name), name)
        for name in ('scanAll', 'scanSelected', 'rescanAll', 'cancelScan',
                     'copyBoxesToFolder', 'confirmAll', 'saveReviewed', 'verifyReviewed'):
            self.assertTrue(hasattr(self.batch, name), name)
        self.assertFalse(hasattr(self.controller, 'scanAll'))
        self.assertFalse(hasattr(self.controller, 'busy'))

    def test_verify_reviewed_reports_saved_exports(self):
        self.controller.folder.open_path(self.make_folder())
        for entry in self.controller.session.entries:
            entry.boxes = BoxList([(5, 5, 20, 20)])
            entry.selected = {0}
        self.batch.confirmAll()
        self.batch.saveReviewed()
        self.wait_for_batch()
        self.assertEqual(self.errors, [])
        self.assertTrue(all(entry.saved for entry in self.controller.session.entries))
        signals = []
        self.batch.verifyResult.connect(lambda result: signals.append(result))
        self.batch.verifyReviewed()
        self.assertTrue(self.batch.last_verify['all_ok'])
        self.assertEqual(len(self.batch.last_verify['files']), 2)
        self.assertEqual(len(signals), 1)

    def test_scan_all_reports_progress_and_boxes(self):
        self.controller.folder.open_path(self.make_folder())
        progress = []
        self.batch.progressChanged.connect(
            lambda: progress.append((self.batch.progressValue, self.batch.progressMax))
        )
        engine = FakeEngine(tsv=TSV)
        with patch.object(self.controller.session, 'scan_engine', return_value=engine):
            self.batch.scanAll()
            self.wait_for_batch()

        self.assertEqual(self.errors, [])
        self.assertTrue(all(entry.scanned for entry in self.controller.session.entries))
        self.assertTrue(all(entry.boxes for entry in self.controller.session.entries))
        self.assertTrue(self.batch.canCancel is False)
        self.assertEqual(self.batch.progressValue, 2)
        self.assertEqual(self.batch.progressMax, 2)
        self.assertIn((2, 2), progress)
        model = self.controller.folder.folderModel
        self.assertEqual(model.data(model.index(0), model.JobStateRole), '')

    def test_confirm_all_marks_entries_reviewed(self):
        self.controller.folder.open_path(self.make_folder())
        for entry in self.controller.session.entries:
            entry.boxes = BoxList([(5, 5, 20, 20)])
            entry.selected = {0}
        self.batch.confirmAll()
        self.assertTrue(all(entry.reviewed for entry in self.controller.session.entries))
        self.assertEqual(self.controller.folder.reviewedCount, 2)

    def test_copy_boxes_reaches_matching_images(self):
        self.controller.folder.open_path(self.make_folder())
        active = self.controller.session.entries[0]
        active.boxes = BoxList([(5, 5, 20, 20)])
        active.selected = {0}
        self.batch.copyBoxesToFolder()
        self.wait_for_batch()
        self.assertEqual(self.controller.session.entries[1].boxes, [(5, 5, 20, 20)])
        self.assertIn('updated', self.batch.progressText + self.batch.progressDetail)

    def test_save_reviewed_exports_every_reviewed_image(self):
        self.controller.folder.open_path(self.make_folder())
        self.controller.session.output_directory = self.root / 'out'
        for entry in self.controller.session.entries:
            entry.selected = {0}
            entry.boxes = BoxList([(5, 5, 20, 20)])
            entry.reviewed = True
        self.controller.session.review.confirmed = True
        self.batch.saveReviewed()
        self.wait_for_batch()

        self.assertEqual(self.errors, [])
        self.assertTrue((self.root / 'out' / '0_redacted.png').is_file())
        self.assertTrue((self.root / 'out' / '1_redacted.png').is_file())
        self.assertTrue(all(entry.saved for entry in self.controller.session.entries))

    def test_cancel_without_a_running_batch_is_harmless(self):
        self.batch.cancelScan()
        self.assertFalse(self.batch.busy)


if __name__ == '__main__':
    unittest.main()
