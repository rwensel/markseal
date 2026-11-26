"""Public launcher re-exports and module ownership."""
import ast
import unittest
from pathlib import Path

from PySide6.QtCore import QObject

from tests.support import (
    core,
    rapidocr_backend,
)


class ModuleSplitTests(unittest.TestCase):
    def test_public_launcher_reexports_keep_resolving(self):
        import offline_redactor
        for name in ('IMAGE_SUFFIXES', 'PATTERNS', 'PRESETS', 'FolderImage', 'ScanCancelled',
                     'apply_redactions', 'detect_regions', 'new_ocr_boxes',
                     'output_path', 'pixelate', 'preferences_path', 'read_folder_image',
                     'recognize_regions', 'save_export', 'write_folder_copy',
                     'write_preferences'):
            self.assertTrue(hasattr(offline_redactor, name), name)

    def test_each_concept_lives_in_its_sibling_module(self):
        from markseal import detection, images, ocr, redaction
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

    def test_controller_is_only_the_qml_shell(self):
        from markseal.controller import Controller

        def declared(cls):
            meta = cls.staticMetaObject
            props = {meta.property(index).name()
                     for index in range(meta.propertyCount())}
            methods = {bytes(meta.method(index).name()).decode()
                       for index in range(meta.methodCount())}
            return props, methods

        base_props, base_methods = declared(QObject)
        props, methods = declared(Controller)
        self.assertEqual(props - base_props, {
            'settings', 'review', 'folder', 'batch', 'updates', 'watches',
            'statusText', 'errorText', 'errorDetail', 'errorActionText',
        })
        self.assertEqual(methods - base_methods, {
            'statusChanged', 'errorChanged',
            'dismissError', 'runErrorAction',
            'openImage', 'openFolder', 'openDropped', 'pasteImage', 'captureRegion',
            'canClose',
        })

    def test_facade_modules_do_not_import_the_controller(self):
        import markseal.facades
        package = Path(markseal.facades.__file__).resolve().parent
        modules = sorted(path for path in package.glob('*.py') if path.name != '__init__.py')
        self.assertEqual(
            [path.stem for path in modules],
            ['activity', 'alerts', 'auto_watch', 'batch', 'folder', 'review',
             'review_actions', 'review_load', 'review_scan_actions', 'review_view',
             'settings', 'state', 'updates', 'watch_inbox', 'watch_sweep', 'watches'],
        )
        for path in modules:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    self.assertNotEqual(module, 'controller', f'{path.name} imports controller')
                    self.assertNotEqual(module, 'markseal.controller',
                                        f'{path.name} imports controller')
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn('controller', alias.name,
                                         f'{path.name} imports controller')
