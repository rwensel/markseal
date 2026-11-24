"""Third-party notices ship with the app and stay readable."""
import unittest

from markseal.facades.settings import third_party_notices_path


class NoticesTests(unittest.TestCase):
    def test_notices_cover_core_components_and_licenses(self):
        text = third_party_notices_path().read_text(encoding='utf-8')
        for name in ('Qt for Python (PySide6)', 'RapidOCR', 'OpenCV',
                     'ONNX Runtime', 'pypdfium2', 'PDFium', 'YuNet face detection model'):
            with self.subTest(name=name):
                self.assertIn(name, text)
        self.assertIn('LGPL-3.0-only', text)
        self.assertIn('Apache-2.0', text)
        self.assertIn('LICENSE TEXTS', text)

    def test_summary_precedes_the_license_bodies(self):
        text = third_party_notices_path().read_text(encoding='utf-8')
        summary, _, bodies = text.partition('\nLICENSE TEXTS\n')
        self.assertTrue(summary.startswith('THIRD-PARTY NOTICES'))
        self.assertIn('COMPONENTS', summary)
        self.assertTrue(bodies.strip())
