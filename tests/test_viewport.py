"""View transforms, drag mapping, and hit testing."""
import unittest

from tests.support import (
    Image,
    Path,
    Review,
    Viewport,
)


class ViewportTests(unittest.TestCase):
    def test_point_mapping_round_trips_at_the_letterbox_edges(self):
        view = Viewport()
        view.set_view_size(500, 400)
        view.reset((200, 100))
        self.assertAlmostEqual(view.scale, 1.0)
        self.assertAlmostEqual(view.offset_x, 150)
        self.assertAlmostEqual(view.offset_y, 150)
        self.assertEqual(view.image_coordinates(150, 150), (0, 0))
        self.assertEqual(view.image_coordinates(349, 249), (199, 99))
        self.assertEqual(view.image_coordinates(10, 10), (-140, -140))

    def test_zoom_anchors_the_pointer_at_the_same_image_pixel(self):
        view = Viewport()
        view.set_view_size(500, 500)
        view.reset((1000, 1000))
        before = view.image_coordinates(250, 250)
        self.assertTrue(view.zoom_at(250, 250, 1))
        self.assertEqual(view.image_coordinates(250, 250), before)
        self.assertGreater(view.zoom, 1.0)

    def test_drag_boxes_normalize_every_direction_with_exclusive_edges(self):
        view = Viewport()
        view.set_view_size(200, 200)
        view.reset((200, 200))
        expected = (10, 10, 41, 31)
        self.assertEqual(view.drag_box(10, 10, start=(40, 30)), expected)
        self.assertEqual(view.drag_box(40, 30, start=(10, 10)), expected)
        self.assertEqual(view.drag_box(10, 30, start=(40, 10)), expected)
        self.assertEqual(view.drag_box(40, 10, start=(10, 30)), expected)

    def test_drag_rect_tracks_the_pointer_in_view_space(self):
        view = Viewport()
        view.set_view_size(100, 100)
        view.reset((100, 100))
        self.assertTrue(view.begin_drag(20, 30))
        self.assertEqual(view.drag_rect(60, 10), (20, 10, 40, 20))
        self.assertEqual(view.take_drag(), (20, 30))
        self.assertIsNone(view.drag_rect(60, 10))

    def test_capture_region_clamps_to_the_image_at_zoom(self):
        view = Viewport()
        view.set_view_size(200, 200)
        view.reset((100, 100))
        view.zoom_at(100, 100, 1)
        self.assertEqual(view.drag_region(-50, -50, start=(500, 500)), (0, 0, 100, 100))

    def test_hit_testing_uses_the_letterbox_offset(self):
        view = Viewport()
        view.set_view_size(500, 400)
        view.reset((200, 100))
        boxes = [(10, 10, 50, 50)]
        self.assertEqual(view.hit_index(160, 160, boxes), 0)
        self.assertIsNone(view.hit_index(210, 210, boxes))

    def test_pan_only_starts_when_zoomed_and_ends_once(self):
        view = Viewport()
        view.set_view_size(400, 400)
        view.reset((1000, 1000))
        self.assertFalse(view.pan_begin(200, 200))
        view.zoom_at(200, 200, 1)
        self.assertTrue(view.pan_begin(200, 200))
        self.assertTrue(view.pan_move(180, 190))
        self.assertTrue(view.pan_end())
        self.assertFalse(view.pan_end())

    def test_tiny_drag_adds_no_box_and_click_toggles_only_inside(self):
        review = Review()
        review.load(Image.new('RGB', (200, 200)), Path('tiny.png'))
        review.set_view_size(200, 200)
        self.assertEqual(review.release(10, 10), 'none')
        self.assertTrue(review.press(10, 10))
        self.assertEqual(review.release(13, 13), 'none')
        self.assertEqual(review.boxes, [])
