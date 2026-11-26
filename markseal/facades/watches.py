"""Watched-folder facade: the inbox rows, sweeping, and manual intake.

The store is the document from :mod:`markseal.watches`; this facade owns its
lifecycle, the filesystem notifications, and appending arrivals to the open
folder. The automatic lane lives in :mod:`markseal.facades.auto_watch` so its
job lifecycle never takes the manual busy flag or blocks navigation.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import (
    Property, QFileSystemWatcher, QObject, QTimer, Signal, Slot,
)
from PySide6.QtWidgets import QFileDialog

from .. import watches as watch_store
from .auto_watch import AutomaticLane

POLICY_LABELS = {'manual': 'MANUAL', 'automatic': 'AUTO'}
POLICY_ALIASES = {
    'manual': 'manual',
    'automatic': 'automatic',
    'auto': 'automatic',
}


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
        self.records = watch_store.WatchRecords(self.store, self._path)
        self._auto = AutomaticLane(session, alerts, self.records, self)
        self._auto.changed.connect(self.autoChanged)
        self._auto.recordsChanged.connect(self._records_changed)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_sweep)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(600)
        self._debounce.timeout.connect(self.sweep)
        self._resweep = QTimer(self)
        self._resweep.setSingleShot(True)
        self._resweep.timeout.connect(self.sweep)
        session.facades.folder.folderChanged.connect(self._folder_changed)
        session.facades.folder.folderChanged.connect(self._auto.dispatch)
        session.jobs.busyChanged.connect(self._retry_scan)
        session.jobs.busyChanged.connect(self._auto.dispatch)

    def _counts_for(self, watch):
        folder_key = watch_store.key(watch.path)
        result = self._counts.get(folder_key)
        if result is None:
            result = self.records.counts_for(watch)
        return result

    def _refresh_counts(self, watch):
        self._counts[watch_store.key(watch.path)] = self.records.counts_for(watch)

    def _records_changed(self):
        for folder in self.store.folders:
            self._refresh_counts(folder)
        self.watchesChanged.emit()

    @Property('QVariantList', notify=watchesChanged)
    def watchRows(self):
        rows = []
        for folder in self.store.folders:
            folder_key = watch_store.key(folder.path)
            result = self._counts_for(folder)
            rows.append({
                'path': str(folder.path),
                'name': folder.path.name,
                'policy': POLICY_LABELS[folder.policy],
                'new': result.new,
                'queued': result.queued,
                'existing': result.existing,
                'needs_review': result.needs_review,
                'exported': result.exported,
                'recursive': folder.recursive,
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
        return self._auto.busy

    @Property(str, notify=autoChanged)
    def autoStatus(self):
        return self._auto.status

    @Slot()
    def start(self):
        if self._started:
            return
        self._started = True
        try:
            loaded = watch_store.load(self._path)
        except watch_store.WatchError:
            self._recover_store()
        else:
            self.store.folders = loaded.folders
            self.store.seen = loaded.seen
        self._auto.store = self.store
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
        self._auto.reset_hold()
        moment = time.time() if now is None else now
        export_targets = watch_store.export_targets(self.store)
        young = False
        changed = False
        counts = {}
        errors = {}
        for folder in list(self.store.folders):
            folder_key = watch_store.key(folder.path)
            scan_issues = []
            entries = watch_store.scan(self.store, folder, scan_issues)
            if entries is None:
                counts[folder_key] = watch_store.WatchCounts(available=False)
                errors[folder_key] = 'Folder unavailable'
                continue
            names = [entry.key for entry in entries]
            if not scan_issues and watch_store.prune(self.store, folder, names):
                changed = True
            records = self.store.seen.get(folder_key, {})
            if any(_unsettled(entry.stamp, moment)
                   and (records.get(entry.key) is None
                        or records[entry.key].stamp() != (
                            entry.stamp.st_size, entry.stamp.st_mtime_ns))
                   and watch_store.key(entry.path) not in export_targets
                   for entry in entries):
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
        self._auto.dispatch()

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
        self._auto.clear_stop()
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
            self._auto.resume()

    @Slot(str, bool)
    def setRecursive(self, path, recursive):
        folder = watch_store.find(self.store, path)
        value = bool(recursive)
        if folder is None or folder.recursive == value:
            return
        folder.recursive = value
        if value:
            watch_store.baseline(self.store, folder, nested_only=True)
        folder_key = watch_store.key(folder.path)
        self._counts[folder_key] = watch_store.counts(self.store, folder)
        self._save()
        self.watchesChanged.emit()
        self.sweep()

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
        self._auto.pause()
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
        folder = watch_store.find(self.store, path)
        if folder is None:
            self.session.facades.folder.open_path(Path(path))
            return
        entries = watch_store.scan(self.store, folder)
        if entries is None:
            self.alerts.error('Cannot open folder', 'The folder could not be read.')
            return
        self.session.facades.folder.open_paths(folder.path,
                                                [entry.path for entry in entries])

    def watch_for(self, path):
        return watch_store.folder_for(self.store, path)

    def output_for(self, path):
        folder = watch_store.find(self.store, path)
        return folder.export_directory if folder is not None else None

    def output_for_source(self, path):
        """The export folder for one source, mirroring its subfolder when needed."""
        folder = watch_store.folder_for(self.store, path)
        if folder is None:
            return None
        return watch_store.destination(folder, path)

    def note_export(self, path, target):
        folder = self.watch_for(path)
        if folder is None:
            return
        change = self.records.set(folder, path, state=watch_store.EXPORTED,
                                  export=target)
        if change.changed:
            self._counts[change.folder_key] = change.counts
            self.watchesChanged.emit()

    @Slot(str)
    def processExisting(self, path):
        """Requeue (automatic) or reset (manual) the records a watch already has."""
        folder = watch_store.find(self.store, path)
        if folder is None:
            return
        folder_key = watch_store.key(folder.path)
        self._auto.clear_stop()
        change = self.records.process_existing(
            folder, automatic=folder.policy == 'automatic')
        if change.changed:
            self._counts[folder_key] = change.counts
            self.watchesChanged.emit()
        if folder.policy == 'automatic':
            self._auto.resume()
            return
        if self._intake_open_folder():
            self.watchesChanged.emit()

    @Slot()
    def cancelAuto(self):
        self._auto.cancel()

    def _mark_queued_presented(self, folder):
        records = self.store.seen.get(watch_store.key(folder.path), {})
        paths = [folder.path / name for name, record in records.items()
                 if record.state == watch_store.QUEUED]
        change = self.records.set_many(folder, paths, state=watch_store.PRESENTED)
        if change.changed:
            self._counts[change.folder_key] = change.counts

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
                change = self.records.set_many(
                    watch, paths, state=watch_store.PRESENTED)
                changed = change.changed
                if change.changed:
                    self._counts[change.folder_key] = change.counts
            added = self.session.facades.folder.add_paths(paths)
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
            self.records.save()
        except OSError as error:
            self.alerts.error('Cannot save watched folders', str(error))

    def _recover_store(self):
        corrupt = self._path.with_name(self._path.name + '.corrupt')
        try:
            self._path.replace(corrupt)
        except OSError:
            pass
        self.store.folders.clear()
        self.store.seen.clear()
        self.alerts.set_status(
            'The watched-folder list could not be loaded; starting with an empty list.'
        )
