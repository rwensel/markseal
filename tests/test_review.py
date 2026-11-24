"""Review session state and folder image sharing."""
import unittest

from tests.support import (
    BoxList,
    BoxSet,
    FolderImage,
    Image,
    Path,
    Review,
    image_status,
)


class ReviewSessionTests(unittest.TestCase):
    def test_folder_image_and_review_share_one_box_state(self):
        entry = FolderImage(Path('shared.png'))
        review = Review()
        review.load(Image.new('RGB', (200, 200)), Path('shared.png'))
        review.boxset = entry.boxset
        box = (10, 10, 50, 50)
        review.add_suggestions(BoxList([box], {box: ('Emails',)}))
        self.assertEqual(entry.boxes, [box])
        self.assertEqual(entry.rules[box], ('Emails',))
        self.assertEqual(entry.selected, {0})
        review.selected = set()
        self.assertEqual(entry.selected, set())
        entry.add_shared_boxes([(60, 60, 90, 90)], source='Copied box')
        self.assertEqual(review.boxes[-1], (60, 60, 90, 90))
        self.assertEqual(review.rules[(60, 60, 90, 90)], ('Copied box',))

    def test_toggle_box_updates_selection_and_clears_confirmation(self):
        review = Review()
        review.load(Image.new('RGB', (100, 100)), Path('toggle.png'))
        review.boxes = [(1, 1, 10, 10), (20, 20, 30, 30)]
        review.selected = {0, 1}
        review.confirmed = True
        self.assertTrue(review.toggle_box(0))
        self.assertEqual(review.selected, {1})
        self.assertFalse(review.confirmed)
        self.assertFalse(review.toggle_box(9))

    def test_select_all_and_none_clear_confirmation(self):
        review = Review()
        review.load(Image.new('RGB', (100, 100)), Path('select.png'))
        review.boxes = [(1, 1, 10, 10), (20, 20, 30, 30)]
        review.selected = {0}
        review.confirmed = False
        self.assertTrue(review.select_all())
        self.assertEqual(review.selected, {0, 1})
        self.assertFalse(review.confirmed)
        self.assertFalse(review.select_all())
        review.confirmed = True
        self.assertFalse(review.select_all())
        self.assertEqual(review.selected, {0, 1})
        review.confirmed = False
        self.assertTrue(review.select_none())
        self.assertEqual(review.selected, set())
        self.assertFalse(review.select_none())

    def test_state_survives_switching_between_folder_images(self):
        first = FolderImage(Path('one.png'))
        second = FolderImage(Path('two.png'))
        review = Review()
        review.load(Image.new('RGB', (100, 100)), first.path)
        review.boxset = first.boxset
        review.add_suggestions([(1, 1, 10, 10)])
        review.boxset = second.boxset
        review.add_suggestions([(20, 20, 30, 30)])
        review.boxset = first.boxset
        self.assertEqual(review.boxes, [(1, 1, 10, 10)])
        self.assertEqual(review.selected, {0})
        self.assertEqual(second.boxes, [(20, 20, 30, 30)])
        self.assertEqual(second.selected, {0})

    def test_status_transitions_follow_scan_review_and_save(self):
        entry = FolderImage(Path('status.png'))
        self.assertEqual(entry.status, 'Not scanned')
        entry.add_suggestions([])
        self.assertEqual(entry.status, 'Scanned · review needed')
        entry.add_suggestions([(1, 1, 5, 5)], ['enhanced OCR timed out'])
        self.assertEqual(entry.status, 'Partial scan · review needed')
        entry.reviewed = True
        self.assertEqual(entry.status, 'Reviewed')
        entry.saved = True
        self.assertEqual(entry.status, 'Saved')
        entry.error = 'Open failed'
        self.assertEqual(entry.status, 'Open failed')
        self.assertEqual(image_status(boxes=[(0, 0, 1, 1)]), 'Boxes added · review needed')

    def test_both_merge_paths_prune_nested_boxes_with_one_rule_source(self):
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        entry = FolderImage(Path('nested.png'))
        entry.add_shared_boxes([inner, outer], source='Anchor match')
        self.assertEqual(entry.boxes, [outer])
        self.assertEqual(entry.selected, {0})
        self.assertEqual(entry.rules, {outer: ('Anchor match',)})

        review = Review()
        review.load(Image.new('RGB', (400, 300)), Path('nested.png'))
        review.add_suggestions(BoxList([inner, outer], {inner: ('Secrets',),
                                                         outer: ('Secrets',)}))
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertEqual(review.rules, {outer: ('Secrets',)})

    def test_absorbed_box_reports_unchanged_in_both_paths(self):
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        entry = FolderImage(Path('absorbed.png'), boxes=[outer], selected={0})
        self.assertFalse(entry.add_shared_boxes([inner]))
        self.assertEqual(entry.boxes, [outer])

        review = Review()
        review.load(Image.new('RGB', (400, 300)), Path('absorbed.png'))
        review.boxes = [outer]
        review.selected = {0}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([inner]), 0)
        self.assertTrue(review.confirmed)
        self.assertEqual(review.boxes, [outer])

    def test_new_boxes_clear_review_and_save_flags(self):
        entry = FolderImage(Path('flags.png'))
        entry.add_suggestions([(1, 1, 9, 9)])
        entry.reviewed = entry.saved = True
        entry.add_shared_boxes([(20, 20, 30, 30)], source='Anchor match')
        self.assertFalse(entry.reviewed)
        self.assertFalse(entry.saved)
        entry.reviewed = entry.saved = True
        entry.add_suggestions([(40, 40, 50, 50)])
        self.assertFalse(entry.reviewed)
        self.assertFalse(entry.saved)
        self.assertEqual(entry.rules[(20, 20, 30, 30)], ('Anchor match',))

    def test_boxset_remove_and_undo_keep_selection_indices(self):
        state = BoxSet(boxes=[(0, 0, 5, 5), (10, 10, 20, 20), (30, 30, 40, 40)],
                       selected={0, 1, 2})
        self.assertTrue(state.remove(1))
        self.assertEqual(state.selected, {0, 1})
        self.assertEqual(state.selected_boxes(), [(0, 0, 5, 5), (30, 30, 40, 40)])
        self.assertTrue(state.undo())
        self.assertEqual(state.boxes, [(0, 0, 5, 5)])
        self.assertEqual(state.selected, {0})
        self.assertTrue(state.clear())
        self.assertEqual(state.boxes, [])

    def test_redo_restores_the_undone_box_and_selection(self):
        state = BoxSet(boxes=[(0, 0, 5, 5), (10, 10, 20, 20)],
                       rules={(10, 10, 20, 20): ('Secrets',)}, selected={0, 1})
        self.assertTrue(state.undo())
        self.assertTrue(state.can_redo())
        self.assertEqual(state.selected, {0})
        self.assertTrue(state.redo())
        self.assertEqual(state.boxes, [(0, 0, 5, 5), (10, 10, 20, 20)])
        self.assertEqual(state.rules[(10, 10, 20, 20)], ('Secrets',))
        self.assertEqual(state.selected, {0, 1})
        self.assertFalse(state.can_redo())

    def test_new_box_clears_redo(self):
        state = BoxSet(boxes=[(0, 0, 5, 5)])
        state.undo()
        state.add((1, 1, 6, 6))
        self.assertFalse(state.can_redo())
