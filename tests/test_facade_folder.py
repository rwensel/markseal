"""Folder facade: model roles, row selection, and shared box sets."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from markseal.controller import Controller
from markseal.ui.models import FolderModel


class FolderFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.controller = Controller(preferences_file=self.root / 'settings.json')
        self.addCleanup(self.controller.deleteLater)
        self.controller.alerts.ask = lambda *args, **kwargs: True
        self.controller.alerts.info = lambda *args, **kwargs: None
        self.folder = self.controller.folder

    def make_folder(self, names=('a.png', 'b.png')):
        source = self.root / 'images'
        source.mkdir(exist_ok=True)
        for name in names:
            Image.new('RGB', (60, 40), 'white').save(source / name)
        return source

    def test_facade_exposes_the_folder_surface(self):
        for name in ('folderMode', 'folderName', 'folderCounts', 'reviewedCount',
                     'folderImageCount', 'folderModel'):
            self.assertTrue(hasattr(self.folder, name), name)
        self.assertTrue(hasattr(self.folder, 'selectRow'))
        self.assertFalse(hasattr(self.controller, 'folderMode'))
        self.assertIsInstance(self.folder.folderModel, FolderModel)

    def test_open_path_fills_the_model_and_activates_the_first_row(self):
        source = self.make_folder()
        self.folder.open_path(source)
        self.assertTrue(self.folder.folderMode)
        self.assertEqual(self.folder.folderName, 'images')
        self.assertEqual(self.folder.folderImageCount, 2)
        self.assertEqual(self.folder.folderModel.rowCount(), 2)
        model = self.folder.folderModel
        self.assertTrue(model.data(model.index(0), FolderModel.ActiveRole))
        self.assertTrue(model.data(model.index(0), FolderModel.SelectedRole))
        self.assertEqual(model.data(model.index(0), FolderModel.NameRole), 'a.png')
        self.assertIs(self.controller.session.review.boxset,
                      self.controller.session.entries[0].boxset)

    def test_select_row_control_shift_and_scroll(self):
        self.folder.open_path(self.make_folder())
        scrolled = []
        self.folder.scrollRequested.connect(scrolled.append)

        self.folder.selectRow(1, False, False)
        self.assertEqual(self.controller.session.row_selection, {1})
        self.assertEqual(self.controller.session.active, 1)
        self.assertEqual(scrolled, [1])
        model = self.folder.folderModel
        self.assertTrue(model.data(model.index(1), FolderModel.ActiveRole))

        self.folder.selectRow(0, True, False)
        self.assertEqual(self.controller.session.row_selection, {0, 1})
        self.folder.selectRow(1, True, False)
        self.assertEqual(self.controller.session.row_selection, {0})

        self.folder.selectRow(0, False, True)
        self.assertEqual(self.controller.session.row_selection, {0, 1})

    def test_selection_change_updates_the_confirm_label(self):
        self.folder.open_path(self.make_folder())
        labels = []
        self.controller.review.confirmLabelChanged.connect(
            lambda: labels.append(self.controller.review.confirmLabel)
        )
        self.folder.selectRow(0, False, False)
        self.folder.selectRow(1, True, False)
        self.assertEqual(labels[-1], 'CONFIRM 2')
        self.folder.selectRow(0, True, False)
        self.assertEqual(labels[-1], 'CONFIRM')

    def test_switching_rows_borrows_each_entry_box_set(self):
        self.folder.open_path(self.make_folder())
        first = self.controller.session.entries[0]
        second = self.controller.session.entries[1]
        self.controller.session.review.add_suggestions([(5, 5, 20, 20)])
        self.assertEqual(first.boxes, [(5, 5, 20, 20)])

        self.folder.selectRow(1, False, False)
        self.assertIs(self.controller.session.review.boxset, second.boxset)
        self.assertEqual(second.boxes, [])
        self.assertEqual(first.boxes, [(5, 5, 20, 20)])

        self.folder.selectRow(0, False, False)
        self.assertIs(self.controller.session.review.boxset, first.boxset)
        self.assertEqual(self.controller.session.review.boxes, [(5, 5, 20, 20)])

    def test_clear_resets_the_folder_state(self):
        self.folder.open_path(self.make_folder())
        self.folder.clear()
        self.assertEqual(self.controller.session.entries, [])
        self.assertEqual(self.folder.folderModel.rowCount(), 0)
        self.assertFalse(self.folder.folderMode)

    def test_appended_rows_keep_selection_and_active_row(self):
        source = self.make_folder()
        self.folder.open_path(source)
        Image.new('RGB', (60, 40), 'white').save(source / 'c.png')
        self.controller.session.row_selection = {0}
        added = self.folder.add_paths([source / 'c.png'])
        self.assertEqual(len(added), 1)
        self.assertEqual(self.folder.folderModel.rowCount(), 3)
        self.assertEqual(self.controller.session.row_selection, {0})
        self.assertEqual(self.controller.session.active, 0)
        model = self.folder.folderModel
        self.assertEqual(model.data(model.index(2), FolderModel.NameRole), 'c.png')
        self.assertFalse(model.data(model.index(2), FolderModel.ActiveRole))

    def test_watched_output_wins_over_the_global_override(self):
        session = self.controller.session
        watched = self.root / 'watched'
        session.facades.watches = type('Stub', (), {
            'output_for': lambda self, folder: watched,
            'note_export': lambda self, path, target: None,
        })()
        session.output_directory_override = self.root / 'global'
        self.assertEqual(
            session.output_directory_for(self.root / 'images'), watched)
        session.facades.watches = None
        self.assertEqual(
            session.output_directory_for(self.root / 'images'),
            self.root / 'global')


if __name__ == '__main__':
    unittest.main()
