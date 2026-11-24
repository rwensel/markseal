"""Watched-folder facade: the inbox rows, sweeping, manual intake, and the
unattended automatic lane.

The store is the document from :mod:`markseal.watches`; this facade owns its
lifecycle, the filesystem notifications, and appending arrivals to the open
folder. Automatic exports run on a second :class:`JobCenter` so they never take
the manual busy flag or block navigation.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from threading import Event

from PySide6.QtCore import (
    Property, QFileSystemWatcher, QObject, QTimer, Signal, Slot,
)
from PySide6.QtWidgets import QFileDialog

from .. import boxset, export, ocr, workflows
from .. import watches as watch_store
from ..jobs import ScanCancelled
from .activity import JobCenter

POLICY_LABELS = {'manual': 'MANUAL', 'automatic': 'AUTO'}
POLICY_ALIASES = {
    'manual': 'manual',
    'automatic': 'automatic',
    'auto': 'automatic',
}

AUTO_LABEL = 'Auto-redacting'
_PAUSED = 'paused'


def _unsettled(stamp, moment):
    """A file that is still young enough to be mid-write."""
    return 0 <= moment - stamp.st_mtime < watch_store.STABLE_SECONDS


class WatchFacade(QObject):
    watchesChanged = Signal()
    inboxRequested = Signal()
    autoChanged = Signal()

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self.store = watch_store.WatchStore()
        self.batch = None
        self._path = watch_store.store_path(session.preference_file)
        self._counts = {}
        self._errors = {}
        self._scan_pending = set()
        self._started = False
        self._inbox_requested = False
        self._intaking = False
        self._auto_jobs = JobCenter(session, self)
        self._auto_hold = False
        self._auto_stopped = False
        self._auto_status = ''
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_sweep)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(600)
        self._debounce.timeout.connect(self.sweep)
        self._resweep = QTimer(self)
        self._resweep.setSingleShot(True)
        self._resweep.timeout.connect(self.sweep)
        self._auto_jobs.busyChanged.connect(self.autoChanged)
        self._auto_jobs.busyChanged.connect(self._dispatch_auto)
        self._auto_jobs.progressChanged.connect(self.autoChanged)
        session.facades.folder.folderChanged.connect(self._folder_changed)
        session.facades.folder.folderChanged.connect(self._dispatch_auto)
        session.jobs.busyChanged.connect(self._retry_scan)
        session.jobs.busyChanged.connect(self._dispatch_auto)

    @Property('QVariantList', notify=watchesChanged)
    def watchRows(self):
        rows = []
        for folder in self.store.folders:
            folder_key = watch_store.key(folder.path)
            result = self._counts.get(folder_key)
            if result is None:
                result = watch_store.counts(self.store, folder)
            rows.append({
                'path': str(folder.path),
                'name': folder.path.name,
                'policy': POLICY_LABELS[folder.policy],
                'new': result.new,
                'existing': result.existing,
                'needs_review': result.needs_review,
                'exported': result.exported,
                'output': str(folder.export_directory),
                'issues': [{'name': name, 'detail': detail}
                           for name, detail in result.issues],
                'error': self._errors.get(folder_key, ''),
            })
        return rows

    @Property(int, notify=watchesChanged)
    def newCount(self):
        return sum(result.new for result in self._counts.values())

    @Property(int, notify=watchesChanged)
    def watchCount(self):
        return len(self.store.folders)

    @Property(bool, notify=autoChanged)
    def autoRunning(self):
        return self._auto_jobs.busy

    @Property(str, notify=autoChanged)
    def autoStatus(self):
        if self._auto_jobs.busy:
            return self._auto_jobs.progressText
        return self._auto_status

    @Slot()
    def start(self):
        if self._started:
            return
        self._started = True
        try:
            self.store = watch_store.load(self._path)
        except watch_store.WatchError:
            self._recover_store()
        for folder in list(self.store.folders):
            self._watch_path(folder.path)
        self.sweep()
        if (self.newCount > 0 and not self._inbox_requested
                and self.session.review.image is None
                and not self.session.facades.folder.folderMode):
            self._inbox_requested = True
            self.inboxRequested.emit()

    def sweep(self, now=None):
        """List every watch, prune stale records, refresh counts, and intake."""
        self._auto_hold = False
        moment = time.time() if now is None else now
        export_targets = watch_store.export_targets(self.store)
        young = False
        changed = False
        counts = {}
        errors = {}
        for folder in list(self.store.folders):
            folder_key = watch_store.key(folder.path)
            images = watch_store._images(folder)
            if images is None:
                counts[folder_key] = watch_store.WatchCounts(available=False)
                errors[folder_key] = 'Folder unavailable'
                continue
            names = [name for name, _path, _stamp in images]
            if watch_store.prune(self.store, folder, names):
                changed = True
            records = self.store.seen.get(folder_key, {})
            if any(_unsettled(stamp, moment)
                   and (records.get(name) is None
                        or records[name].stamp() != (stamp.st_size, stamp.st_mtime_ns))
                   and watch_store.key(path) not in export_targets
                   for name, path, stamp in images):
                young = True
            counts[folder_key] = watch_store.counts(self.store, folder, now=moment)
            self._watch_path(folder.path)
        if counts != self._counts or errors != self._errors:
            changed = True
        self._counts = counts
        self._errors = errors
        if self._intake_open_folder():
            changed = True
        if changed:
            self._save()
            self.watchesChanged.emit()
        if young:
            self._resweep.start(2100)
        elif self.store.folders:
            self._resweep.start(10000)
        else:
            self._resweep.stop()
        self._dispatch_auto()

    @Slot()
    def chooseFolder(self):
        path = QFileDialog.getExistingDirectory(None, 'Watch folder')
        if path:
            self.addWatch(path)

    @Slot(str)
    def addWatch(self, path):
        if not path:
            return
        folder = watch_store.WatchedFolder(Path(path))
        try:
            watch_store.add(self.store, folder)
        except watch_store.WatchError as error:
            self.alerts.error('Cannot watch folder', str(error))
            return
        self._auto_stopped = False
        self._save()
        self._watch_path(folder.path)
        self.sweep()
        self.watchesChanged.emit()

    @Slot(str, str)
    def setPolicy(self, path, policy):
        folder = watch_store.find(self.store, path)
        value = POLICY_ALIASES.get((policy or '').lower())
        if folder is None or value is None:
            return
        if folder.policy == value:
            return
        previous = folder.policy
        folder.policy = value
        if value == 'manual' and previous == 'automatic':
            self._mark_queued_presented(folder)
            self._counts[watch_store.key(folder.path)] = watch_store.counts(
                self.store, folder)
        self._save()
        self.watchesChanged.emit()
        if value == 'automatic':
            self._auto_hold = False
            self._auto_stopped = False
            self._dispatch_auto()

    @Slot(str)
    def removeWatch(self, path):
        folder = watch_store.find(self.store, path)
        if folder is None:
            return
        if not self.alerts.ask(
                'Remove watch?',
                f'Stop watching {folder.path.name}? Its intake records are removed.'):
            return
        folder_key = watch_store.key(folder.path)
        self._auto_hold = True
        self._auto_jobs.cancel()
        watch_store.remove(self.store, folder.path)
        self._counts.pop(folder_key, None)
        self._errors.pop(folder_key, None)
        self._unwatch_path(folder.path)
        self._scan_pending = {
            item for item in self._scan_pending
            if watch_store.key(item.parent) != folder_key
        }
        self._save()
        if not self.store.folders:
            self._resweep.stop()
        self.watchesChanged.emit()

    @Slot(str)
    def openFolder(self, path):
        self.session.facades.folder.open_path(Path(path))

    def watch_for(self, path):
        path = Path(path)
        folder = watch_store.find(self.store, path)
        if folder is None and path.parent != path:
            folder = watch_store.find(self.store, path.parent)
        return folder

    def output_for(self, path):
        folder = watch_store.find(self.store, path)
        return folder.export_directory if folder is not None else None

    def note_export(self, path, target):
        folder = self.watch_for(path)
        if folder is None:
            return
        try:
            watch_store.mark(self.store, folder, path, state=watch_store.EXPORTED,
                             export=target)
        except OSError:
            return
        folder_key = watch_store.key(folder.path)
        self._counts[folder_key] = watch_store.counts(self.store, folder)
        self._save()
        self.watchesChanged.emit()

    @Slot(str)
    def processExisting(self, path):
        """Requeue (automatic) or reset (manual) the records a watch already has."""
        folder = watch_store.find(self.store, path)
        if folder is None:
            return
        folder_key = watch_store.key(folder.path)
        records = self.store.seen.get(folder_key, {})
        changed = False
        self._auto_stopped = False
        if folder.policy == 'automatic':
            for name, record in list(records.items()):
                if record.state not in (watch_store.PRESENTED, watch_store.NEEDS_REVIEW):
                    continue
                source = folder.path / name
                try:
                    stamp = source.stat()
                except OSError:
                    continue
                if (stamp.st_size, stamp.st_mtime_ns) != record.stamp():
                    continue
                try:
                    watch_store.mark(self.store, folder, source, state=watch_store.QUEUED)
                except OSError:
                    continue
                changed = True
            if changed:
                self._counts[folder_key] = watch_store.counts(self.store, folder)
                self._save()
                self.watchesChanged.emit()
            self._auto_hold = False
            self._dispatch_auto()
            return
        for name, record in list(records.items()):
            if record.state not in (watch_store.PRESENTED, watch_store.NEEDS_REVIEW):
                continue
            source = folder.path / name
            try:
                stamp = source.stat()
            except OSError:
                continue
            if (stamp.st_size, stamp.st_mtime_ns) != record.stamp():
                continue
            del records[name]
            changed = True
        if changed:
            self._counts[folder_key] = watch_store.counts(self.store, folder)
            self._save()
            self.watchesChanged.emit()
        if self._watch_open(folder) and self._intake_open_folder():
            self.watchesChanged.emit()

    @Slot()
    def cancelAuto(self):
        self._auto_stopped = True
        self._auto_jobs.cancel()
        self.autoChanged.emit()

    def _dispatch_auto(self):
        """Enqueue every eligible file once, then start the lane if it is idle."""
        if self._auto_hold or self._auto_stopped or self._auto_jobs.busy or self.session.jobs.busy:
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
        touched = {}
        for watch, _path in jobs:
            touched[watch_store.key(watch.path)] = watch
        for watch in touched.values():
            self._counts[watch_store.key(watch.path)] = watch_store.counts(
                self.store, watch)
        self._save()
        self.watchesChanged.emit()
        try:
            engine = self.session.scan_engine()
            settings = self.session.scan_settings()
        except OSError as error:
            self._auto_records_failed(jobs, str(error))
            self.alerts.error('OCR unavailable', str(error), 'RETRY',
                              self._dispatch_auto)
            return
        except (ValueError, re.error) as error:
            self._auto_records_failed(jobs, str(error))
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
        self._auto_status = ''
        stats = {'exported': 0, 'needs_review': 0}

        def operation(job):
            watch, path = job
            if not self._auto_ready(watch, cancel):
                cancel.set()
                return (path, None, _PAUSED, None, '')
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
                if not self._auto_ready(watch, cancel):
                    cancel.set()
                    return (path, stamp, _PAUSED, None, '')
                try:
                    snapshot, with_log = workflows.auto_export_snapshot(
                        entry, watch.export_directory, template, include_log)
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
                state, target, detail = watch_store.NEEDS_REVIEW, None, error
            else:
                _path, _stamp, state, target, detail = result
            if state == _PAUSED:
                self._auto_hold = True
                if current.policy != 'automatic' and self._write_record(
                        current, path, watch_store.PRESENTED):
                    self._counts[watch_store.key(current.path)] = (
                        watch_store.counts(self.store, current))
                    self._save()
                    self.watchesChanged.emit()
                return
            if state == watch_store.EXPORTED:
                stats['exported'] += 1
            elif state == watch_store.NEEDS_REVIEW:
                stats['needs_review'] += 1
            if self._write_record(current, path, state, export=target, detail=detail):
                self._counts[watch_store.key(current.path)] = watch_store.counts(
                    self.store, current)
                self._save()
                self.watchesChanged.emit()

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
            self._auto_status = status
            return status

        self._auto_jobs.run(
            AUTO_LABEL, jobs, operation, accept, finish, cancel=cancel,
            workers=1, report_failures=False,
            metrics_settings=self.session.scan_metrics(),
        )

    def _auto_ready(self, watch, cancel):
        """Whether this file may still run and, later, publish."""
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

    def _write_record(self, watch, path, state, *, export=None, detail=''):
        try:
            watch_store.mark(self.store, watch, path, state=state,
                             export=export, detail=detail)
            return True
        except OSError:
            return False

    def _mark_queued_presented(self, folder):
        records = self.store.seen.get(watch_store.key(folder.path), {})
        for name, record in list(records.items()):
            if record.state != watch_store.QUEUED:
                continue
            self._write_record(folder, folder.path / name, watch_store.PRESENTED)

    def _auto_records_failed(self, jobs, detail):
        changed = False
        for watch, path in jobs:
            current = watch_store.find(self.store, watch.path)
            if current is None:
                continue
            if not self._write_record(current, path, watch_store.NEEDS_REVIEW,
                                      detail=detail):
                continue
            changed = True
            self._counts[watch_store.key(current.path)] = watch_store.counts(
                self.store, current)
        if changed:
            self._save()
            self.watchesChanged.emit()
            self.autoChanged.emit()

    def _folder_changed(self):
        folder = self.session.folder
        if folder is None or not self.session.facades.folder.folderMode:
            return
        if watch_store.find(self.store, folder) is None:
            return
        if self._intake_open_folder():
            self.watchesChanged.emit()

    def _intake_open_folder(self):
        """Append unseen arrivals of the open watched folder and scan them."""
        if self._intaking:
            return False
        folder = self.session.folder
        if folder is None or not self.session.facades.folder.folderMode:
            return False
        watch = watch_store.find(self.store, folder)
        if watch is None:
            return False
        self._intaking = True
        try:
            paths = watch_store.unseen(self.store, watch)
            if not paths:
                return False
            changed = False
            if watch.policy == 'manual':
                for path in paths:
                    try:
                        watch_store.mark(self.store, watch, path,
                                         state=watch_store.PRESENTED)
                    except OSError:
                        continue
                changed = True
            added = self.session.facades.folder.add_paths(paths)
            if changed or added:
                self._save()
            wanted = set(paths)
            targets = [entry for entry in self.session.entries
                       if entry.path in wanted and not entry.scanned and not entry.error]
            if targets:
                if self.session.jobs.busy:
                    self._scan_pending.update(entry.path for entry in targets)
                elif self.batch is not None:
                    self.batch.start_scan(targets, follow=False)
            if changed:
                self._counts[watch_store.key(watch.path)] = watch_store.counts(
                    self.store, watch)
            return changed or bool(added)
        finally:
            self._intaking = False

    def _retry_scan(self):
        if self.session.jobs.busy or not self._scan_pending:
            return
        paths = set(self._scan_pending)
        self._scan_pending.clear()
        targets = [entry for entry in self.session.entries
                   if entry.path in paths and not entry.scanned and not entry.error]
        if targets and self.batch is not None:
            self.batch.start_scan(targets, follow=False)

    def _schedule_sweep(self, *_args):
        self._debounce.start()

    def _watch_path(self, path):
        path = Path(path)
        if not path.is_dir():
            return
        watched = {
            os.path.normcase(os.path.abspath(name))
            for name in self._watcher.directories()
        }
        if os.path.normcase(os.path.abspath(str(path))) in watched:
            return
        self._watcher.addPath(str(path))

    def _unwatch_path(self, path):
        watched = {
            os.path.normcase(os.path.abspath(name)): name
            for name in self._watcher.directories()
        }
        match = watched.get(os.path.normcase(os.path.abspath(str(path))))
        if match is not None:
            self._watcher.removePath(match)

    def _save(self):
        try:
            watch_store.save(self._path, self.store)
        except OSError as error:
            self.alerts.error('Cannot save watched folders', str(error))

    def _recover_store(self):
        corrupt = self._path.with_name(self._path.name + '.corrupt')
        try:
            self._path.replace(corrupt)
        except OSError:
            pass
        self.store = watch_store.WatchStore()
        self.alerts.set_status(
            'The watched-folder list could not be loaded; starting with an empty list.'
        )
