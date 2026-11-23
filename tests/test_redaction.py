"""Redaction output and selection behavior."""
import unittest

from tests.support import (
    FolderImage,
    Image,
    Path,
    Review,
    apply_redactions,
    pixelate,
)


class RedactionTests(unittest.TestCase):
    def test_pixelate_preserves_pixels_outside_box(self):
        im = Image.new('RGB', (100, 80), 'white')
        for x in range(10, 70):
            for y in range(10, 50): im.putpixel((x, y), (x*3, y*5, 40))
        out = pixelate(im, [(10, 10, 70, 50)])
        self.assertEqual(im.getpixel((5, 5)), out.getpixel((5, 5)))
        self.assertNotEqual(im.getpixel((12, 12)), out.getpixel((12, 12)))
        self.assertEqual(im.getpixel((12, 12)), (36, 60, 40))

    def test_solid_redaction_changes_only_selected_area(self):
        im = Image.new('RGB', (50, 50), 'white')
        out = apply_redactions(im, [(10, 10, 20, 20)], 'Solid black')
        self.assertEqual(out.getpixel((12, 12)), (0, 0, 0))
        self.assertEqual(out.getpixel((20, 20)), (255, 255, 255))

    def test_select_confirm_and_change_selection(self):
        review = Review()
        review.load(Image.new('RGB', (200, 200)), Path('test.png'))
        review.set_view_size(100, 100)
        review.boxes = [(10, 10, 60, 60), (80, 80, 110, 110)]
        review.selected = set()
        review.confirmed = False
        review.press(15, 15)
        review.release(15, 15)
        self.assertEqual(review.selected, {0})
        self.assertEqual(review.selected_boxes(), [(10, 10, 60, 60)])
        review.confirmed = True
        review.press(15, 15)
        review.release(15, 15)
        self.assertEqual(review.selected, set())
        self.assertFalse(review.confirmed)
        review.press(60, 60)
        review.release(80, 80)
        self.assertEqual(review.boxes[-1], (120, 120, 161, 161))
        self.assertIn(2, review.selected)

    def test_new_suggestions_start_selected_without_reselecting_existing(self):
        review = Review()
        review.image = Image.new('RGB', (200, 200))
        review.boxes = [(1, 1, 10, 10)]
        review.selected = set()
        review.confirmed = True
        added = review.add_suggestions([(1, 1, 10, 10), (20, 20, 40, 40)])
        self.assertEqual(added, 1)
        self.assertEqual(review.selected, {1})
        self.assertFalse(review.confirmed)

    def test_nested_selected_suggestions_keep_only_the_outer_box(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        other = (200, 10, 260, 60)
        added = review.add_suggestions([inner, outer, other])
        self.assertEqual(added, 2)
        self.assertEqual(review.boxes, [outer, other])
        self.assertEqual(review.selected, {0, 1})

    def test_suggestion_inside_existing_selected_area_is_skipped(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        review.boxes = [outer]
        review.selected = {0}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([(20, 20, 60, 40)]), 0)
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertTrue(review.confirmed)

    def test_outer_suggestion_replaces_existing_selected_inner_box(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        inner = (20, 20, 60, 40)
        outer = (10, 10, 120, 60)
        review.boxes = [inner]
        review.selected = {0}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([outer]), 1)
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertFalse(review.confirmed)

    def test_unselected_outer_box_does_not_remove_selected_inner_box(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        review.boxes = [outer, inner]
        review.selected = {1}
        self.assertEqual(review.add_suggestions([(200, 10, 260, 60)]), 1)
        self.assertEqual(review.boxes, [outer, inner, (200, 10, 260, 60)])
        self.assertEqual(review.selected, {1, 2})

    def test_folder_suggestions_skip_boxes_inside_selected_area(self):
        entry = FolderImage(Path('example.png'))
        outer = (10, 10, 120, 60)
        entry.boxes = [outer]
        entry.selected = {0}
        self.assertEqual(entry.add_suggestions([(20, 20, 60, 40)]), 0)
        self.assertEqual(entry.boxes, [outer])
        self.assertEqual(entry.selected, {0})

    def test_scan_cleans_existing_nested_selected_boxes(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        review.boxes = [outer, inner]
        review.selected = {0, 1}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([]), 0)
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertFalse(review.confirmed)

    def test_zoom_keeps_pointer_location_and_selection_coordinates(self):
        review = Review()
        review.load(Image.new('RGB', (1000, 1000)), Path('test.png'))
        review.set_view_size(500, 500)
        self.assertAlmostEqual(review.scale, 0.5)
        self.assertTrue(review.zoom_at(250, 250, 1))
        self.assertAlmostEqual((250-review.offset_x) / review.scale, 500)
        self.assertAlmostEqual((250-review.offset_y) / review.scale, 500)
        self.assertGreater(review.scale, 0.5)

    def test_small_image_is_centered_in_the_view(self):
        review = Review()
        review.load(Image.new('RGB', (200, 100)), Path('small.png'))
        review.set_view_size(500, 400)
        self.assertEqual(review.scale, 1.0)
        self.assertAlmostEqual(review.offset_x, 150)
        self.assertAlmostEqual(review.offset_y, 150)
