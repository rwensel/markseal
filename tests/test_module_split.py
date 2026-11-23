"""Public launcher re-exports and module ownership."""
import unittest

from tests.support import (
    core,
    rapidocr_backend,
)


class ModuleSplitTests(unittest.TestCase):
    def test_public_launcher_reexports_keep_resolving(self):
        import offline_redactor
        for name in ('IMAGE_SUFFIXES', 'PATTERNS', 'PRESETS', 'FolderImage', 'ScanCancelled',
                     'apply_redactions', 'detect_regions', 'find_tesseract', 'new_ocr_boxes',
                     'output_path', 'pixelate', 'preferences_path', 'read_folder_image',
                     'recognize_regions', 'save_export', 'write_folder_copy',
                     'write_preferences'):
            self.assertTrue(hasattr(offline_redactor, name), name)

    def test_each_concept_lives_in_its_sibling_module(self):
        from redactor import detection, images, ocr, redaction
        self.assertIs(detection.detect_regions, core.detect_regions)
        self.assertIs(detection.pattern_from_text, core.pattern_from_text)
        self.assertIs(redaction.pixelate, core.pixelate)
        self.assertIs(redaction.apply_redactions, core.apply_redactions)
        self.assertIs(images.read_folder_image, core.read_folder_image)
        self.assertIs(ocr.recognize_regions, core.recognize_regions)
        self.assertIs(ocr.scan_folder_image, core.scan_folder_image)

    def test_engine_pool_reuses_idle_engines_and_clears_on_close(self):
        created = []

        def create():
            created.append(object())
            return created[-1]

        pool = rapidocr_backend.EnginePool(create)
        first = pool.borrow()
        pool.release(first)
        self.assertIs(pool.borrow(), first)
        self.assertEqual(len(created), 1)
        pool.close()
        second = pool.borrow()
        self.assertIsNot(second, first)
        self.assertEqual(len(created), 2)
