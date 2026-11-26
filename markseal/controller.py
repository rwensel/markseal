from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .facades import (
    Alerts, BatchFacade, FolderFacade, JobCenter, ReviewFacade, SessionState,
    SettingsFacade, UpdateFacade, WatchFacade,
)
from .intake import Intake
from .ui.models import DisplayImageProvider


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
        self._intake = Intake(self)
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
        pending = [entry for entry in self.session.entries if entry.unsaved]
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

    def _present_image(self, image, path, pasted=False):
        self._intake.present_image(image, path, pasted=pasted)

    def _grab_screen_region(self, x, y, width, height):
        return self._intake.grab_screen_region(x, y, width, height)

    @Slot()
    def openImage(self):
        self._intake.open_image()

    @Slot()
    def openFolder(self):
        self._intake.open_folder()

    @Slot('QVariantList')
    def openDropped(self, urls):
        self._intake.open_dropped(urls)

    @Slot()
    def pasteImage(self):
        self._intake.paste_image()

    @Slot(int, int, int, int)
    def captureRegion(self, x, y, width, height):
        self._intake.capture_region(x, y, width, height)
