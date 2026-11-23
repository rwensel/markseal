"""Bounded background jobs and the busy/progress board state."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, QTimer, Signal

from ..jobs import JobRunner, progress_line


class JobCenter(QObject):
    busyChanged = Signal()
    progressChanged = Signal()
    scanStageChanged = Signal()
    jobStatesQueued = Signal(object)
    jobStarted = Signal(object)
    jobCleared = Signal(object)
    jobStatesCleared = Signal()
    rowsChanged = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self._busy = False
        self._busy_label = ''
        self._progress_text = 'Ready'
        self._progress_value = 0
        self._progress_max = 1
        self._progress_detail = ''
        self._progress_current = ''
        self._scan_stage = ''
        self._runner = JobRunner(session.parallel_limit)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        self.before_start = None

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(str, notify=busyChanged)
    def busyLabel(self):
        return self._busy_label

    @Property(bool, notify=busyChanged)
    def canCancel(self):
        return self._runner.can_cancel

    @Property(str, notify=progressChanged)
    def progressText(self):
        return self._progress_text

    @Property(int, notify=progressChanged)
    def progressValue(self):
        return self._progress_value

    @Property(int, notify=progressChanged)
    def progressMax(self):
        return self._progress_max

    @Property(str, notify=progressChanged)
    def progressDetail(self):
        return self._progress_detail

    @Property(str, notify=progressChanged)
    def progressCurrent(self):
        return self._progress_current

    @Property(str, notify=scanStageChanged)
    def scanStage(self):
        return self._scan_stage

    def set_scan_stage(self, text):
        if self._scan_stage != text:
            self._scan_stage = text
            self.scanStageChanged.emit()

    def begin_manual(self, label):
        self._busy = True
        self._busy_label = label
        self.busyChanged.emit()

    def end_manual(self):
        self._busy = False
        self._busy_label = ''
        self.busyChanged.emit()

    def cancel(self):
        if self._runner.cancel():
            self._progress_text = 'Canceling scan…'
            self.progressChanged.emit()

    def run(self, label, jobs, operation, accept, finish=None, *, cancel=None,
            show_image=None, metrics_settings=None, rows=None, workers=None,
            stage_queue=None, complete=None, report_failures=True):
        if not jobs or self._busy:
            return
        if self.before_start is not None:
            self.before_start()
        requested = self.session.preferences.parallel_images if workers is None else workers
        if not self._runner.start(
                label, jobs, operation, accept, finish,
                cancel=cancel, show_image=show_image, metrics_settings=metrics_settings,
                rows=rows, workers=requested, stage_queue=stage_queue,
                complete=complete, report_failures=report_failures):
            return
        runner = self._runner
        self._busy = True
        self._busy_label = label
        self._progress_max = runner.total
        self._progress_value = 0
        self._progress_detail = ''
        self._progress_current = ''
        self.set_scan_stage('')
        self.jobStatesQueued.emit(
            {row: 'queued' for row in runner.job_rows if row is not None}
        )
        self.busyChanged.emit()
        self.progressChanged.emit()
        if not runner.paced:
            self.show_progress(label, 0, runner.total, runner.jobs, runner.workers)
        self._timer.start()
        if runner.paced:
            self.show_next_if_current(runner.generation)

    def show_progress(self, label, completed, total, jobs, workers=1):
        text, current = progress_line(label, completed, total, jobs, workers)
        self._progress_max = total
        self._progress_value = completed
        self._progress_text = text
        if current:
            self._progress_current = current
        self.progressChanged.emit()

    def show_next_if_current(self, generation):
        runner = self._runner
        if runner.next_paced(generation) is None:
            return
        self.show_progress(runner.label, runner.completed, runner.total,
                           runner.jobs, runner.workers)
        runner.release_paced(generation)

    def _poll(self):
        events = self._runner.poll()
        if events is None:
            self._timer.stop()
            return
        for text in events.stages:
            self.set_scan_stage(text)
        for row in events.started:
            self.jobStarted.emit(row)
        for row in events.result_rows:
            self.jobCleared.emit(row)
        if events.finished:
            self._finish(events.summary)
            return
        if not events.progress_changed:
            return
        self.rowsChanged.emit()
        runner = self._runner
        if runner.completed >= runner.total or runner.cancel_pending:
            return
        if not runner.paced:
            self.show_progress(runner.label, runner.completed, runner.total,
                               runner.jobs, runner.workers)
            return
        percent = runner.completed * 100 // runner.total
        self._progress_value = runner.completed
        self._progress_text = (f'{runner.label} · {runner.completed}/{runner.total} '
                               f'processed ({percent}%)')
        self.progressChanged.emit()
        generation = runner.generation
        QTimer.singleShot(250, lambda: self.show_next_if_current(generation))

    def _finish(self, summary):
        self._timer.stop()
        self.jobStatesCleared.emit()
        self._busy = False
        self._busy_label = ''
        self.rowsChanged.emit()
        self._progress_max = summary.total
        self._progress_value = summary.completed
        self._progress_current = ''
        self.set_scan_stage('')
        self._progress_text, self._progress_detail = summary.lines()
        self.busyChanged.emit()
        self.progressChanged.emit()
        if summary.failures and summary.report_failures:
            self.session.alerts.error(
                f'{summary.label} issues',
                f'{len(summary.failures)} of {summary.total} failed. '
                f'First error: {summary.failures[0]}',
            )
        if summary.complete is not None:
            summary.complete()
