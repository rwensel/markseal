from __future__ import annotations

import re
from threading import Event

from PySide6.QtCore import QObject, Signal

from .. import boxset, export, ocr, workflows
from .. import watches as watch_store
from ..jobs import ScanCancelled
from .activity import JobCenter

AUTO_LABEL = 'Auto-redacting'
PAUSED = 'paused'


class AutomaticLane(QObject):
    changed = Signal()
    recordsChanged = Signal()

    def __init__(self, session, alerts, store, persist, update_counts, counts_for,
                 parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self.store = store
        self._persist = persist
        self._update_counts = update_counts
        self._counts_for = counts_for
        self.hold = False
        self.stopped = False
        self._status = ''
        self.jobs = JobCenter(session, self)
        self.jobs.busyChanged.connect(self.changed)
        self.jobs.busyChanged.connect(self.dispatch)
        self.jobs.progressChanged.connect(self.changed)

    @property
    def busy(self):
        return self.jobs.busy

    @property
    def status(self):
        if self.jobs.busy:
            return self.jobs.progressText
        if self.stopped:
            waiting = sum(self._counts_for(watch).queued for watch in self.store.folders)
            if waiting:
                return f'Stopped · {waiting} waiting · PROCESS EXISTING to resume'
        return self._status

    def reset_hold(self):
        self.hold = False

    def clear_stop(self):
        self.stopped = False

    def cancel(self):
        self.stopped = True
        self.jobs.cancel()
        self.changed.emit()

    def pause(self):
        self.hold = True
        self.jobs.cancel()
        self.changed.emit()

    def resume(self):
        self.hold = False
        self.stopped = False
        self._status = ''
        self.changed.emit()
        self.dispatch()

    def dispatch(self):
        if self.hold or self.stopped or self.jobs.busy or self.session.jobs.busy:
            return
        candidates = []
        for watch in list(self.store.folders):
            if watch.policy != 'automatic' or self._watch_open(watch):
                continue
            found = []
            names = set()
            for path in watch_store.pending_queued(self.store, watch):
                if path not in names:
                    names.add(path)
                    found.append(path)
            for path in watch_store.unseen(self.store, watch):
                if path not in names:
                    names.add(path)
                    found.append(path)
            candidates.extend((watch, path) for path in found)
        if not candidates:
            return
        jobs = []
        for watch, path in candidates:
            try:
                watch_store.mark(self.store, watch, path, state=watch_store.QUEUED)
            except OSError:
                continue
            jobs.append((watch, path))
        if not jobs:
            return
        self._status = ''
        self.changed.emit()
        touched = {}
        for watch, _path in jobs:
            touched[watch_store.key(watch.path)] = watch
        for watch in touched.values():
            self._update_counts(watch)
        self._persist()
        self.recordsChanged.emit()
        try:
            engine = self.session.scan_engine()
            settings = self.session.scan_settings()
        except OSError as error:
            self._records_failed(jobs, str(error))
            self.alerts.error('OCR unavailable', str(error), 'RETRY',
                              lambda: self._retry(jobs))
            return
        except (ValueError, re.error) as error:
            self._records_failed(jobs, str(error))
            self.alerts.error('Invalid detection settings', str(error), 'OPEN SETTINGS',
                              self.session.facades.settings.requestSettings)
            return
        preferences = self.session.preferences
        enhanced = preferences.enhanced_ocr
        color_assisted = preferences.color_ocr
        method = preferences.method
        template = preferences.filename_template
        include_log = preferences.include_log
        cancel = Event()
        self._status = ''
        stats = {'exported': 0, 'needs_review': 0}

        def operation(job):
            watch, path = job
            if not self._ready(watch, cancel):
                cancel.set()
                return (path, None, PAUSED, None, '')
            try:
                scanned = ocr.scan_folder_image(
                    path, None, engine, settings, enhanced, cancel,
                    color_assisted=color_assisted,
                )
            except ScanCancelled:
                raise
            except Exception as error:
                return (path, None, watch_store.NEEDS_REVIEW, None, str(error))
            stamp, _found, _incomplete = scanned
            entry = boxset.FolderImage(path, method=method)
            outcome = workflows.apply_scan_result(entry, scanned)
            if outcome.error:
                return (path, stamp, watch_store.NEEDS_REVIEW, None, outcome.error)
            state, detail = watch_store.automatic_outcome(entry)
            target = None
            if state == watch_store.EXPORTED:
                if not self._ready(watch, cancel):
                    cancel.set()
                    return (path, stamp, PAUSED, None, '')
                try:
                    snapshot, with_log = workflows.auto_export_snapshot(
                        entry, watch_store.destination(watch, path),
                        template, include_log)
                    snapshot.target.parent.mkdir(parents=True, exist_ok=True)
                    export.write_copy(snapshot, include_log=with_log)
                except Exception as error:
                    return (path, stamp, watch_store.NEEDS_REVIEW, None, str(error))
                target = str(snapshot.target)
            return (path, stamp, state, target, detail)

        def accept(index, result, error):
            watch, path = jobs[index]
            current = watch_store.find(self.store, watch.path)
            if current is None:
                return
            if error is not None:
                state, target, detail, stamp = watch_store.NEEDS_REVIEW, None, error, None
            else:
                _path, stamp, state, target, detail = result
            if state == PAUSED:
                self.hold = True
                if current.policy != 'automatic' and self._write_record(
                        current, path, watch_store.PRESENTED, stamp=stamp):
                    self._update_counts(current)
                    self._persist()
                    self.recordsChanged.emit()
                return
            if state == watch_store.EXPORTED:
                stats['exported'] += 1
            elif state == watch_store.NEEDS_REVIEW:
                stats['needs_review'] += 1
            if self._write_record(current, path, state, export=target, detail=detail,
                                  stamp=stamp):
                self._update_counts(current)
                self._persist()
                self.recordsChanged.emit()

        def finish():
            waiting = len(jobs) - stats['exported'] - stats['needs_review']
            parts = []
            if stats['exported']:
                parts.append(f'{stats["exported"]} redacted')
            if stats['needs_review']:
                parts.append(f'{stats["needs_review"]} needs review')
            if waiting > 0:
                parts.append(f'{waiting} waiting')
            status = AUTO_LABEL + (' stopped' if cancel.is_set() else ' finished')
            if parts:
                status += ' · ' + ' · '.join(parts)
            self._status = status
            return status

        self.jobs.run(
            AUTO_LABEL, jobs, operation, accept, finish, cancel=cancel,
            workers=1, report_failures=False,
            metrics_settings=self.session.scan_metrics(),
        )

    def _ready(self, watch, cancel):
        if cancel.is_set():
            return False
        current = watch_store.find(self.store, watch.path)
        if current is None or current.policy != 'automatic':
            return False
        if self._watch_open(watch) or self.session.jobs.busy:
            return False
        return True

    def _watch_open(self, watch):
        facade = self.session.facades.folder
        if facade is None or not facade.folderMode:
            return False
        open_folder = self.session.folder
        return (open_folder is not None
                and watch_store.key(open_folder) == watch_store.key(watch.path))

    def _write_record(self, watch, path, state, *, export=None, detail='', stamp=None):
        try:
            watch_store.mark(self.store, watch, path, state=state,
                             export=export, detail=detail, stamp=stamp)
            return True
        except OSError:
            return False

    def _retry(self, jobs):
        touched = {}
        for watch, path in jobs:
            current = watch_store.find(self.store, watch.path)
            if current is None or current.policy != 'automatic':
                continue
            if self._write_record(current, path, watch_store.QUEUED):
                touched[watch_store.key(current.path)] = current
        if touched:
            for watch in touched.values():
                self._update_counts(watch)
            self._persist()
            self.recordsChanged.emit()
        self.resume()

    def _records_failed(self, jobs, detail):
        changed = False
        for watch, path in jobs:
            current = watch_store.find(self.store, watch.path)
            if current is None:
                continue
            if not self._write_record(current, path, watch_store.NEEDS_REVIEW,
                                      detail=detail):
                continue
            changed = True
            self._update_counts(current)
        if changed:
            self._persist()
            self.recordsChanged.emit()
            self.changed.emit()
