from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    Property, QBuffer, QIODevice, QObject, QTimer, QUrl, Signal, Slot,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from . import documents, images
from .facades import (
    Alerts, BatchFacade, FolderFacade, JobCenter, ReviewFacade, SessionState,
    SettingsFacade, UpdateFacade, WatchFacade,
)
from .ui.models import DisplayImageProvider


def _pil_from_qimage(qimage):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    qimage.save(buffer, 'PNG')
    raw = bytes(buffer.data())
    buffer.close()
    with Image.open(io.BytesIO(raw)) as source:
        return source.convert('RGB')


class Controller(QObject):
    statusChanged = Signal()
    errorChanged = Signal()

    def __init__(self, preferences_file=None, parent=None):
        super().__init__(parent)
        self.session = SessionState(preferences_file)
        self.alerts = Alerts(self)
        self.jobs = JobCenter(self.session, self)
        self.session.alerts = self.alerts
        self.session.jobs = self.jobs
        self._settings = SettingsFacade(self.session, self.alerts, self)
        self._review = ReviewFacade(self.session, self.alerts, self)
        self._folder = FolderFacade(self.session, self.alerts, self)
        self._batch = BatchFacade(self.session, self.alerts, self)
        self._updates = UpdateFacade(self.session, self.alerts, self)
        self.session.facades.settings = self._settings
        self.session.facades.review = self._review
        self.session.facades.folder = self._folder
        self._watches = WatchFacade(self.session, self.alerts, self)
        self._watches.batch = self._batch
        self.session.facades.watches = self._watches
        self._review.batch = self._batch
        self._settings.on_method_changed = self._review.method_changed
        self._settings.retry_learn = self._review.beginLearnPattern
        self.alerts.statusChanged.connect(self.statusChanged)
        self.alerts.errorChanged.connect(self.errorChanged)
        self.jobs.jobStatesQueued.connect(self._folder.set_job_states)
        self.jobs.jobStarted.connect(
            lambda row: self._folder.set_job_state(row, 'running'))
        self.jobs.jobCleared.connect(
            lambda row: self._folder.set_job_state(row, ''))
        self.jobs.jobStatesCleared.connect(self._folder.clear_job_states)
        self.jobs.rowsChanged.connect(self._folder.refresh_and_emit)
        self._review.reviewChanged.connect(self._folder.refresh_and_emit)
        self._folder.selectionChanged.connect(self._review.selection_changed)
        self.jobs.before_start = self._review.cancel_capture
        self._settings.load_preferences()
        self._updates.check()
        if not self.alerts.status_text:
            self.alerts.set_status('Ready. No screenshot open.')
        QTimer.singleShot(0, self._watches.start)

    @Property(QObject, constant=True)
    def settings(self):
        return self._settings

    @Property(QObject, constant=True)
    def review(self):
        return self._review

    @Property(QObject, constant=True)
    def folder(self):
        return self._folder

    @Property(QObject, constant=True)
    def batch(self):
        return self._batch

    @Property(QObject, constant=True)
    def updates(self):
        return self._updates

    @Property(QObject, constant=True)
    def watches(self):
        return self._watches

    def display_qimage(self):
        return self._review.display_qimage()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self.alerts.status_text

    @Property(str, notify=errorChanged)
    def errorText(self):
        return self.alerts.error_text

    @Property(str, notify=errorChanged)
    def errorDetail(self):
        return self.alerts.error_detail

    @Property(str, notify=errorChanged)
    def errorActionText(self):
        return self.alerts.error_action_text

    @Slot()
    def dismissError(self):
        self.alerts.dismiss()

    @Slot()
    def runErrorAction(self):
        self.alerts.run_action()

    @Slot(result=bool)
    def canClose(self):
        if self.jobs.busy:
            return self.alerts.ask(
                'Close MarkSeal?',
                'A job is still running. Close MarkSeal anyway?',
            )
        if self._review.isPdf and self._review.unsaved_pdf_work() \
                and self._review.last_export is None:
            return self.alerts.ask(
                'Discard PDF markings?',
                'This PDF has unsaved markings. Close and discard them?',
            )
        pending = [
            entry for entry in self.session.entries
            if not entry.saved and (entry.boxes or entry.reviewed)
        ]
        if pending:
            count = len(pending)
            message = ('1 image has unsaved review work. Close and discard it?'
                       if count == 1 else
                       f'{count} images have unsaved review work. Close and discard it?')
            return self.alerts.ask('Close MarkSeal?', message)
        if not self.session.entries and self.session.review.boxes \
                and self._review.last_export is None:
            return self.alerts.ask(
                'Close MarkSeal?',
                'The current image has unsaved markings. Close and discard them?',
            )
        return True

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            None, 'Open image', '',
            'Images and PDFs (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.pdf);;'
            'Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;'
            'PDF documents (*.pdf);;All files (*.*)',
        )
        return Path(path) if path else None

    def _choose_folder(self, title):
        path = QFileDialog.getExistingDirectory(None, title)
        return Path(path) if path else None

    def _prepare_image_open(self, check_folder=True):
        if self.jobs.busy:
            return False
        if check_folder and not self._folder.can_leave():
            return False
        if self._review.isPdf:
            if self._review.unsaved_pdf_work():
                if not self.alerts.ask(
                        'Discard PDF markings?',
                        'This PDF has unsaved markings. Discard them?'):
                    return False
        elif not self.session.entries and self.session.review.boxes:
            if not self.alerts.ask('Open another image', 'Discard the current unsaved markings?'):
                return False
        return True

    def _present_image(self, image, path, pasted=False):
        self._review.cancel_capture()
        if self._folder.has_entries():
            self._folder.clear()
        self._review.load_image(image, path, pasted=pasted)
        self.alerts.set_status(
            f'{self._review.imageName}: scan the image or drag to add a box, then confirm.'
        )

    @Slot()
    def openImage(self):
        if not self._prepare_image_open():
            return
        chosen = self._choose_image()
        if chosen is None:
            return
        if chosen.suffix.lower() in documents.PDF_SUFFIXES:
            self._load_pdf(chosen)
            return
        try:
            with Image.open(chosen) as source:
                image = source.convert('RGB')
        except Exception as error:
            self.alerts.error('Cannot open image', str(error))
            return
        self._present_image(image, chosen)

    def _load_pdf(self, path):
        try:
            self._review.load_pdf(path)
        except documents.PdfError as error:
            self.alerts.error('Cannot open PDF', str(error))
            return False
        self.alerts.set_status(
            f'{path.name} · PDF · page 1 of {self._review.pdfPageCount}. Review the page.'
        )
        return True

    @Slot()
    def openFolder(self):
        if self.jobs.busy:
            return
        if not self._prepare_image_open(check_folder=False):
            return
        chosen = self._choose_folder('Open image folder')
        if chosen is None:
            return
        self._folder.open_path(chosen)

    @Slot('QVariantList')
    def openDropped(self, urls):
        if self.jobs.busy:
            return
        paths = []
        for value in urls or []:
            url = value if isinstance(value, QUrl) else QUrl(str(value))
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        supported = [path for path in paths
                     if path.is_file() and (path.suffix.lower() in images.IMAGE_SUFFIXES
                                             or path.suffix.lower() in documents.PDF_SUFFIXES)]
        if supported:
            if not self._prepare_image_open():
                return
            candidate = supported[0]
            if candidate.suffix.lower() in documents.PDF_SUFFIXES:
                self._load_pdf(candidate)
                return
            try:
                with Image.open(candidate) as source:
                    image = source.convert('RGB')
            except Exception as error:
                self.alerts.error('Cannot open image', str(error))
                return
            self._present_image(image, candidate)
            return
        folders = [path for path in paths if path.is_dir()]
        if folders:
            if not self._prepare_image_open(check_folder=False):
                return
            self._folder.open_path(folders[0])
            return
        self.alerts.info('Drop an image or PDF',
                         'Drop a PNG, JPEG, BMP, TIFF, or PDF file, or an image folder.')

    def _clipboard_image(self):
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

    @Slot()
    def pasteImage(self):
        if self.jobs.busy:
            return
        try:
            loaded = self._clipboard_image()
        except Exception as error:
            self.alerts.error('Cannot paste image', str(error))
            return
        if loaded is None:
            self.alerts.info('Paste image', 'The clipboard does not contain an image.')
            return
        if not self._prepare_image_open():
            return
        image, path, pasted = loaded
        self._present_image(image, path, pasted=pasted)

    def _grab_screen_region(self, x, y, width, height):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        pixmap = screen.grabWindow(0, int(x), int(y), int(width), int(height))
        return None if pixmap.isNull() else pixmap.toImage()

    @Slot(int, int, int, int)
    def captureRegion(self, x, y, width, height):
        if not self._prepare_image_open():
            return
        qimage = self._grab_screen_region(x, y, width, height)
        if qimage is None or qimage.isNull():
            self.alerts.set_status(
                'Screen capture is unavailable on this display. Use Open image instead.'
            )
            return
        self._present_image(_pil_from_qimage(qimage), Path('captured-region.png'), pasted=True)
