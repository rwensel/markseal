"""Watched-folder store, intake rules, and state counts."""
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from markseal import watches


def make_image(path):
    Image.new('RGB', (40, 30), 'white').save(path)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'shots'
        self.folder.mkdir()
        self.store = watches.WatchStore()

    def add(self, policy='manual'):
        return watches.add(self.store, watches.WatchedFolder(self.folder, policy))

    def write(self, name, age=10):
        path = self.folder / name
        make_image(path)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def test_add_baselines_current_images(self):
        self.write('a.png')
        self.write('b.jpg')
        folder = self.add()
        counts = watches.counts(self.store, folder)
        self.assertEqual((counts.new, counts.existing, counts.available), (0, 2, True))
        self.assertEqual(watches.unseen(self.store, folder), [])

    def test_later_image_is_new_only_after_it_settles(self):
        folder = self.add()
        path = self.write('new.png', age=0)
        self.assertEqual(watches.unseen(self.store, folder), [])
        later = time.time() + 3
        self.assertEqual(watches.unseen(self.store, folder, now=later), [path])

    def test_changed_stamp_makes_an_exported_file_new(self):
        path = self.write('a.png')
        folder = self.add()
        watches.mark(self.store, folder, path, state=watches.EXPORTED,
                     export=str(self.root / 'redacted' / 'a_redacted.png'))
        self.assertEqual(watches.counts(self.store, folder).new, 0)
        later = time.time() + 100
        os.utime(path, (later, later))
        self.assertEqual(watches.counts(self.store, folder).new, 1)

    def test_non_images_sidecars_and_export_targets_are_ignored(self):
        folder = self.add()
        (self.folder / 'notes.txt').write_text('x', encoding='utf-8')
        (self.folder / 'a.redactions.json').write_text('{}', encoding='utf-8')
        exported = self.write('source.png')
        target = self.folder / 'b_redacted.png'
        make_image(target)
        watches.mark(self.store, folder, exported, state=watches.EXPORTED,
                     export=str(target))
        candidate = self.write('a.png')
        found = watches.unseen(self.store, folder, now=time.time() + 3)
        self.assertEqual(found, [candidate])

    def test_prune_drops_only_the_names_absent_from_the_listing(self):
        self.write('a.png')
        self.write('b.png')
        folder = self.add()
        watches.prune(self.store, folder, ['a.png'])
        names = self.store.seen[watches.key(self.folder)]
        self.assertEqual(list(names), ['a.png'])

    def test_pending_queued_respects_the_stamp(self):
        path = self.write('a.png')
        folder = self.add()
        watches.mark(self.store, folder, path, state=watches.QUEUED)
        self.assertEqual(watches.pending_queued(self.store, folder), [path])
        later = time.time() + 100
        os.utime(path, (later, later))
        self.assertEqual(watches.pending_queued(self.store, folder), [])

    def test_round_trip_and_remove(self):
        path = self.write('a.png')
        folder = self.add('automatic')
        watches.mark(self.store, folder, path, state=watches.NEEDS_REVIEW,
                     detail='Nothing found')
        target = self.root / 'watches.json'
        watches.save(target, self.store)
        loaded = watches.load(target)
        self.assertEqual(loaded.folders, self.store.folders)
        self.assertEqual(
            loaded.seen[watches.key(self.folder)]['a.png'].detail, 'Nothing found')
        watches.remove(loaded, self.folder)
        self.assertEqual(loaded.folders, [])
        self.assertNotIn(watches.key(self.folder), loaded.seen)

    def test_malformed_document_raises(self):
        target = self.root / 'watches.json'
        target.write_text('{', encoding='utf-8')
        with self.assertRaises(watches.WatchError):
            watches.load(target)

    def test_counts_on_an_unavailable_folder_keep_the_records(self):
        self.write('a.png')
        folder = self.add()
        self.folder.rename(self.root / 'moved')
        counts = watches.counts(self.store, folder)
        self.assertFalse(counts.available)
        self.assertIn(watches.key(self.folder), self.store.seen)

    def test_validation_rejections(self):
        self.add()
        nested = self.folder / 'nested'
        nested.mkdir()
        for candidate in (
            watches.WatchedFolder(Path('relative')),
            watches.WatchedFolder(self.root / 'missing'),
            watches.WatchedFolder(self.folder),
            watches.WatchedFolder(self.folder, 'other'),
            watches.WatchedFolder(nested),
        ):
            with self.subTest(candidate=candidate):
                self.assertIsNotNone(watches.validate(self.store, candidate))
        outside = self.root / 'elsewhere'
        outside.mkdir()
        self.assertIsNotNone(watches.validate(
            self.store, watches.WatchedFolder(outside, output_directory=self.folder)))
        existing_output = self.root / 'exports'
        existing_output.mkdir()
        self.store.folders.append(
            watches.WatchedFolder(outside, output_directory=existing_output))
        self.assertIsNotNone(watches.validate(
            self.store, watches.WatchedFolder(existing_output)))
