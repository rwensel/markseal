"""The updates facade state and its setting gate."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from markseal import updates
from markseal.controller import Controller


class UpdateFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.controller = Controller(
            preferences_file=Path(self.temporary.name) / 'settings.json')
        self.addCleanup(self.controller.deleteLater)
        self.updates = self.controller.updates

    def test_found_update_sets_state_and_dismiss_clears_it(self):
        self.updates._found(updates.UpdateInfo('2.1.0', 'notes', 'page', 'dl', 'sha'))
        self.assertTrue(self.updates.hasUpdate)
        self.assertEqual(self.updates.updateInfo['version'], '2.1.0')
        self.updates.dismiss()
        self.assertFalse(self.updates.hasUpdate)
        self.assertEqual(self.updates.updateInfo, {})

    def test_check_is_gated_by_the_setting(self):
        self.controller.session.preferences.check_for_updates = False
        self.updates.check()
        self.assertFalse(self.updates.busy)

    def test_check_reports_an_available_update(self):
        info = updates.UpdateInfo('2.1.0', 'notes', 'page', 'dl', 'sha')
        self.controller.session.preferences.check_for_updates = True
        with patch('markseal.updates.check_for_update', return_value=info):
            self.updates.check()
            QThreadPool.globalInstance().waitForDone(5000)
            self.app.processEvents()
        self.assertTrue(self.updates.hasUpdate)
        self.assertEqual(self.updates.updateInfo['version'], '2.1.0')

    def test_found_sets_a_status_line(self):
        self.updates._found(updates.UpdateInfo('2.1.0', 'notes', 'page', 'dl', 'sha'))
        self.assertIn('2.1.0', self.updates.status)

    def test_progress_updates_the_status_line(self):
        self.updates._info = updates.UpdateInfo('2.1.0', '', '', 'dl', 'sha')
        self.updates._progress_update(0.42)
        self.assertAlmostEqual(self.updates.progress, 0.42)
        self.assertIn('42%', self.updates.status)

    def test_downloaded_marks_ready_to_install(self):
        self.updates._downloaded(Path('installer.exe'))
        self.assertTrue(self.updates.readyToInstall)
        self.assertIn('install', self.updates.status.lower())

    def test_failure_reaches_the_status_line(self):
        self.updates._failed('network down')
        self.assertEqual(self.updates.errorText, 'network down')
        self.assertIn('network down', self.updates.status)
        self.assertIn('network down', self.controller.alerts.status_text)

    def test_dismiss_clears_status_and_progress(self):
        self.updates._found(updates.UpdateInfo('2.1.0', '', '', 'dl', 'sha'))
        self.updates._progress_update(0.5)
        self.updates.dismiss()
        self.assertEqual(self.updates.status, '')
        self.assertEqual(self.updates.progress, 0.0)
        self.assertFalse(self.updates.hasUpdate)


if __name__ == '__main__':
    unittest.main()
