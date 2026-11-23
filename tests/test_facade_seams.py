"""Alert forwarding and the job center's poll/finish path."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from markseal.controller import Controller


class SeamTests(unittest.TestCase):
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

    def test_alert_changes_reach_the_root_properties(self):
        statuses = []
        errors = []
        self.controller.statusChanged.connect(lambda: statuses.append(self.controller.statusText))
        self.controller.errorChanged.connect(
            lambda: errors.append((self.controller.errorText, self.controller.errorDetail))
        )

        self.controller.alerts.set_status('Scanning image')
        self.controller.alerts.error('Cannot open image', 'Missing file', 'RETRY', None)

        self.assertEqual(self.controller.statusText, 'Scanning image')
        self.assertEqual(statuses, ['Scanning image'])
        self.assertEqual(self.controller.errorActionText, 'RETRY')
        self.assertEqual(errors, [('Cannot open image', 'Missing file')])

        self.controller.dismissError()
        self.assertEqual(self.controller.errorText, '')
        self.assertEqual(self.controller.errorDetail, '')

    def test_job_center_finishes_a_batch_and_reports_progress(self):
        accepted = []
        rows = []
        jobs = [Path('a.png'), Path('b.png'), Path('c.png')]
        self.controller.jobs.jobStatesQueued.connect(lambda states: rows.append(sorted(states)))
        self.controller.jobs.run(
            'Test batch', jobs,
            lambda job: job.name,
            lambda index, result, error: accepted.append(result),
            rows={path: index for index, path in enumerate(jobs)},
        )
        self.assertTrue(self.controller.jobs.busy)
        self.assertTrue(self.controller.jobs._runner.wait(5))
        self.controller.jobs._poll()

        self.assertFalse(self.controller.jobs.busy)
        self.assertEqual(sorted(accepted), ['a.png', 'b.png', 'c.png'])
        self.assertEqual(self.controller.jobs.progressValue, 3)
        self.assertEqual(self.controller.jobs.progressMax, 3)
        self.assertEqual(rows, [[0, 1, 2]])

    def test_manual_busy_round_trip_emits_once_per_change(self):
        changes = []
        self.controller.jobs.busyChanged.connect(lambda: changes.append(self.controller.jobs.busy))
        self.controller.jobs.begin_manual('Saving copy')
        self.assertEqual(self.controller.batch.busyLabel, 'Saving copy')
        self.controller.jobs.end_manual()
        self.assertEqual(changes, [True, False])
        self.assertEqual(self.controller.batch.busyLabel, '')

    def test_moved_state_is_reachable_through_the_session(self):
        self.assertEqual(self.controller.session.entries, [])
        self.assertIs(self.controller.session.review.path, None)
        self.assertEqual(self.controller.session.parallel_limit,
                         self.controller.session.parallel_limit)


if __name__ == '__main__':
    unittest.main()
