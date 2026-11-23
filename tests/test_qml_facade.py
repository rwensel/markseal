"""Every QML reference to the Backend singleton resolves to a real member."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

import markseal
from markseal.controller import Controller

REFERENCE = re.compile(r'Backend\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)')
CONNECTIONS = re.compile(r'Connections\s*\{')
TARGET = re.compile(r'target:\s*(Backend(?:\.\w+)*)')
HANDLER = re.compile(r'function\s+on([A-Z]\w*)\s*\(')


def qml_files():
    return sorted((Path(markseal.__file__).resolve().parent / 'qml').glob('*.qml'))


def member_names(obj):
    meta = obj.metaObject()
    names = {meta.property(index).name() for index in range(meta.propertyCount())}
    for index in range(meta.methodCount()):
        names.add(bytes(meta.method(index).name()).decode())
    return names


def resolved_value(obj, name):
    meta = obj.metaObject()
    for index in range(meta.propertyCount()):
        declaration = meta.property(index)
        if declaration.name() == name:
            return True, getattr(obj, name)
    return name in member_names(obj), None


def resolves(root, path):
    current = root
    for part in path.split('.'):
        if not isinstance(current, QObject):
            return True
        found, value = resolved_value(current, part)
        if not found:
            return False
        if value is None:
            return True
        current = value
    return True


def connections_blocks(text):
    for match in CONNECTIONS.finditer(text):
        depth = 0
        for index in range(match.end() - 1, len(text)):
            if text[index] == '{':
                depth += 1
            elif text[index] == '}':
                depth -= 1
                if depth == 0:
                    yield match.start(), text[match.end():index]
                    break


class QmlFacadeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.controller = Controller(
            preferences_file=Path(self.temporary.name) / 'settings.json'
        )
        self.addCleanup(self.controller.deleteLater)

    def test_every_backend_reference_resolves(self):
        failures = []
        for path in qml_files():
            lines = path.read_text(encoding='utf-8').splitlines()
            for lineno, line in enumerate(lines, 1):
                for match in REFERENCE.finditer(line):
                    if not resolves(self.controller, match.group(1)):
                        failures.append(f'{path.name}:{lineno}: Backend.{match.group(1)}')
        self.assertEqual(failures, [])

    def test_every_connections_handler_maps_to_a_signal(self):
        failures = []
        for path in qml_files():
            text = path.read_text(encoding='utf-8')
            for offset, block in connections_blocks(text):
                target = TARGET.search(block)
                if target is None:
                    continue
                line = text[:offset].count('\n') + 1
                obj = self.controller
                for part in target.group(1).split('.')[1:]:
                    obj = getattr(obj, part)
                names = member_names(obj)
                for handler in HANDLER.findall(block):
                    signal = handler[0].lower() + handler[1:]
                    if signal not in names:
                        failures.append(
                            f'{path.name}:{line}: {target.group(1)} has no signal {signal}'
                        )
        self.assertEqual(failures, [])


if __name__ == '__main__':
    unittest.main()
