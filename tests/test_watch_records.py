import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

from markseal import watches


def make_image(path):
    Image.new('RGB', (40, 30), 'white').save(path)


class WatchRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'shots'
        self.folder.mkdir()
        self.store = watches.WatchStore()
        self.store_path = self.root / 'watches.json'
        self.watch = watches.add(self.store, watches.WatchedFolder(self.folder))
        self.records = watches.WatchRecords(self.store, self.store_path)

    def write(self, name='a.png'):
        path = self.folder / name
        make_image(path)
        stamp = time.time() - 10
        os.utime(path, (stamp, stamp))
        return path

    def folder_key(self):
        return watches.key(self.folder)

    def test_set_refreshes_counts_and_persists(self):
        path = self.write()
        change = self.records.set(self.watch, path, state=watches.QUEUED)

        self.assertTrue(change.changed)
        self.assertIsNone(change.error)
        self.assertEqual(change.folder_key, self.folder_key())
        self.assertEqual(change.counts.queued, 1)
        self.assertEqual(
            self.store.seen[self.folder_key()]['a.png'].state, watches.QUEUED)
        loaded = watches.load(self.store_path)
        self.assertEqual(
            loaded.seen[self.folder_key()]['a.png'].state, watches.QUEUED)

    def test_set_pins_the_scan_stamp(self):
        path = self.write()
        stamp = watches.record(path).stamp()
        later = time.time() + 100
        os.utime(path, (later, later))

        change = self.records.set(self.watch, path, state=watches.EXPORTED,
                                  stamp=stamp, export=self.root / 'out.png')

        self.assertTrue(change.changed)
        self.assertEqual(change.counts.new, 1)

    def test_set_reports_a_missing_source_without_writing(self):
        change = self.records.set(
            self.watch, self.folder / 'missing.png', state=watches.QUEUED)

        self.assertFalse(change.changed)
        self.assertIsInstance(change.error, OSError)
        self.assertEqual(self.store.seen[self.folder_key()], {})
        self.assertFalse(self.store_path.exists())

    def test_set_rolls_back_when_persistence_fails(self):
        path = self.write()
        self.records.set(self.watch, path, state=watches.PRESENTED)
        with mock.patch('markseal.watches.save', side_effect=OSError('disk full')):
            change = self.records.set(self.watch, path, state=watches.QUEUED)

        self.assertFalse(change.changed)
        self.assertIsInstance(change.error, OSError)
        record = self.store.seen[self.folder_key()]['a.png']
        self.assertEqual(record.state, watches.PRESENTED)

    def test_set_many_saves_once(self):
        one = self.write('one.png')
        two = self.write('two.png')
        with mock.patch('markseal.watches.save', wraps=watches.save) as save:
            change = self.records.set_many(
                self.watch, [one, two], state=watches.QUEUED)

        self.assertTrue(change.changed)
        self.assertEqual(change.counts.queued, 2)
        self.assertEqual(save.call_count, 1)

    def test_forget_removes_records_and_persists(self):
        path = self.write()
        self.records.set(self.watch, path, state=watches.PRESENTED)

        change = self.records.forget(self.watch, [path])

        self.assertTrue(change.changed)
        self.assertNotIn('a.png', self.store.seen[self.folder_key()])
        loaded = watches.load(self.store_path)
        self.assertNotIn('a.png', loaded.seen[self.folder_key()])

    def test_process_existing_queues_matching_automatic_records(self):
        path = self.write()
        self.records.set(self.watch, path, state=watches.PRESENTED)

        change = self.records.process_existing(self.watch, automatic=True)

        self.assertTrue(change.changed)
        self.assertEqual(change.counts.queued, 1)
        self.assertEqual(
            self.store.seen[self.folder_key()]['a.png'].state, watches.QUEUED)

    def test_process_existing_skips_a_changed_source(self):
        path = self.write()
        self.records.set(self.watch, path, state=watches.PRESENTED)
        later = time.time() + 100
        os.utime(path, (later, later))

        change = self.records.process_existing(self.watch, automatic=True)

        self.assertFalse(change.changed)
        self.assertEqual(change.counts.queued, 0)

    def test_process_existing_forgets_matching_manual_records(self):
        path = self.write()
        self.records.set(self.watch, path, state=watches.PRESENTED)

        change = self.records.process_existing(self.watch, automatic=False)

        self.assertTrue(change.changed)
        self.assertNotIn('a.png', self.store.seen[self.folder_key()])


if __name__ == '__main__':
    unittest.main()
