"""Architecture guards: dependency direction and the single network seam."""
import ast
import unittest
from pathlib import Path

import markseal

ROOT = Path(markseal.__file__).resolve().parent

DOMAIN = (
    'audit_exports.py', 'boxset.py', 'core.py', 'detection.py', 'export.py',
    'field_detection.py', 'image_detection.py', 'images.py', 'jobs.py', 'ner.py',
    'ocr.py', 'ocr_preprocess.py', 'patterns.py',
    'performance_log.py', 'preferences.py', 'rapidocr_backend.py', 'redaction.py',
    'review.py', 'theme_tokens.py', 'viewport.py', 'visual_anchor.py',
    'workflows.py',
)
UI_MODULES = {'PySide6', 'facades', 'controller', 'qml'}
NETWORK_MODULES = {'urllib', 'http', 'requests', 'socket', 'ssl', 'aiohttp', 'ftplib', 'xmlrpc'}
NETWORK_SEAM = 'updates.py'


def imported_parts(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    parts = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts.update(alias.name.split('.'))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                parts.update(node.module.split('.'))
            if node.level:
                for alias in node.names:
                    parts.update(alias.name.split('.'))
    return parts


class ArchitectureTests(unittest.TestCase):
    def test_domain_modules_do_not_reach_toward_qt_or_the_ui(self):
        for name in DOMAIN:
            parts = imported_parts(ROOT / name)
            self.assertEqual(parts & UI_MODULES, set(), f'{name} imports UI layers')

    def test_facades_do_not_import_the_controller(self):
        for path in sorted((ROOT / 'facades').glob('*.py')):
            parts = imported_parts(path)
            self.assertNotIn('controller', parts, f'{path.name} imports controller')

    def test_only_the_updates_seam_imports_network_libraries(self):
        for path in sorted(ROOT.rglob('*.py')):
            hits = imported_parts(path) & NETWORK_MODULES
            if hits:
                self.assertEqual(path.name, NETWORK_SEAM,
                                 f'{path.name} imports {sorted(hits)}')
