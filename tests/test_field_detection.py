"""Deterministic personal-field detection."""
import unittest

from markseal.field_detection import field_boxes


def line(*words, top=20):
    return [(text, left, top, left + width, top + 24, confidence)
            for text, left, width, confidence in words]


class FieldDetectionTests(unittest.TestCase):
    def test_name_and_address_values_exclude_the_label(self):
        boxes, rules = field_boxes(
            [line(('Name:', 0, 50, 99), ('Katie', 60, 60, 99), ('Miller', 130, 60, 99)),
             line(('Address:', 0, 70, 99), ('129', 80, 40, 99), ('Maple', 130, 60, 99),
                  ('Ave,', 200, 50, 99), ('Anytown,', 260, 80, 99), ('USA', 350, 40, 99))],
            (800, 400), 50, {'Personal names', 'Postal addresses'})
        self.assertEqual(rules[boxes[0]], ('Personal names',))
        self.assertGreater(boxes[0][0], 54)
        self.assertGreaterEqual(boxes[1][0], 74)
        self.assertLess(boxes[1][0], 100)
        self.assertEqual(rules[boxes[1]], ('Postal addresses',))

    def test_license_value_requires_a_separator_and_a_digit(self):
        boxes, rules = field_boxes(
            [line(('License', 0, 70, 99), ('agreement', 80, 90, 99)),
             line(('License', 0, 70, 99), ('#CSM1234567890', 80, 160, 99))],
            (800, 400), 50, {'License & ID numbers'})
        self.assertEqual(len(boxes), 1)
        self.assertEqual(rules[boxes[0]], ('License & ID numbers',))

    def test_mid_line_license_takes_only_the_value(self):
        boxes, rules = field_boxes(
            [line(('Certified', 0, 70, 99), ('Scrum', 80, 60, 99), ('Master', 150, 70, 99),
                  ('License', 400, 70, 99), ('#CSM1234567890', 480, 160, 99))],
            (900, 400), 50, {'License & ID numbers'})
        self.assertEqual(len(boxes), 1)
        self.assertGreater(boxes[0][0], 466)
        self.assertEqual(rules[boxes[0]], ('License & ID numbers',))

    def test_two_column_row_stops_at_the_next_label(self):
        boxes, rules = field_boxes(
            [line(('Name:', 0, 50, 99), ('Katie', 60, 60, 99), ('Miller', 130, 60, 99),
                  ('DOB:', 400, 40, 99), ('01/15/1980', 450, 100, 99))],
            (800, 400), 50, {'Personal names', 'Dates of birth'})
        self.assertEqual(rules[boxes[0]], ('Personal names',))
        self.assertEqual(rules[boxes[1]], ('Dates of birth',))

    def test_address_continues_for_one_wrapped_line(self):
        first = line(('Address:', 0, 70, 99))
        second = [('129', 10, 50, 90, 74, 99), ('Maple', 60, 50, 120, 74, 99),
                  ('Ave,', 130, 50, 180, 74, 99)]
        boxes, rules = field_boxes([first, second], (800, 400), 50, {'Postal addresses'})
        self.assertEqual(len(boxes), 1)
        self.assertEqual(rules[boxes[0]], ('Postal addresses',))

    def test_birth_dates_accept_numeric_and_written_values(self):
        numeric, numeric_rules = field_boxes(
            [line(('DOB:', 0, 40, 99), ('01/15/1980', 50, 90, 99))],
            (600, 200), 50, {'Dates of birth'})
        written, written_rules = field_boxes(
            [line(('Date', 0, 40, 99), ('of', 50, 20, 99), ('Birth:', 80, 50, 99),
                  ('January', 140, 60, 99), ('15,', 210, 30, 99), ('1980', 250, 40, 99))],
            (600, 200), 50, {'Dates of birth'})
        self.assertEqual(numeric_rules[numeric[0]], ('Dates of birth',))
        self.assertEqual(written_rules[written[0]], ('Dates of birth',))

    def test_passport_value_is_detected(self):
        boxes, rules = field_boxes(
            [line(('Passport', 0, 60, 99), ('No:', 70, 30, 99), ('AB1234567', 110, 90, 99))],
            (600, 200), 50, {'License & ID numbers'})
        self.assertEqual(len(boxes), 1)
        self.assertEqual(rules[boxes[0]], ('License & ID numbers',))

    def test_line_start_prose_is_not_a_name(self):
        prose, _ = field_boxes(
            [line(('name', 0, 40, 99), ('is', 50, 20, 99), ('Katie', 80, 50, 99))],
            (600, 200), 50, {'Personal names'})
        contact, _ = field_boxes(
            [line(('Contact', 0, 60, 99), ('Katie', 70, 50, 99), ('Miller', 130, 50, 99))],
            (600, 200), 50, {'Personal names'})
        self.assertEqual(prose, [])
        self.assertEqual(contact, [])

    def test_placeholders_and_low_confidence_values_are_rejected(self):
        placeholders, _ = field_boxes(
            [line(('DOB:', 0, 40, 99), ('N/A', 50, 30, 99)),
             line(('Name:', 0, 40, 99), ('-', 50, 10, 99))],
            (600, 200), 50, {'Dates of birth', 'Personal names'})
        low, _ = field_boxes(
            [line(('Name:', 0, 40, 99), ('Katie', 50, 50, 10))],
            (600, 200), 50, {'Personal names'})
        self.assertEqual(placeholders, [])
        self.assertEqual(low, [])

    def test_disabled_categories_do_not_run(self):
        boxes, rules = field_boxes(
            [line(('Address:', 0, 70, 99), ('129', 80, 40, 99), ('Maple', 130, 60, 99))],
            (600, 200), 50, {'Personal names'})
        self.assertEqual(boxes, [])
        self.assertEqual(rules, {})
