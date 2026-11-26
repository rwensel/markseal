"""Offscreen tests for the QML controller and its review-to-export workflow."""
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

import markseal
from markseal.controller import Controller, DisplayImageProvider
from tests.support import FakeEngine

TSV = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
       '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n')


def write_pdf(path, count=2):
    pages = [Image.new('RGB', (612, 792), 'white') for _ in range(count)]
    pages[0].save(path, 'PDF', save_all=True, append_images=pages[1:], resolution=72)


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

    def open_pdf(self):
        path = Path(self.temporary.name) / 'two-pages.pdf'
        write_pdf(path)
        with patch.object(self.controller, '_choose_image', return_value=path):
            self.controller.openImage()
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

    def test_capture_region_loads_a_pasted_image(self):
        qimage = QImage(40, 30, QImage.Format.Format_RGB32)
        qimage.fill(0xFFFFFFFF)
        with patch.object(self.controller, '_grab_screen_region', return_value=qimage):
            self.controller.captureRegion(10, 10, 40, 30)
        self.assertTrue(self.controller.session.pasted_image)
        self.assertIsNotNone(self.controller.session.review.image)

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

        self.controller.review.verifyCurrent()
        self.assertIsNone(self.controller.review.last_verify['issue'])
        self.assertTrue(self.controller.review.last_verify['outside_pixels_unchanged'])

    def test_open_image_accepts_a_pdf(self):
        path = Path(self.temporary.name) / 'two-pages.pdf'
        write_pdf(path)
        with patch.object(self.controller, '_choose_image', return_value=path):
            self.controller.openImage()
        self.assertEqual(self.errors, [])
        self.assertTrue(self.controller.review.isPdf)
        self.assertEqual(self.controller.review.pdfPage, 1)
        self.assertEqual(self.controller.review.pdfPageCount, 2)
        self.assertTrue(self.controller.review.hasImage)

    def test_drop_pdf_loads_first_page(self):
        path = Path(self.temporary.name) / 'two-pages.pdf'
        write_pdf(path)
        self.controller.openDropped([QUrl.fromLocalFile(str(path))])
        self.assertEqual(self.errors, [])
        self.assertTrue(self.controller.review.isPdf)
        self.assertEqual(self.controller.review.pdfPage, 1)
        self.assertEqual(self.controller.review.pdfPageCount, 2)

    def test_corrupt_pdf_reports_an_error(self):
        path = Path(self.temporary.name) / 'broken.pdf'
        path.write_bytes(b'%PDF-1.7\nnot a real pdf')
        with patch.object(self.controller, '_choose_image', return_value=path):
            self.controller.openImage()
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(self.errors[0][0], 'Cannot open PDF')
        self.assertFalse(self.controller.review.hasImage)

    def test_drop_message_mentions_pdf(self):
        messages = []
        self.controller.alerts.info = lambda *args, **kwargs: messages.append(args)
        path = Path(self.temporary.name) / 'notes.txt'
        path.write_text('not an image')
        self.controller.openDropped([QUrl.fromLocalFile(str(path))])
        self.assertTrue(messages)
        self.assertIn('PDF', messages[0][1])

    def test_pdf_navigation_updates_page_and_size(self):
        self.open_pdf()
        first_size = self.controller.session.review.image.size
        self.controller.review.nextPdfPage()
        self.assertEqual(self.controller.review.pdfPage, 2)
        self.assertEqual(self.controller.review.pdfPageCount, 2)
        self.assertEqual(self.controller.session.review.image.size, first_size)
        self.controller.review.previousPdfPage()
        self.assertEqual(self.controller.review.pdfPage, 1)

    def test_pdf_pages_keep_their_own_boxes(self):
        self.open_pdf()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Page one')
        self.controller.review.nextPdfPage()
        self.controller.session.review.boxset.add((30, 30, 40, 40), 'Page two A')
        self.controller.session.review.boxset.add((50, 50, 60, 60), 'Page two B')
        self.controller.review.previousPdfPage()
        self.assertEqual(len(self.controller.session.review.boxes), 1)
        self.controller.review.nextPdfPage()
        self.assertEqual(len(self.controller.session.review.boxes), 2)

    def test_pdf_pages_keep_confirmed_state(self):
        self.open_pdf()
        self.controller.review.confirmSelection()
        self.assertTrue(self.controller.session.review.confirmed)
        self.controller.review.nextPdfPage()
        self.assertFalse(self.controller.session.review.confirmed)
        self.controller.review.previousPdfPage()
        self.assertTrue(self.controller.session.review.confirmed)

    def test_pdf_navigation_stops_at_the_ends(self):
        self.open_pdf()
        self.assertFalse(self.controller.review.canPreviousPdfPage)
        self.assertTrue(self.controller.review.canNextPdfPage)
        self.controller.review.nextPdfPage()
        self.assertFalse(self.controller.review.canNextPdfPage)
        self.controller.review.nextPdfPage()
        self.assertEqual(self.controller.review.pdfPage, 2)

    def test_pdf_can_jump_to_a_page(self):
        self.open_pdf()
        self.controller.review.goToPdfPage(2)
        self.assertEqual(self.controller.review.pdfPage, 2)
        self.controller.review.goToPdfPage(1)
        self.assertEqual(self.controller.review.pdfPage, 1)

    def test_loading_an_image_clears_pdf_state(self):
        self.open_pdf()
        self.open_image()
        self.assertFalse(self.controller.review.isPdf)
        self.assertEqual(self.controller.review.pdfPageCount, 0)

    def test_pdf_blank_page_scans_to_zero_without_error(self):
        self.open_pdf()
        with patch.object(self.controller.session, 'scan_engine', return_value=FakeEngine()):
            self.controller.review.start_single_scan()
            self.wait_for_jobs()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.controller.review.totalBoxes, 0)

    def test_unsaved_pdf_work_reports_boxes_on_any_page(self):
        self.open_pdf()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Page one')
        self.controller.review.nextPdfPage()
        self.assertTrue(self.controller.review.unsaved_pdf_work())
        self.controller.review.previousPdfPage()
        self.controller.session.review.boxset.clear()
        self.assertFalse(self.controller.review.unsaved_pdf_work())

    def test_pdf_current_page_markings_prompt_once(self):
        self.open_pdf()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Current page')
        image_path = Path(self.temporary.name) / 'replacement.png'
        Image.new('RGB', (80, 60), 'white').save(image_path)
        asks = []
        self.controller.alerts.ask = lambda *args, **kwargs: asks.append(args) or True
        with patch.object(self.controller, '_choose_image', return_value=image_path) as choose:
            self.controller.openImage()
        choose.assert_called_once()
        self.assertEqual(len(asks), 1)
        self.assertNotIn('another page', asks[0][1])
        self.assertFalse(self.controller.review.isPdf)

    def test_open_folder_prompts_once_for_unsaved_work(self):
        folders = []
        for name in ('first', 'second'):
            folder = Path(self.temporary.name) / name
            folder.mkdir()
            Image.new('RGB', (80, 60), 'white').save(folder / 'one.png')
            folders.append(folder)
        with patch.object(self.controller, '_choose_folder', return_value=folders[0]):
            self.controller.openFolder()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Unsaved')
        asks = []
        self.controller.alerts.ask = lambda *args, **kwargs: asks.append(args) or True
        with patch.object(self.controller, '_choose_folder', return_value=folders[1]):
            self.controller.openFolder()
        self.assertEqual(len(asks), 1)

    def test_opening_an_image_prompts_when_pdf_has_markings(self):
        self.open_pdf()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Page one')
        self.controller.review.nextPdfPage()
        image_path = Path(self.temporary.name) / 'replacement.png'
        Image.new('RGB', (80, 60), 'white').save(image_path)
        self.controller.alerts.ask = lambda *args, **kwargs: False
        with patch.object(self.controller, '_choose_image') as choose:
            self.controller.openImage()
        choose.assert_not_called()
        self.assertTrue(self.controller.review.isPdf)
        self.controller.alerts.ask = lambda *args, **kwargs: True
        with patch.object(self.controller, '_choose_image', return_value=image_path):
            self.controller.openImage()
        self.assertFalse(self.controller.review.isPdf)

    def test_pdf_only_folder_reports_the_image_only_boundary(self):
        folder = Path(self.temporary.name) / 'pdfs'
        folder.mkdir()
        write_pdf(folder / 'only.pdf')
        messages = []
        self.controller.alerts.info = lambda *args, **kwargs: messages.append(args)
        with patch.object(self.controller, '_choose_folder', return_value=folder):
            self.controller.openFolder()
        self.assertTrue(messages)
        self.assertIn('PDF', messages[0][1])
        self.assertIn('one file at a time', messages[0][1])

    def test_folder_open_does_not_list_pdfs(self):
        folder = Path(self.temporary.name) / 'mixed'
        folder.mkdir()
        Image.new('RGB', (80, 60), 'white').save(folder / 'one.png')
        write_pdf(folder / 'ignored.pdf')
        with patch.object(self.controller, '_choose_folder', return_value=folder):
            self.controller.openFolder()
        self.assertEqual(len(self.controller.session.entries), 1)
        self.assertEqual(self.controller.session.entries[0].path.name, 'one.png')

    def test_pdf_page_export_uses_page_specific_name_and_log(self):
        self.open_pdf()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Account')
        self.controller.review.confirmSelection()
        target = Path(self.temporary.name) / 'two-pages_page-001_redacted.png'
        with patch('markseal.facades.review.QFileDialog.getSaveFileName',
                   return_value=(str(target), 'PNG image (*.png)')) as dialog:
            self.controller.review.save_single()
        self.assertEqual(self.errors, [])
        self.assertEqual(dialog.call_args.args[2], 'two-pages_page-001_redacted.png')
        self.assertTrue(target.is_file())
        log = json.loads(target.with_suffix('.redactions.json').read_text(encoding='utf-8'))
        self.assertEqual(log['source_page'], 1)

    def test_image_export_does_not_add_source_page(self):
        source = self.open_image()
        self.controller.session.review.boxset.add((10, 10, 20, 20), 'Account')
        self.controller.review.confirmSelection()
        target = Path(self.temporary.name) / 'screenshot_redacted.png'
        with patch('markseal.facades.review.QFileDialog.getSaveFileName',
                   return_value=(str(target), 'PNG image (*.png)')):
            self.controller.review.save_single()
        self.assertEqual(self.errors, [])
        log = json.loads(target.with_suffix('.redactions.json').read_text(encoding='utf-8'))
        self.assertNotIn('source_page', log)

    def test_verify_is_unavailable_for_pdf(self):
        self.open_pdf()
        messages = []
        self.controller.alerts.info = lambda *args, **kwargs: messages.append(args)
        self.controller.review.verifyCurrent()
        self.assertEqual(self.errors, [])
        self.assertTrue(messages)
        self.assertIn('PDF page exports', messages[0][1])
        self.assertIsNone(self.controller.review.last_verify)

    def test_blank_pdf_page_can_be_saved_after_confirmation(self):
        self.open_pdf()
        self.controller.review.confirmSelection()
        target = Path(self.temporary.name) / 'blank_page-001_redacted.png'
        with patch('markseal.facades.review.QFileDialog.getSaveFileName',
                   return_value=(str(target), 'PNG image (*.png)')):
            self.controller.review.save_single()
        self.assertEqual(self.errors, [])
        self.assertTrue(target.is_file())

    def test_close_protects_unsaved_boxes(self):
        self.open_image()
        self.controller.session.review.boxes = [(0, 0, 10, 10)]
        self.controller.session.review.selected = {0}
        asked = []
        self.controller.alerts.ask = (
            lambda title, text: asked.append((title, text)) or False
        )
        self.assertFalse(self.controller.canClose())
        self.assertEqual(asked[0][0], 'Close MarkSeal?')
        self.controller.alerts.ask = lambda *args, **kwargs: True
        self.assertTrue(self.controller.canClose())
        self.controller.review.last_export = Path(self.temporary.name) / 'export.png'
        self.assertTrue(self.controller.canClose())

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
        root = engine.rootObjects()[0]
        bar = root.findChild(QObject, 'pdfBar')
        label = root.findChild(QObject, 'pdfPageLabel')
        self.assertIsNotNone(bar)
        self.assertIsNotNone(label)
        self.assertFalse(bar.property('visible'))
        path = Path(self.temporary.name) / 'two-pages.pdf'
        write_pdf(path)
        self.controller._review.load_pdf(path)
        self.app.processEvents()
        self.assertTrue(bar.property('visible'))
        self.assertEqual(label.property('text'), 'PAGE 1 / 2')
        self.controller.review.nextPdfPage()
        self.app.processEvents()
        self.assertEqual(label.property('text'), 'PAGE 2 / 2')


if __name__ == '__main__':
    unittest.main()
