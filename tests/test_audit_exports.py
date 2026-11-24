"""Verify exported copies against their originals and coordinate logs."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from markseal import audit_exports, export


class VerifyExportTests(unittest.TestCase):
    def make_export(self, folder, method='Pixelate'):
        originals = Path(folder) / 'originals'
        originals.mkdir()
        original = originals / 'a.png'
        Image.new('RGB', (80, 60), 'white').save(original)
        target = Path(folder) / 'a_redacted.png'
        image = Image.new('RGB', (80, 60), 'white')
        job = export.snapshot(original, target, [(10, 10, 30, 30)], frozenset([0]),
                              method, image=image)
        export.write_copy(job, include_log=True)
        return originals, target

    def test_clean_copy_reports_outside_unchanged(self):
        with TemporaryDirectory() as folder:
            originals, exported = self.make_export(folder)
            result = audit_exports.verify_export(exported, originals)
        self.assertTrue(result['outside_pixels_unchanged'])
        self.assertEqual(result['logged_boxes'], 1)
        self.assertIsNone(result['issue'])

    def test_ocr_mode_uses_identifiers_without_the_model(self):
        with TemporaryDirectory() as folder:
            originals, exported = self.make_export(folder)
            with patch('markseal.ocr.make_engine', return_value=object()), \
                 patch('markseal.ocr.recognize_regions', return_value=[]):
                result = audit_exports.verify_export(exported, originals, run_ocr=True)
        self.assertIsNone(result['issue'])
        self.assertEqual(result['ocr_candidates'],
                         {'covered': 0, 'partial': 0, 'uncovered': 0})

    def test_missing_log_reports_issue_without_raising(self):
        with TemporaryDirectory() as folder:
            originals, exported = self.make_export(folder)
            exported.with_suffix('.redactions.json').unlink()
            result = audit_exports.verify_export(exported, originals)
        self.assertIn('coordinate log missing', result['issue'])
        self.assertIsNone(result['outside_pixels_unchanged'])


if __name__ == '__main__':
    unittest.main()
