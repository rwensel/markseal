"""Review facade: counts, confirmation, and the shared BoxSet."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from PIL import Image
from PySide6.QtWidgets import QApplication

from markseal.boxset import FolderImage
from markseal.controller import Controller


class RecordingBatch:
    def __init__(self):
        self.calls = []

    def scan_entry(self, entry, rescan=False, area=None):
        self.calls.append(('scan_entry', entry, rescan, area))

    def match_boxes_to_folder(self, anchor):
        self.calls.append(('match_boxes_to_folder', anchor))

    def confirm_entries(self, entries, title):
        self.calls.append(('confirm_entries', entries, title))

    def save_active(self):
        self.calls.append(('save_active',))


class ReviewFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.controller = Controller(
            preferences_file=Path(self.temporary.name) / 'settings.json'
        )
        self.addCleanup(self.controller.deleteLater)
        self.review = self.controller.review
        self.batch = RecordingBatch()
        self.review.batch = self.batch
        self.controller.alerts.ask = lambda *args, **kwargs: True
        self.controller.alerts.info = lambda *args, **kwargs: None
        self.errors = []
        self.controller.alerts.error = (
            lambda title, text='', *args, **kwargs: self.errors.append((title, text))
        )

    def open_image(self):
        path = Path(self.temporary.name) / 'screen.png'
        Image.new('RGB', (200, 100), 'white').save(path)
        self.review.load_image(Image.new('RGB', (200, 100), 'white'), path)
        return path

    def test_facade_exposes_the_review_surface(self):
        for name in ('hasImage', 'imageName', 'imageSizeText', 'imageRevision',
                     'imageWidth', 'imageHeight', 'boxes', 'selectedCount',
                     'excludedCount', 'totalBoxes', 'confirmed', 'confirmLabel',
                     'viewScale', 'viewOffsetX', 'viewOffsetY', 'panning',
                     'dragActive', 'captureMode'):
            self.assertTrue(hasattr(self.review, name), name)
        for name in ('setViewSize', 'press', 'move', 'release', 'zoomAt', 'zoomStep',
                     'zoomFit', 'panStep', 'selectAllBoxes', 'selectNoBoxes',
                     'beginPan', 'movePan', 'endPan', 'toggleBox', 'removeBox', 'undo',
                     'editBoxes', 'clearBoxes', 'confirmSelection', 'redactAll',
                     'cancelCapture',
                     'find', 'beginScanArea', 'beginAnchorCapture',
                     'beginLearnPattern', 'copyRedacted', 'save', 'verifyCurrent'):
            self.assertTrue(hasattr(self.review, name), name)
        self.assertFalse(hasattr(self.controller, 'totalBoxes'))
        self.assertFalse(hasattr(self.controller, 'confirmSelection'))

    def test_verify_current_reports_the_last_export(self):
        self.open_image()
        self.controller.session.review.boxes = [(10, 10, 30, 30)]
        self.controller.session.review.selected = {0}
        self.controller.session.review.confirmed = True
        target = Path(self.temporary.name) / 'screen_redacted.png'
        with patch('markseal.facades.review.QFileDialog.getSaveFileName',
                   return_value=(str(target), 'PNG image (*.png)')):
            self.review.save_single()
        self.assertTrue(target.is_file())
        self.assertEqual(self.review.last_export, target)
        signals = []
        self.review.verifyResult.connect(lambda result: signals.append(result))
        self.review.verifyCurrent()
        self.assertEqual(self.errors, [])
        self.assertIsNone(self.review.last_verify['issue'])
        self.assertTrue(self.review.last_verify['outside_pixels_unchanged'])
        self.assertEqual(len(signals), 1)

    def test_counts_follow_the_box_set(self):
        self.open_image()
        self.controller.session.review.boxes = [(0, 0, 10, 10), (20, 20, 40, 40)]
        self.controller.session.review.selected = {0, 1}
        self.review.reviewChanged.emit()
        self.assertEqual(self.review.totalBoxes, 2)
        self.assertEqual(self.review.selectedCount, 2)
        self.assertEqual(self.review.excludedCount, 0)
        self.review.toggleBox(0)
        self.assertEqual(self.review.selectedCount, 1)
        self.assertEqual(self.review.excludedCount, 1)
        self.assertFalse(self.review.confirmed)

    def test_box_edits_do_not_reload_the_unconfirmed_display(self):
        self.open_image()
        self.controller.session.review.boxes = [(0, 0, 10, 10)]
        self.controller.session.review.selected = {0}
        revision = self.review.imageRevision
        self.review.toggleBox(0)
        self.review.removeBox(0)
        self.assertEqual(self.review.imageRevision, revision)

    def test_box_edits_invalidate_the_last_export(self):
        self.open_image()
        self.review.last_export = Path('saved.png')
        self.controller.session.review.boxes = [(0, 0, 10, 10)]
        self.controller.session.review.selected = {0}
        self.review.toggleBox(0)
        self.assertIsNone(self.review.last_export)

    def test_undo_after_confirmation_reloads_the_display(self):
        self.open_image()
        self.controller.session.review.boxset.add((0, 0, 10, 10))
        self.controller.session.review.confirmed = True
        revision = self.review.imageRevision
        self.review.undo()
        self.assertFalse(self.review.confirmed)
        self.assertEqual(self.review.imageRevision, revision + 1)

    def test_adopt_entry_borrows_the_folder_box_set(self):
        entry = FolderImage(Path('shared.png'))
        self.review.adopt_entry(entry)
        self.assertIs(self.controller.session.review.boxset, entry.boxset)
        self.controller.session.review.add_suggestions([(5, 5, 15, 15)])
        self.assertEqual(entry.boxes, [(5, 5, 15, 15)])
        self.assertEqual(entry.selected, {0})

    def test_confirm_label_tracks_row_selection(self):
        labels = []
        self.review.confirmLabelChanged.connect(lambda: labels.append(self.review.confirmLabel))
        self.controller.session.entries = [FolderImage(Path('a.png')), FolderImage(Path('b.png'))]
        self.controller.session.row_selection = {0, 1}
        self.review.selection_changed()
        self.assertEqual(labels, ['CONFIRM 2'])
        self.controller.session.row_selection = {0}
        self.review.selection_changed()
        self.assertEqual(labels, ['CONFIRM 2', 'CONFIRM'])

    def test_multi_row_confirmation_delegates_to_batch(self):
        self.open_image()
        entries = [FolderImage(Path('a.png')), FolderImage(Path('b.png'))]
        self.controller.session.entries = entries
        self.controller.session.row_selection = {0, 1}
        self.review.confirmSelection()
        self.assertEqual(self.batch.calls,
                         [('confirm_entries', entries, 'Confirm selected images')])

    def test_redact_all_selects_and_confirms_every_box(self):
        self.open_image()
        self.controller.session.review.boxes = [(10, 10, 20, 20), (30, 30, 40, 40)]
        self.controller.session.review.selected = {1}
        self.controller.session.review.confirmed = False
        self.review.redactAll()
        self.assertEqual(self.controller.session.review.selected, {0, 1})
        self.assertTrue(self.controller.session.review.confirmed)

    def test_folder_find_and_save_delegate_to_batch(self):
        self.open_image()
        entry = FolderImage(Path('a.png'))
        self.controller.session.entries = [entry]
        self.controller.session.active = 0
        self.review.find()
        self.assertEqual(self.batch.calls, [('scan_entry', entry, True, None)])

        entry.reviewed = True
        self.controller.session.review.confirmed = True
        self.review.save()
        self.assertEqual(self.batch.calls[-1], ('save_active',))

    def test_capture_mode_round_trip(self):
        self.open_image()
        self.review.beginScanArea()
        self.assertEqual(self.review.captureMode, 'area')
        self.review.cancelCapture()
        self.assertEqual(self.review.captureMode, 'none')

    def test_invalidate_clears_confirmation_and_bumps_the_revision(self):
        self.open_image()
        self.controller.session.review.confirmed = True
        revision = self.review.imageRevision
        self.review.invalidate()
        self.assertFalse(self.review.confirmed)
        self.assertEqual(self.review.imageRevision, revision + 1)


if __name__ == '__main__':
    unittest.main()
