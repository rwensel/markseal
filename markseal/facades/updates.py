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
        except Exception as error:  # A worker error must still finish the job bookkeeping.
            self.signals.failed.emit(str(error) or error.__class__.__name__)


class UpdateFacade(QObject):
    availableChanged = Signal()
    failedChanged = Signal()
    stateChanged = Signal()
    progressChanged = Signal()
    statusChanged = Signal()

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self._info = None
        self._installer = None
        self._error = ''
        self._jobs = 0
        self._pending = None
        self._progress = 0.0
        self._status = ''

    @Property(str, constant=True)
    def currentVersion(self):
        return updates.__version__

    @Property(str, constant=True)
    def platform(self):
        return updates.platform_key()

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

    @Property(float, notify=progressChanged)
    def progress(self):
        return self._progress

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=stateChanged)
    def readyToInstall(self):
        return self._installer is not None

    @Slot()
    def check(self):
        if not self.session.preferences.check_for_updates or self._jobs:
            return
        channel = 'beta' if self.session.preferences.beta_channel else 'stable'
        url = updates.manifest_url(channel)
        self._set_status('Checking for updates…')
        self._run(lambda progress: updates.check_for_update(url=url), self._found)

    @Slot()
    def download(self):
        if self._info is None or self._jobs:
            return
        info = self._info
        self._set_progress(0.0)
        self._set_status('Downloading update… 0%')
        self._run(lambda progress: updates.download_update(info, progress=progress),
                  self._downloaded)

    @Slot()
    def install(self):
        if self._installer is None:
            self.download()
            return
        try:
            updates.launch_installer(self._installer)
            self._set_status('Installer launched.')
        except updates.UpdateError as error:
            self._failed(str(error))

    @Slot()
    def dismiss(self):
        self._info = None
        self._installer = None
        self._error = ''
        self._set_progress(0.0)
        self._set_status('')
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
        job.signals.progress.connect(self._progress_update)
        self._pending = job
        QThreadPool.globalInstance().start(job)

    def _found(self, info):
        self._error = ''
        self.failedChanged.emit()
        if info is not None:
            self._info = info
            self.availableChanged.emit()
            self._set_status(f'Update {info.version} is available.')
            if self.session.preferences.download_updates_automatically:
                self.download()
        else:
            self._set_status(f'MarkSeal {self.currentVersion} is up to date.')

    def _downloaded(self, path):
        self._installer = path
        self._set_progress(1.0)
        self._set_status('Update downloaded. Press INSTALL to run it.')
        self.stateChanged.emit()

    def _failed(self, message):
        self._error = message
        self.failedChanged.emit()
        self._set_status('Update failed: ' + message)
        self.alerts.set_status('Update failed: ' + message)

    def _progress_update(self, value):
        self._set_progress(value)
        self._set_status(f'Downloading update… {int(self._progress * 100)}%')

    def _set_progress(self, value):
        value = max(0.0, min(1.0, float(value)))
        if value != self._progress:
            self._progress = value
            self.progressChanged.emit()

    def _set_status(self, text):
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    def _finish(self, *_):
        self._pending = None
        self._jobs = max(0, self._jobs - 1)
        self.stateChanged.emit()
