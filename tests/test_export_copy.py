import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from markseal import preferences
from markseal.boxset import FolderImage
from markseal.export_copy import CopyRequest, ExportCopies, export_succeeded


class ExportCopyTests(unittest.TestCase):
    def setUp(self):
        self.preferences = preferences.defaults()
        self.copies = ExportCopies(self.preferences)

    def entry(self, path='a.png', boxes=((0, 0, 5, 5),), selected=(0,)):
        return FolderImage(Path(path), boxes=boxes, selected=selected)

    def test_plan_builds_targets_and_counts_unredacted_copies(self):
        with TemporaryDirectory() as folder:
            redacted = self.entry()
            unredacted = self.entry('b.png', boxes=(), selected=())

            plan = self.copies.plan(
                [CopyRequest.from_entry(redacted), CopyRequest.from_entry(unredacted)],
                output_directory=Path(folder),
            )

            self.assertEqual([job.target.name for job in plan.jobs],
                             ['a_redacted.png', 'b_redacted.png'])
            self.assertEqual(plan.unredacted, 1)
            self.assertTrue(plan.include_log)

    def test_plan_refuses_an_existing_target_and_log(self):
        with TemporaryDirectory() as folder:
            (Path(folder) / 'a_redacted.png').write_bytes(b'x')
            with self.assertRaises(ValueError):
                self.copies.plan(
                    [CopyRequest.from_entry(self.entry())],
                    output_directory=Path(folder),
                )

    def test_plan_can_allow_an_explicit_single_save_overwrite(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'picked.png'
            target.write_bytes(b'x')
            request = CopyRequest(
                source=Path('a.png'),
                method='Pixelate',
                target=target,
            )

            plan = self.copies.plan(
                [request], output_directory=Path(folder), allow_overwrite=True)

            self.assertEqual(plan.jobs[0].target, target)

    def test_plan_returns_none_when_the_chooser_cancels(self):
        with TemporaryDirectory() as folder:
            plan = self.copies.plan(
                [CopyRequest.from_entry(self.entry())],
                output_directory=Path(folder),
                choose=lambda target: None,
            )

        self.assertIsNone(plan)

    def test_snapshot_keeps_the_planned_source_and_boxes(self):
        with TemporaryDirectory() as folder:
            entry = self.entry()
            plan = self.copies.plan(
                [CopyRequest.from_entry(entry)], output_directory=Path(folder))

            snapshot = self.copies.snapshot(plan.jobs[0])

        self.assertEqual(snapshot.source, Path('a.png'))
        self.assertEqual(snapshot.target, plan.jobs[0].target)
        self.assertEqual(snapshot.boxes, ((0, 0, 5, 5),))
        self.assertEqual(snapshot.selected, frozenset({0}))

    def test_write_and_verify_share_the_same_result_shape(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / 'a.png'
            Image.new('RGB', (30, 20), 'white').save(source)
            entry = FolderImage(source, boxes=[(5, 5, 15, 15)], selected={0})
            plan = self.copies.plan(
                [CopyRequest.from_entry(entry)], output_directory=Path(folder))

            job = self.copies.snapshot(plan.jobs[0])
            self.copies.write(job, include_log=plan.include_log)
            result = self.copies.verify(plan.jobs[0].target, Path(folder))

            self.assertEqual(result['issue'], None)
            self.assertTrue(result['outside_pixels_unchanged'])
            self.assertEqual(result['logged_boxes'], 1)

    def test_auto_snapshot_targets_the_watch_folder(self):
        entry = self.entry(boxes=((1, 2, 3, 4),), selected=(0,))

        snapshot, include_log = self.copies.auto_snapshot(
            entry, Path('shots/redacted'))

        self.assertEqual(snapshot.target, Path('shots/redacted/a_redacted.png'))
        self.assertTrue(include_log)
        self.assertEqual(list(snapshot.boxes), [(1, 2, 3, 4)])

    def test_auto_snapshot_confirms_and_refuses_an_existing_target(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / 'a_redacted.png'
            target.write_bytes(b'x')
            entry = self.entry()
            with self.assertRaises(ValueError):
                self.copies.auto_snapshot(entry, Path(folder))

            self.assertTrue(entry.reviewed)

    def test_export_succeeded_requires_the_snapshot_to_match(self):
        entry = self.entry(boxes=((0, 0, 5, 5),), selected=(0,))
        entry.confirm(True)
        snapshot = type('Snapshot', (), {
            'boxes': [(0, 0, 5, 5)],
            'selected': {0},
            'method': entry.method,
        })()
        self.assertTrue(export_succeeded(entry, snapshot))

        entry.selected = set()
        self.assertFalse(export_succeeded(entry, snapshot))


if __name__ == '__main__':
    unittest.main()
