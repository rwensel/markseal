from __future__ import annotations

import re
from threading import Event

from PySide6.QtCore import QObject, Signal

from .. import boxset, ocr, workflows
from .. import watches as watch_store
from ..export_copy import ExportCopies
from ..jobs import ScanCancelled
from .activity import JobCenter

AUTO_LABEL = 'Auto-redacting'
PAUSED = 'paused'


class AutomaticLane(QObject):
    changed = Signal()
    recordsChanged = Signal()

    def __init__(self, session, alerts, records, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self.records = records
        self.store = records.store
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
            waiting = sum(self.records.counts_for(watch).queued
                          for watch in self.store.folders)
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
        grouped = {}
        for watch, path in candidates:
            grouped.setdefault(watch_store.key(watch.path), (watch, []))[1].append(path)
        jobs = []
        for watch, paths in grouped.values():
            change = self.records.set_many(watch, paths, state=watch_store.QUEUED)
            if change.changed:
                jobs.extend((watch, path) for path in paths)
        if not jobs:
            return
        self._status = ''
        self.changed.emit()
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
        copies = ExportCopies(preferences)
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
                    snapshot, with_log = copies.auto_snapshot(
                        entry, watch_store.destination(watch, path))
                    snapshot.target.parent.mkdir(parents=True, exist_ok=True)
                    copies.write(snapshot, include_log=with_log)
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
                if current.policy != 'automatic':
                    change = self.records.set(
                        current, path, state=watch_store.PRESENTED, stamp=stamp)
                    if change.changed:
                        self.recordsChanged.emit()
                return
            if state == watch_store.EXPORTED:
                stats['exported'] += 1
            elif state == watch_store.NEEDS_REVIEW:
                stats['needs_review'] += 1
            change = self.records.set(current, path, state=state, export=target,
                                      detail=detail, stamp=stamp)
            if change.changed:
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

    def _retry(self, jobs):
        grouped = {}
        for watch, path in jobs:
            current = watch_store.find(self.store, watch.path)
            if current is None or current.policy != 'automatic':
                continue
            grouped.setdefault(watch_store.key(current.path), (current, []))[1].append(path)
        changed = False
        for watch, paths in grouped.values():
            change = self.records.set_many(watch, paths, state=watch_store.QUEUED)
            changed = change.changed or changed
        if changed:
            self.recordsChanged.emit()
        self.resume()

    def _records_failed(self, jobs, detail):
        grouped = {}
        for watch, path in jobs:
            current = watch_store.find(self.store, watch.path)
            if current is None:
                continue
            grouped.setdefault(watch_store.key(current.path), (current, []))[1].append(path)
        changed = False
        for watch, paths in grouped.values():
            change = self.records.set_many(
                watch, paths, state=watch_store.NEEDS_REVIEW, detail=detail)
            changed = change.changed or changed
        if changed:
            self.recordsChanged.emit()
            self.changed.emit()
