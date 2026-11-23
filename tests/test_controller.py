"""Offscreen tests for the QML controller and its review-to-export workflow."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from PySide6.QtCore import QEventLoop, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

import markseal
from markseal.controller import Controller, DisplayImageProvider
from tests.support import FakeEngine

TSV = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
       '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n')


class ControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        QQuickStyle.setStyle('Basic')
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.controller = Controller(
            preferences_file=Path(self.temporary.name) / 'settings.json'
        )
        self.controller.alerts.info = lambda *args, **kwargs: None
        self.controller.alerts.ask = lambda *args, **kwargs: True
        self.errors = []
        self.controller.alerts.error = (
            lambda title, text='', *args, **kwargs: self.errors.append((title, text))
        )

    def tearDown(self):
        self.controller.deleteLater()
        self.app.processEvents()

    def open_image(self):
        path = Path(self.temporary.name) / 'screenshot.png'
        Image.new('RGB', (300, 100), 'white').save(path)
        with Image.open(path) as source:
            image = source.convert('RGB')
        self.controller._present_image(image, path)
        return path

    def wait_for_jobs(self, timeout_ms=10000):
        if not self.controller.batch.busy:
            return
        loop = QEventLoop()

        def finished():
            if not self.controller.batch.busy:
                loop.quit()

        self.controller.batch.busyChanged.connect(finished)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()
        self.controller.batch.busyChanged.disconnect(finished)
        self.assertFalse(self.controller.batch.busy, 'background job did not finish')

    def test_scan_review_and_export_round_trip(self):
        source = self.open_image()
        engine = FakeEngine(tsv=TSV)
        with patch.object(self.controller.session, 'scan_engine', return_value=engine):
            self.controller.review.start_single_scan()
            self.wait_for_jobs()

        self.assertEqual(self.errors, [])
        self.assertEqual(self.controller.review.totalBoxes, 1)
        self.assertEqual(self.controller.review.selectedCount, 1)
        self.assertEqual(self.controller.session.review.rules[
                             self.controller.session.review.boxes[0]],
                         ('Emails',))

        self.controller.review.toggleBox(0)
        self.assertEqual(self.controller.review.selectedCount, 0)
        self.assertFalse(self.controller.review.confirmed)
        self.controller.review.toggleBox(0)
        self.controller.settings.setRedactionMethod('Solid black')
        self.controller.review.confirmSelection()
        self.assertTrue(self.controller.review.confirmed)

        target = Path(self.temporary.name) / 'screenshot_redacted.png'
        with patch('markseal.facades.review.QFileDialog.getSaveFileName',
                   return_value=(str(target), 'PNG image (*.png)')):
            self.controller.review.save_single()

        self.assertEqual(self.errors, [])
        self.assertTrue(target.is_file())
        self.assertTrue(target.with_suffix('.redactions.json').is_file())
        with Image.open(source) as original, Image.open(target) as exported:
            self.assertEqual(original.size, exported.size)
            self.assertEqual(exported.getpixel((20, 25)), (0, 0, 0))
            self.assertEqual(original.getpixel((250, 80)), exported.getpixel((250, 80)))

    def test_main_qml_loads_with_the_backend(self):
        qmlRegisterSingletonInstance(Controller, 'Redactor', 1, 0, 'Backend', self.controller)
        engine = QQmlApplicationEngine()
        engine.addImageProvider('redactor', DisplayImageProvider(self.controller))
        main_qml = Path(markseal.__file__).resolve().parent / 'qml' / 'Main.qml'
        messages = []
        previous = qInstallMessageHandler(
            lambda mode, context, message: messages.append(message)
        )
        try:
            engine.load(QUrl.fromLocalFile(str(main_qml)))
        finally:
            qInstallMessageHandler(previous)
        self.assertTrue(engine.rootObjects(), f'Main.qml did not load: {messages}')
        qml_warnings = [message for message in messages if 'qml' in message.lower()]
        self.assertEqual(qml_warnings, [])


if __name__ == '__main__':
    unittest.main()
