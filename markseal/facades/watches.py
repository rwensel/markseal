"""Watched-folder facade: the inbox rows, sweeping, and manual intake.

The store is the document from :mod:`markseal.watches`; this facade owns its
lifecycle, the filesystem notifications, and appending arrivals to the open
folder. Automatic processing is not part of this facade yet.
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


def _unsettled(stamp, moment):
    """A file that is still young enough to be mid-write."""
    return 0 <= moment - stamp.st_mtime < watch_store.STABLE_SECONDS


class WatchFacade(QObject):
    watchesChanged = Signal()
    inboxRequested = Signal()

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
        session.jobs.busyChanged.connect(self._retry_scan)

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
                'policy': folder.policy.upper(),
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
        self._save()
        self._watch_path(folder.path)
        self.sweep()
        self.watchesChanged.emit()

    @Slot(str, str)
    def setPolicy(self, path, policy):
        folder = watch_store.find(self.store, path)
        policy = (policy or '').lower()
        if folder is None or policy not in watch_store.POLICIES:
            return
        if folder.policy == policy:
            return
        folder.policy = policy
        self._save()
        self.watchesChanged.emit()

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
        folder = self.watch_for(path)
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
