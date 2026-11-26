import unittest
from pathlib import Path

from markseal import workflows
from tests.support import BoxList, FolderImage


def entry(name, **options):
    return FolderImage(Path(name), **options)


class ScanPlanningTests(unittest.TestCase):
    def test_scan_plan_skips_reviewed_entries_unless_rescanning(self):
        scanned = entry('scanned.png', scanned=True)
        reviewed = entry('reviewed.png', reviewed=True)
        fresh = entry('fresh.png')
        plan = workflows.plan_scan([scanned, reviewed, fresh], [scanned, reviewed, fresh])
        self.assertEqual(plan.entries, (fresh,))
        self.assertEqual(plan.label, 'Scanning')
        self.assertEqual(plan.rows, {scanned.path: 0, reviewed.path: 1, fresh.path: 2})
        self.assertEqual(plan.jobs, ((fresh.path, None),))

        rescan = workflows.plan_scan([scanned, reviewed, fresh], [scanned, reviewed, fresh],
                                     rescan=True, area=(1, 1, 9, 9))
        self.assertEqual(rescan.entries, (scanned, reviewed, fresh))
        self.assertEqual(rescan.label, 'Scanning area')

    def test_scan_result_merges_suggestions_and_marks_review_state(self):
        image = entry('shot.png', stamp='v1')
        found = BoxList([(10, 10, 20, 20)], {(10, 10, 20, 20): ('Emails',)})
        outcome = workflows.apply_scan_result(image, ('v1', found, ('enhanced',)))
        self.assertEqual(outcome.count, 1)
        self.assertTrue(outcome.changed)
        self.assertEqual(outcome.incomplete, ('enhanced',))
        self.assertEqual(image.boxes, [(10, 10, 20, 20)])
        self.assertTrue(image.scanned)
        self.assertEqual(image.stamp, 'v1')

    def test_scan_result_rejects_a_changed_source(self):
        image = entry('shot.png', stamp='v1')
        outcome = workflows.apply_scan_result(
            image, ('v2', BoxList([(1, 1, 2, 2)]), ()),
        )
        self.assertEqual(outcome.error, 'Source changed')
        self.assertEqual(image.error, 'Source changed')
        self.assertEqual(image.boxes, [])

    def test_area_scan_keeps_outside_boxes_and_tags_area_provenance(self):
        box = (1, 1, 5, 5)
        image = entry('shot.png', boxes=[box], selected={0})
        found = BoxList([(20, 20, 40, 40)], {(20, 20, 40, 40): ('Emails',)})
        outcome = workflows.apply_scan_result(image, (None, found, ()), area=(0, 0, 50, 50))
        self.assertEqual(outcome.count, 1)
        self.assertEqual(image.boxes, [box, (20, 20, 40, 40)])
        self.assertEqual(image.rules[(20, 20, 40, 40)], ('Emails',))

    def test_scan_summary_counts_complete_and_partial_entries(self):
        complete = entry('a.png', scanned=True)
        partial = entry('b.png', scanned=True, incomplete_ocr=('color',))
        failed = entry('c.png', error='Scan failed')
        self.assertEqual(workflows.scan_summary([complete, partial, failed]), '1 succeeded · 1 partial')
        self.assertEqual(workflows.scan_summary([], area=(0, 0, 1, 1)), 'No area results')
        self.assertEqual(
            workflows.scan_summary([complete], area=(0, 0, 1, 1), area_completed=True),
            'Area scan finished · review suggested boxes',
        )


class BatchToolTests(unittest.TestCase):
    def test_copy_reports_skipped_unchanged_and_applied(self):
        image = entry('a.png', stamp='v1')
        self.assertEqual(workflows.copy_boxes_to_entry(image, [(0, 0, 5, 5)], 'v2', True), 'skipped')
        self.assertEqual(workflows.copy_boxes_to_entry(image, [(0, 0, 5, 5)], 'v1', False), 'skipped')
        self.assertEqual(workflows.copy_boxes_to_entry(image, [(0, 0, 5, 5)], 'v1', True), 'applied')
        self.assertEqual(workflows.copy_boxes_to_entry(image, [(0, 0, 5, 5)], 'v1', True), 'unchanged')

    def test_match_reports_whether_boxes_were_placed(self):
        image = entry('a.png', stamp='v1')
        self.assertEqual(workflows.match_boxes_to_entry(image, [], 'v1'), (False, False))
        self.assertEqual(workflows.match_boxes_to_entry(image, [(0, 0, 5, 5)], 'v2'), (False, False))
        self.assertEqual(workflows.match_boxes_to_entry(image, [(0, 0, 5, 5)], 'v1'), (True, True))
        self.assertEqual(image.rules[(0, 0, 5, 5)], ('Anchor match',))


class ConfirmationTests(unittest.TestCase):
    def test_eligibility_skips_empty_errored_and_reviewed_entries(self):
        ready = entry('a.png', selected={0}, boxes=[(0, 0, 5, 5)])
        eligible = workflows.eligible_for_confirmation([
            ready,
            entry('b.png', boxes=[(0, 0, 5, 5)]),
            entry('c.png', selected={0}, boxes=[(0, 0, 5, 5)], error='Scan failed'),
            entry('d.png', selected={0}, boxes=[(0, 0, 5, 5)], reviewed=True),
        ])
        self.assertEqual(eligible, [ready])

    def test_confirmation_prompt_names_partial_scans(self):
        prompt = workflows.confirmation_prompt([
            entry('a.png', selected={0}, boxes=[(0, 0, 5, 5)],
                  scanned=True, incomplete_ocr=('color',)),
        ], 'Pixelate')
        self.assertIn('1 image?', prompt)
        self.assertIn('1 image has a partial scan', prompt)

    def test_confirmation_prompt_handles_plural_images(self):
        prompt = workflows.confirmation_prompt([
            entry('a.png', selected={0}, boxes=[(0, 0, 5, 5)],
                  scanned=True, incomplete_ocr=('color',)),
            entry('b.png', selected={0}, boxes=[(0, 0, 5, 5)],
                  scanned=True, incomplete_ocr=('color',)),
        ], 'Blur')
        self.assertIn('2 images?', prompt)
        self.assertIn('2 images have partial scans', prompt)


if __name__ == '__main__':
    unittest.main()
