"""Watched-folder store, intake rules, and state counts."""
import json
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


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / 'shots'
        self.folder.mkdir()
        self.store = watches.WatchStore()

    def add(self, policy='manual', recursive=False):
        return watches.add(self.store, watches.WatchedFolder(
            self.folder, policy, recursive=recursive))

    def write(self, name, age=10):
        path = self.folder / name
        make_image(path)
        stamp = time.time() - age
        os.utime(path, (stamp, stamp))
        return path

    def write_in(self, relative, age=10):
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
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

    def test_add_refuses_an_unlistable_folder(self):
        self.write('a.png')
        with mock.patch('markseal.watch_scan.scan', return_value=None):
            with self.assertRaises(watches.WatchError):
                self.add()
        self.assertEqual(self.store.folders, [])
        self.assertEqual(self.store.seen, {})

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

    def test_counts_report_queued_records(self):
        path = self.write('a.png')
        folder = self.add()
        watches.mark(self.store, folder, path, state=watches.QUEUED)
        counts = watches.counts(self.store, folder)
        self.assertEqual((counts.new, counts.queued), (0, 1))

    def test_mark_can_pin_the_scanned_stamp(self):
        path = self.write('a.png')
        folder = self.add()
        scanned = watches.record(path).stamp()
        later = time.time() + 100
        os.utime(path, (later, later))
        watches.mark(self.store, folder, path, state=watches.EXPORTED,
                     export=str(self.root / 'redacted' / 'a_redacted.png'),
                     stamp=scanned)
        moment = later + 3
        self.assertEqual(watches.unseen(self.store, folder, now=moment), [path])
        self.assertEqual(watches.counts(self.store, folder, now=moment).new, 1)

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

    def test_automatic_outcome_routing(self):
        from markseal.boxset import FolderImage
        exported = FolderImage(Path('a.png'))
        exported.boxes = [(0, 0, 10, 10)]
        exported.selected = {0}
        self.assertEqual(watches.automatic_outcome(exported), (watches.EXPORTED, ''))
        partial = FolderImage(Path('b.png'))
        partial.boxes = [(0, 0, 10, 10)]
        partial.selected = {0}
        partial.incomplete_ocr = ('Personal names',)
        self.assertEqual(watches.automatic_outcome(partial),
                         (watches.NEEDS_REVIEW, 'Partial scan'))
        empty = FolderImage(Path('c.png'))
        self.assertEqual(watches.automatic_outcome(empty),
                         (watches.NEEDS_REVIEW, 'Nothing found'))

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

    def test_recursive_add_baselines_nested_images(self):
        self.write('root.png')
        self.write_in('sub/a.png')
        folder = self.add(recursive=True)
        counts = watches.counts(self.store, folder)
        self.assertEqual((counts.new, counts.existing, counts.available), (0, 2, True))
        records = self.store.seen[watches.key(self.folder)]
        self.assertIn(os.path.normcase('sub/a.png'), records)
        self.assertEqual(watches.unseen(self.store, folder), [])

    def test_recursive_scan_skips_the_export_directory(self):
        folder = self.add(recursive=True)
        nested = self.write_in('sub/a.png')
        self.write_in('redacted/out.png')
        found = watches.unseen(self.store, folder, now=time.time() + 3)
        self.assertEqual(found, [nested])

    def test_nested_names_do_not_collide(self):
        folder = self.add(recursive=True)
        one = self.write_in('one/a.png')
        two = self.write_in('two/a.png')
        found = watches.unseen(self.store, folder, now=time.time() + 3)
        self.assertEqual(found, [one, two])
        watches.mark(self.store, folder, one, state=watches.QUEUED)
        watches.mark(self.store, folder, two, state=watches.NEEDS_REVIEW,
                     detail='Nothing found')
        counts = watches.counts(self.store, folder)
        self.assertEqual((counts.queued, counts.needs_review), (1, 1))
        records = self.store.seen[watches.key(self.folder)]
        self.assertIn(os.path.normcase('one/a.png'), records)
        self.assertIn(os.path.normcase('two/a.png'), records)

    def test_mark_nested_image_uses_its_relative_path(self):
        folder = self.add(recursive=True)
        path = self.write_in('sub/a.png')
        target = self.folder / 'redacted' / 'sub' / 'a_redacted.png'
        watches.mark(self.store, folder, path, state=watches.EXPORTED,
                     export=str(target))
        record = self.store.seen[watches.key(self.folder)][os.path.normcase('sub/a.png')]
        self.assertEqual((record.state, record.export), (watches.EXPORTED, str(target)))

    def test_baseline_nested_only_leaves_a_new_root_image_new(self):
        folder = self.add()
        root = self.write('late.png')
        nested = self.write_in('sub/a.png')
        folder.recursive = True
        watches.baseline(self.store, folder, nested_only=True)
        counts = watches.counts(self.store, folder)
        self.assertEqual((counts.new, counts.existing), (1, 1))
        self.assertEqual(watches.unseen(self.store, folder, now=time.time() + 3), [root])
        self.assertIn(os.path.normcase('sub/a.png'),
                      self.store.seen[watches.key(self.folder)])

    def test_recursive_scan_does_not_follow_a_symlink(self):
        folder = self.add(recursive=True)
        real = self.write_in('real/a.png')
        link = self.folder / 'link'
        try:
            link.symlink_to(self.folder / 'real', target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are unavailable')
        found = watches.unseen(self.store, folder, now=time.time() + 3)
        self.assertEqual(found, [real])

    def test_round_trip_preserves_recursion(self):
        folder = self.add(recursive=True)
        target = self.root / 'watches.json'
        watches.save(target, self.store)
        loaded = watches.load(target)
        self.assertTrue(loaded.folders[0].recursive)
        self.assertEqual(loaded.folders, self.store.folders)

    def test_load_migrates_name_keys_to_relative_paths(self):
        target = self.root / 'watches.json'
        record = {'size': 1, 'mtime_ns': 2, 'state': 'presented',
                  'export': '', 'detail': ''}
        target.write_text(json.dumps({
            'folders': [{'path': str(self.folder), 'policy': 'manual',
                         'output_directory': None}],
            'seen': {watches.key(self.folder): {'a.png': record}},
        }), encoding='utf-8')
        loaded = watches.load(target)
        self.assertFalse(loaded.folders[0].recursive)
        self.assertIn(os.path.normcase('a.png'), loaded.seen[watches.key(self.folder)])

    def test_unreadable_subfolder_is_reported_and_keeps_records(self):
        self.write_in('locked/a.png')
        folder = self.add(recursive=True)
        real_scandir = os.scandir

        def guarded(path):
            if Path(path).name == 'locked':
                raise PermissionError('denied')
            return real_scandir(path)

        with mock.patch('markseal.images.os.scandir', side_effect=guarded):
            counts = watches.counts(self.store, folder)
        self.assertTrue(counts.available)
        self.assertIn(('locked', 'Could not read this folder'), counts.issues)
        self.assertIn(os.path.normcase('locked/a.png'),
                      self.store.seen[watches.key(self.folder)])

    def test_turning_recursion_off_keeps_nested_records(self):
        folder = self.add(recursive=True)
        nested = self.write_in('sub/a.png')
        watches.mark(self.store, folder, nested, state=watches.QUEUED)
        folder.recursive = False
        watches.prune(self.store, folder, [])
        records = self.store.seen[watches.key(self.folder)]
        self.assertIn(os.path.normcase('sub/a.png'), records)
        self.assertEqual(records[os.path.normcase('sub/a.png')].state, watches.QUEUED)

    def test_scan_exposes_relative_entries_and_skips_exports(self):
        folder = self.add(recursive=True)
        nested = self.write_in('sub/a.png')
        self.write_in('redacted/out.png')
        entries = watches.scan(self.store, folder)
        self.assertEqual([entry.key for entry in entries],
                         [os.path.normcase('sub/a.png')])
        self.assertEqual(entries[0].path, nested)

    def test_folder_for_and_contains_respect_recursion(self):
        folder = self.add(recursive=True)
        root = self.write('root.png')
        nested = self.write_in('sub/a.png')
        self.assertIs(watches.folder_for(self.store, root), folder)
        self.assertIs(watches.folder_for(self.store, nested), folder)
        self.assertTrue(watches.contains(folder, root))
        self.assertTrue(watches.contains(folder, nested))
        folder.recursive = False
        self.assertIs(watches.folder_for(self.store, root), folder)
        self.assertIsNone(watches.folder_for(self.store, nested))
        self.assertFalse(watches.contains(folder, nested))

    def test_destination_mirrors_a_nested_source(self):
        folder = self.add(recursive=True)
        root = self.folder / 'root.png'
        nested = self.folder / 'sub' / 'a.png'
        self.assertEqual(watches.destination(folder, root), folder.export_directory)
        self.assertEqual(watches.destination(folder, nested),
                         folder.export_directory / 'sub')

    def test_exclusions_lists_each_watch_export_directory(self):
        folder = self.add()
        self.assertEqual(watches.exclusions(self.store), (folder.export_directory,))
