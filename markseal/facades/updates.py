"""Update checks and downloads, kept off the UI thread."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, QRunnable, QThreadPool, Signal, Slot

from .. import updates


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(float)


class _Job(QRunnable):
    def __init__(self, work):
        super().__init__()
        self._work = work
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self._work(self.signals.progress.emit))
        except updates.UpdateError as error:
            self.signals.failed.emit(str(error))


class UpdateFacade(QObject):
    availableChanged = Signal()
    failedChanged = Signal()
    stateChanged = Signal()

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self._info = None
        self._installer = None
        self._error = ''
        self._jobs = 0
        self._pending = None

    @Property(str, constant=True)
    def currentVersion(self):
        return updates.__version__

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._jobs > 0

    @Property(bool, notify=availableChanged)
    def hasUpdate(self):
        return self._info is not None

    @Property('QVariantMap', notify=availableChanged)
    def updateInfo(self):
        if self._info is None:
            return {}
        return {'version': self._info.version, 'notes': self._info.notes,
                'pageUrl': self._info.page_url}

    @Property(str, notify=failedChanged)
    def errorText(self):
        return self._error

    @Property(bool, notify=stateChanged)
    def readyToInstall(self):
        return self._installer is not None

    @Slot()
    def check(self):
        if not self.session.preferences.check_for_updates or self._jobs:
            return
        self._run(lambda progress: updates.check_for_update(), self._found)

    @Slot()
    def download(self):
        if self._info is None or self._jobs:
            return
        info = self._info
        self._run(lambda progress: updates.download_update(info, progress=progress),
                  self._downloaded)

    @Slot()
    def install(self):
        if self._installer is None:
            self.download()
            return
        try:
            updates.launch_installer(self._installer)
        except updates.UpdateError as error:
            self._failed(str(error))

    @Slot()
    def dismiss(self):
        self._info = None
        self._installer = None
        self._error = ''
        self.availableChanged.emit()
        self.stateChanged.emit()

    def _run(self, work, on_done):
        self._jobs += 1
        self.stateChanged.emit()
        job = _Job(work)
        job.setAutoDelete(False)
        job.signals.done.connect(on_done)
        job.signals.done.connect(self._finish)
        job.signals.failed.connect(self._failed)
        job.signals.failed.connect(self._finish)
        self._pending = job
        QThreadPool.globalInstance().start(job)

    def _found(self, info):
        self._error = ''
        self.failedChanged.emit()
        if info is not None:
            self._info = info
            self.availableChanged.emit()
            if self.session.preferences.download_updates_automatically:
                self.download()

    def _downloaded(self, path):
        self._installer = path
        self.stateChanged.emit()

    def _failed(self, message):
        self._error = message
        self.failedChanged.emit()

    def _finish(self, *_):
        self._pending = None
        self._jobs = max(0, self._jobs - 1)
        self.stateChanged.emit()
