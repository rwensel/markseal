import unittest

from markseal.suggestions import SuggestionSet, contains, padded_box


def word(text, left, top, right, bottom, confidence=95):
    return (text, left, top, right, bottom, confidence)


class PaddedBoxTests(unittest.TestCase):
    def test_pads_and_clamps_to_the_image(self):
        self.assertEqual(padded_box([word('a', 10, 20, 30, 40)], (100, 100)),
                         (6, 16, 34, 44))
        self.assertEqual(padded_box([word('a', 0, 0, 4, 4)], (100, 100)),
                         (0, 0, 8, 8))
        self.assertEqual(padded_box([word('a', 90, 90, 100, 100)], (100, 100)),
                         (86, 86, 100, 100))


class SuggestionSetTests(unittest.TestCase):
    def test_add_merges_same_region_provenance(self):
        found = SuggestionSet()
        found.add((10, 10, 100, 40), 'Emails')
        found.add((11, 11, 99, 39), 'Personal names')
        self.assertEqual(found.boxes, [(10, 10, 100, 40)])
        self.assertEqual(found.rules[(10, 10, 100, 40)], ('Emails', 'Personal names'))

    def test_add_exact_keeps_neighboring_boxes_separate(self):
        found = SuggestionSet()
        found.add_exact((10, 10, 100, 40), 'Emails')
        found.add_exact((11, 11, 99, 39), 'Personal names')
        self.assertEqual(len(found.boxes), 2)
        self.assertEqual(found.rules[(10, 10, 100, 40)], ('Emails',))

    def test_merge_unions_same_region_rules(self):
        found = SuggestionSet()
        found.add_exact((10, 10, 100, 40), 'Emails')
        other = SuggestionSet()
        other.add_exact((11, 11, 99, 39), 'Personal names')
        found.merge(other)
        self.assertEqual(found.boxes, [(10, 10, 100, 40)])
        self.assertEqual(found.rules[(10, 10, 100, 40)], ('Emails', 'Personal names'))

    def test_merge_personal_prefers_the_larger_box_and_keeps_rules(self):
        found = SuggestionSet()
        found.add_exact((10, 10, 40, 40), 'Emails')
        other = SuggestionSet()
        other.add_exact((8, 8, 50, 50), 'Personal names')
        found.merge_personal(other)
        self.assertEqual(found.boxes, [(8, 8, 50, 50)])
        self.assertEqual(found.rules[(8, 8, 50, 50)], ('Emails', 'Personal names'))

    def test_merge_personal_unions_a_contained_shared_label(self):
        found = SuggestionSet()
        found.add_exact((0, 0, 1000, 1000), 'Personal names')
        other = SuggestionSet()
        other.add_exact((10, 10, 40, 40), 'Personal names')
        found.merge_personal(other)
        self.assertEqual(found.boxes, [(0, 0, 1000, 1000)])
        self.assertEqual(found.rules[(0, 0, 1000, 1000)], ('Personal names',))

    def test_cover_replaces_every_contained_box(self):
        found = SuggestionSet()
        found.add_exact((10, 10, 20, 20), 'Emails')
        found.add_exact((50, 50, 60, 60), 'Emails')
        found.cover((5, 5, 30, 30), 'Secrets')
        self.assertEqual(found.boxes, [(50, 50, 60, 60), (5, 5, 30, 30)])
        self.assertEqual(found.rules[(5, 5, 30, 30)], ('Secrets',))

    def test_prune_contained_keeps_the_container_and_unions_labels(self):
        found = SuggestionSet()
        found.add_exact((0, 0, 1000, 1000), 'Emails')
        found.add_exact((10, 10, 40, 40), 'Emails')
        found.add_exact((10, 10, 40, 40), 'Personal names')
        found.prune_contained()
        self.assertEqual(found.boxes, [(0, 0, 1000, 1000)])
        self.assertEqual(found.rules, {(0, 0, 1000, 1000): ('Emails', 'Personal names')})

    def test_parts_exposes_tuple_rules(self):
        found = SuggestionSet()
        found.add((10, 10, 100, 40), 'Emails')
        boxes, rules = found.parts()
        self.assertEqual(boxes, [(10, 10, 100, 40)])
        self.assertEqual(rules, {(10, 10, 100, 40): ('Emails',)})

    def test_contains_is_exact(self):
        self.assertTrue(contains((0, 0, 10, 10), (1, 1, 9, 9)))
        self.assertFalse(contains((0, 0, 10, 10), (0, 0, 11, 10)))
        self.assertFalse(contains((0, 0, 10, 10), (11, 0, 20, 10)))


if __name__ == '__main__':
    unittest.main()
