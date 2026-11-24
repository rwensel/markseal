"""Watched-folder facade: store, sweep, inbox counts, and manual intake."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from markseal.controller import Controller
from markseal import watches as watch_store
from tests.support import FakeEngine

TSV = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
       '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n')


class WatchFacadeTests(unittest.TestCase):
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
        self.controller.alerts.error = lambda *args, **kwargs: None
        self.watches = self.controller.watches
        self.folder = self.root / 'shots'
        self.folder.mkdir()
        self.controller.session.scan_engine = lambda: FakeEngine(TSV)

    def image(self, name, age=10, color='white'):
        path = self.folder / name
        Image.new('RGB', (120, 80), color).save(path)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def wait_for_jobs(self, timeout_ms=10000):
        loop = QEventLoop()
        self.controller.batch.busyChanged.connect(
            lambda: loop.quit() if not self.controller.batch.busy else None)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()

    def test_add_watch_baselines_and_lists_counts(self):
        self.image('old.png')
        self.watches.addWatch(str(self.folder))
        rows = self.watches.watchRows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['policy'], 'MANUAL')
        self.assertEqual((rows[0]['new'], rows[0]['existing']), (0, 1))
        self.assertEqual(rows[0]['output'], str(self.folder / 'redacted'))
        self.assertTrue((self.root / 'watches.json').is_file())

    def test_sweep_counts_a_settled_arrival(self):
        self.watches.addWatch(str(self.folder))
        self.image('new.png', age=0)
        self.watches.sweep()
        self.assertEqual(self.watches.newCount, 0)
        later = time.time() + 3
        self.watches.sweep(now=later)
        self.assertEqual(self.watches.newCount, 1)

    def test_open_marks_new_files_presented_and_scans_them(self):
        self.watches.addWatch(str(self.folder))
        new = self.image('new.png')
        self.watches.sweep(now=time.time() + 3)
        self.watches.openFolder(str(self.folder))
        self.wait_for_jobs()
        entry = next(item for item in self.controller.session.entries
                     if item.path == new)
        self.assertTrue(entry.scanned)
        self.assertTrue(entry.boxes)
        record = self.watches.store.seen[watch_store.key(self.folder)]['new.png']
        self.assertEqual(record.state, 'presented')

    def test_arrival_while_open_appends_a_row_and_keeps_selection(self):
        self.image('old.png')
        self.watches.addWatch(str(self.folder))
        self.watches.openFolder(str(self.folder))
        self.controller.session.row_selection = {0}
        before = self.controller.folder.folderModel.rowCount()
        self.image('late.png', age=10)
        self.watches.sweep()
        self.assertEqual(self.controller.folder.folderModel.rowCount(), before + 1)
        self.assertEqual(self.controller.session.row_selection, {0})
        self.wait_for_jobs()

    def test_note_export_marks_the_record(self):
        path = self.image('a.png')
        self.watches.addWatch(str(self.folder))
        self.watches.note_export(path, self.folder / 'redacted' / 'a_redacted.png')
        record = self.watches.store.seen[watch_store.key(self.folder)]['a.png']
        self.assertEqual(record.state, 'exported')
        self.assertEqual(self.watches.watchRows[0]['exported'], 0)  # file absent

    def test_policy_rows_report_auto_and_set_policy_accepts_aliases(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'auto')
        self.assertEqual(self.watches.watchRows[0]['policy'], 'AUTO')
        self.assertEqual(self.watches.watch_for(self.folder).policy, 'automatic')
        self.watches.setPolicy(str(self.folder), 'MANUAL')
        self.assertEqual(self.watches.watchRows[0]['policy'], 'MANUAL')
        self.assertEqual(self.watches.watch_for(self.folder).policy, 'manual')

    def test_output_for_matches_only_the_watch_folder_itself(self):
        self.watches.addWatch(str(self.folder))
        sub = self.folder / 'sub'
        sub.mkdir()
        self.assertEqual(self.watches.output_for(self.folder), self.folder / 'redacted')
        self.assertIsNone(self.watches.output_for(sub))
        self.controller.session.output_directory_override = self.root / 'global'
        self.assertEqual(
            self.controller.session.output_directory_for(sub), self.root / 'global')

    def test_remove_drops_the_watch_and_its_records(self):
        self.watches.addWatch(str(self.folder))
        self.watches.removeWatch(str(self.folder))
        self.assertEqual(self.watches.watchRows, [])
        self.assertEqual(self.watches.store.seen, {})

    def test_unavailable_folder_keeps_records_and_reports_an_error(self):
        self.image('a.png')
        self.watches.addWatch(str(self.folder))
        self.folder.rename(self.root / 'moved')
        self.watches.sweep()
        self.assertTrue(self.watches.watchRows[0]['error'])
        self.assertIn(watch_store.key(self.folder), self.watches.store.seen)

    def test_start_emits_inbox_requested_when_something_is_new(self):
        self.image('old.png')
        self.watches.addWatch(str(self.folder))
        self.image('new.png', age=10)
        requested = []
        self.watches.inboxRequested.connect(lambda: requested.append(True))
        self.watches.start()
        self.assertTrue(requested)

    def test_corrupt_store_is_quarantined_and_replaced(self):
        (self.root / 'watches.json').write_text('{not json', encoding='utf-8')
        self.watches.start()
        self.assertTrue((self.root / 'watches.json.corrupt').is_file())
        self.assertEqual(self.watches.watchRows, [])
        self.assertIn('could not be loaded', self.controller.alerts.status_text)

    def wait_for_auto(self, timeout_ms=10000):
        if not self.watches.autoRunning:
            return
        loop = QEventLoop()
        self.watches.autoChanged.connect(
            lambda: loop.quit() if not self.watches.autoRunning else None)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()

    def test_automatic_watch_exports_with_a_log(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.image('new.png')
        self.watches.sweep()
        self.wait_for_auto()
        target = self.folder / 'redacted' / 'new_redacted.png'
        self.assertTrue(target.is_file())
        self.assertTrue((self.folder / 'redacted' / 'new_redacted.redactions.json').is_file())
        self.assertEqual(self.watches.watchRows[0]['exported'], 1)

    def test_zero_suggestions_needs_review_and_writes_nothing(self):
        self.controller.session.preferences.categories = ('Emails',)
        self.controller.session.scan_engine = lambda: FakeEngine(
            'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
            '1\t1\t1\t1\t10\t20\t100\t20\t95\tplain words\n')
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.image('blank.png')
        self.watches.sweep()
        self.wait_for_auto()
        row = self.watches.watchRows[0]
        self.assertEqual(row['needs_review'], 1)
        self.assertIn('Nothing found', row['issues'][0]['detail'])
        self.assertFalse((self.folder / 'redacted' / 'blank_redacted.png').exists())

    def test_collision_needs_review_and_does_not_block_the_next_file(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        (self.folder / 'redacted').mkdir()
        (self.folder / 'redacted' / 'a_redacted.png').write_bytes(b'x')
        self.image('a.png')
        self.image('b.png')
        self.watches.sweep()
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'b_redacted.png').is_file())
        row = self.watches.watchRows[0]
        self.assertEqual(row['needs_review'], 1)
        self.assertEqual(row['exported'], 1)

    def test_automatic_pauses_while_the_folder_is_open(self):
        self.image('old.png')
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.watches.openFolder(str(self.folder))
        self.image('late.png')
        self.watches.sweep()
        self.assertFalse((self.folder / 'redacted' / 'late_redacted.png').exists())
        self.controller.folder.clear()
        self.wait_for_jobs()
        self.watches.sweep()
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'late_redacted.png').is_file())

    def test_switching_to_manual_stops_the_lane_and_marks_queued_presented(self):
        path = self.image('queued.png')
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        watch_store.mark(self.watches.store, self.watches.watch_for(self.folder), path,
                         state=watch_store.QUEUED)
        self.watches.setPolicy(str(self.folder), 'manual')
        record = self.watches.store.seen[watch_store.key(self.folder)]['queued.png']
        self.assertEqual(record.state, watch_store.PRESENTED)
        self.watches.sweep()
        self.assertFalse((self.folder / 'redacted' / 'queued_redacted.png').exists())

    def test_process_existing_queues_baseline_files(self):
        self.image('old.png')
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.watches.processExisting(str(self.folder))
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'old_redacted.png').is_file())

    def test_stop_reports_waiting_files_and_process_existing_resumes_them(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.watches.cancelAuto()
        path = self.image('waiting.png')
        watch_store.mark(self.watches.store, self.watches.watch_for(self.folder), path,
                         state=watch_store.QUEUED)
        self.watches.sweep()
        row = self.watches.watchRows[0]
        self.assertEqual(row['queued'], 1)
        self.assertFalse(self.watches.autoRunning)
        self.assertIn('1 waiting', self.watches.autoStatus)
        self.assertIn('PROCESS EXISTING', self.watches.autoStatus)
        self.watches.processExisting(str(self.folder))
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'waiting_redacted.png').is_file())
        self.assertEqual(self.watches.watchRows[0]['queued'], 0)

    def test_ocr_retry_requeues_the_failed_files(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.image('done.png')
        self.watches.sweep()
        self.wait_for_auto()
        self.assertIn('finished', self.watches.autoStatus)
        self.image('blocked.png')
        captured = {}
        self.controller.alerts.error = (
            lambda title, text, *actions: captured.update(title=title, actions=actions))
        self.controller.session.scan_engine = (
            lambda: (_ for _ in ()).throw(OSError('OCR unavailable')))
        self.watches.sweep()
        row = self.watches.watchRows[0]
        self.assertEqual(row['needs_review'], 1)
        self.assertEqual(self.watches.autoStatus, '')
        self.assertEqual(captured['actions'][0], 'RETRY')
        self.controller.session.scan_engine = lambda: FakeEngine(TSV)
        captured['actions'][1]()
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'blocked_redacted.png').is_file())

    def test_stop_hold_survives_sweeps_until_process_existing(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.watches.cancelAuto()
        self.image('later.png')
        self.watches.sweep()
        self.assertFalse(self.watches.autoRunning)
        self.assertFalse((self.folder / 'redacted' / 'later_redacted.png').exists())
        self.watches.processExisting(str(self.folder))
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'later_redacted.png').is_file())

    def test_switching_policy_to_automatic_resumes_after_stop(self):
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.watches.cancelAuto()
        self.image('later.png')
        self.watches.sweep()
        self.assertFalse(self.watches.autoRunning)
        self.watches.setPolicy(str(self.folder), 'manual')
        self.watches.setPolicy(str(self.folder), 'automatic')
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'later_redacted.png').is_file())

    def test_startup_resumes_a_queued_record(self):
        self.image('resume.png')
        self.watches.addWatch(str(self.folder))
        self.watches.setPolicy(str(self.folder), 'automatic')
        path = self.folder / 'resume.png'
        watch_store.mark(self.watches.store, self.watches.watch_for(self.folder), path,
                         state=watch_store.QUEUED)
        self.watches.sweep()
        self.wait_for_auto()
        self.assertTrue((self.folder / 'redacted' / 'resume_redacted.png').is_file())


if __name__ == '__main__':
    unittest.main()
