import unittest
from pathlib import Path

from markseal.boxset import FolderImage


class ReviewLifecycleTests(unittest.TestCase):
    def image(self):
        return FolderImage(Path('screen.png'))

    def test_apply_scan_marks_scanned_and_clears_review_state(self):
        image = self.image()
        image.reviewed = True
        image.saved = True

        added = image.apply_scan([(0, 0, 10, 10)], ('Personal names',))

        self.assertEqual(added, 1)
        self.assertTrue(image.scanned)
        self.assertEqual(image.incomplete_ocr, ('Personal names',))
        self.assertFalse(image.reviewed)
        self.assertFalse(image.saved)
        self.assertEqual(image.error, '')

    def test_apply_scan_without_suggestions_still_resets_review_state(self):
        image = self.image()
        image.reviewed = True
        image.saved = True

        added = image.apply_scan([])

        self.assertEqual(added, 0)
        self.assertTrue(image.scanned)
        self.assertFalse(image.reviewed)
        self.assertFalse(image.saved)

    def test_merge_boxes_resets_review_only_when_boxes_change(self):
        image = self.image()
        image.confirm(True)
        image.mark_saved(Path('screen_redacted.png'))

        changed = image.merge_boxes([(0, 0, 10, 10)], source='Copied box')

        self.assertTrue(changed)
        self.assertFalse(image.reviewed)
        self.assertFalse(image.saved)
        self.assertIsNone(image.export_path)

        image.confirm(True)
        image.mark_saved(Path('screen_redacted.png'))
        unchanged = image.merge_boxes([(0, 0, 10, 10)], source='Copied box')

        self.assertFalse(unchanged)
        self.assertTrue(image.reviewed)
        self.assertTrue(image.saved)

    def test_confirm_and_save_follow_the_review_lifecycle(self):
        image = self.image()
        image.boxes = [(0, 0, 10, 10)]

        image.confirm(True)
        self.assertTrue(image.reviewed)
        self.assertTrue(image.unsaved)

        image.mark_saved(Path('screen_redacted.png'))
        self.assertTrue(image.saved)
        self.assertEqual(image.export_path, Path('screen_redacted.png'))
        self.assertFalse(image.unsaved)

        image.confirm(False)
        self.assertFalse(image.reviewed)
        self.assertFalse(image.saved)
        self.assertIsNone(image.export_path)

    def test_method_change_resets_only_on_a_different_method(self):
        image = self.image()
        image.boxes = [(0, 0, 10, 10)]
        image.confirm(True)
        image.mark_saved(Path('screen_redacted.png'))

        self.assertFalse(image.set_method('Pixelate'))
        self.assertTrue(image.reviewed)
        self.assertTrue(image.saved)

        self.assertTrue(image.set_method('Blur'))
        self.assertEqual(image.method, 'Blur')
        self.assertFalse(image.reviewed)
        self.assertFalse(image.saved)
        self.assertIsNone(image.export_path)
        self.assertTrue(image.unsaved)

    def test_unsaved_is_false_for_an_empty_entry(self):
        image = self.image()

        self.assertFalse(image.unsaved)

        image.confirm(True)
        self.assertTrue(image.unsaved)

        image.mark_saved(Path('screen_redacted.png'))
        self.assertFalse(image.unsaved)


if __name__ == '__main__':
    unittest.main()
