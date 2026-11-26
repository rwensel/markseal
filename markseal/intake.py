from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, QUrl
from PySide6.QtGui import QGuiApplication

from . import documents, images


def image_from_qimage(qimage):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    qimage.save(buffer, 'PNG')
    raw = bytes(buffer.data())
    buffer.close()
    with Image.open(io.BytesIO(raw)) as source:
        return source.convert('RGB')


class Intake:
    def __init__(self, owner):
        self.owner = owner

    def prepare_image_open(self, check_folder=True):
        owner = self.owner
        if owner.jobs.busy:
            return False
        if check_folder and not owner._folder.can_leave():
            return False
        if owner._review.isPdf:
            if owner._review.unsaved_pdf_work():
                if not owner.alerts.ask(
                        'Discard PDF markings?',
                        'This PDF has unsaved markings. Discard them?'):
                    return False
        elif not owner.session.entries and owner.session.review.boxes:
            if not owner.alerts.ask(
                    'Open another image',
                    'Discard the current unsaved markings?'):
                return False
        return True

    def present_image(self, image, path, pasted=False):
        owner = self.owner
        owner._review.cancel_capture()
        if owner._folder.has_entries():
            owner._folder.clear()
        owner._review.load_image(image, path, pasted=pasted)
        owner.alerts.set_status(
            f'{owner._review.imageName}: scan the image or drag to add a box, then confirm.'
        )

    def open_image(self):
        owner = self.owner
        if not self.prepare_image_open():
            return
        chosen = owner._choose_image()
        if chosen is None:
            return
        if chosen.suffix.lower() in documents.PDF_SUFFIXES:
            self.load_pdf(chosen)
            return
        try:
            with Image.open(chosen) as source:
                image = source.convert('RGB')
        except Exception as error:
            owner.alerts.error('Cannot open image', str(error))
            return
        self.present_image(image, chosen)

    def load_pdf(self, path):
        owner = self.owner
        try:
            owner._review.load_pdf(path)
        except documents.PdfError as error:
            owner.alerts.error('Cannot open PDF', str(error))
            return False
        owner.alerts.set_status(
            f'{path.name} · PDF · page 1 of {owner._review.pdfPageCount}. Review the page.'
        )
        return True

    def open_folder(self):
        owner = self.owner
        if owner.jobs.busy:
            return
        if not self.prepare_image_open(check_folder=False):
            return
        chosen = owner._choose_folder('Open image folder')
        if chosen is None:
            return
        owner._folder.open_path(chosen)

    def open_dropped(self, urls):
        owner = self.owner
        if owner.jobs.busy:
            return
        paths = []
        for value in urls or []:
            url = value if isinstance(value, QUrl) else QUrl(str(value))
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        supported = [
            path for path in paths
            if path.is_file() and (
                path.suffix.lower() in images.IMAGE_SUFFIXES
                or path.suffix.lower() in documents.PDF_SUFFIXES
            )
        ]
        if supported:
            if not self.prepare_image_open():
                return
            candidate = supported[0]
            if candidate.suffix.lower() in documents.PDF_SUFFIXES:
                self.load_pdf(candidate)
                return
            try:
                with Image.open(candidate) as source:
                    image = source.convert('RGB')
            except Exception as error:
                owner.alerts.error('Cannot open image', str(error))
                return
            self.present_image(image, candidate)
            return
        folders = [path for path in paths if path.is_dir()]
        if folders:
            if not self.prepare_image_open(check_folder=False):
                return
            owner._folder.open_path(folders[0])
            return
        owner.alerts.info(
            'Drop an image or PDF',
            'Drop a PNG, JPEG, BMP, TIFF, or PDF file, or an image folder.',
        )

    def clipboard_image(self):
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        if data.hasUrls():
            for url in data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_file() and path.suffix.lower() in images.IMAGE_SUFFIXES:
                        with Image.open(path) as source:
                            return source.convert('RGB'), path, False
        if data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, 'PNG')
                raw = bytes(buffer.data())
                buffer.close()
                with Image.open(io.BytesIO(raw)) as source:
                    return source.convert('RGB'), Path('pasted-image.png'), True
        return None

    def paste_image(self):
        owner = self.owner
        if owner.jobs.busy:
            return
        try:
            loaded = self.clipboard_image()
        except Exception as error:
            owner.alerts.error('Cannot paste image', str(error))
            return
        if loaded is None:
            owner.alerts.info('Paste image', 'The clipboard does not contain an image.')
            return
        if not self.prepare_image_open():
            return
        image, path, pasted = loaded
        self.present_image(image, path, pasted=pasted)

    def grab_screen_region(self, x, y, width, height):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        pixmap = screen.grabWindow(0, int(x), int(y), int(width), int(height))
        return None if pixmap.isNull() else pixmap.toImage()

    def capture_region(self, x, y, width, height):
        owner = self.owner
        if not self.prepare_image_open():
            return
        qimage = owner._grab_screen_region(x, y, width, height)
        if qimage is None or qimage.isNull():
            owner.alerts.set_status(
                'Screen capture is unavailable on this display. Use Open image instead.'
            )
            return
        self.present_image(
            image_from_qimage(qimage), Path('captured-region.png'), pasted=True)
