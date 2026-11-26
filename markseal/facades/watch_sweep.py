from __future__ import annotations

import os
import time
from pathlib import Path

from .. import watches as watch_store


class WatchSweep:
    def __init__(self, owner):
        self.owner = owner

    def schedule(self, *_args):
        self.owner._debounce.start()

    def watch_path(self, path):
        path = Path(path)
        if not path.is_dir():
            return
        watched = {
            os.path.normcase(os.path.abspath(name))
            for name in self.owner._watcher.directories()
        }
        if os.path.normcase(os.path.abspath(str(path))) in watched:
            return
        self.owner._watcher.addPath(str(path))

    def unwatch_path(self, path):
        watched = {
            os.path.normcase(os.path.abspath(name)): name
            for name in self.owner._watcher.directories()
        }
        match = watched.get(os.path.normcase(os.path.abspath(str(path))))
        if match is not None:
            self.owner._watcher.removePath(match)

    def sweep(self, now=None):
        owner = self.owner
        owner._auto.reset_hold()
        moment = time.time() if now is None else now
        export_targets = watch_store.export_targets(owner.store)
        young = False
        changed = False
        counts = {}
        errors = {}
        for folder in list(owner.store.folders):
            folder_key = watch_store.key(folder.path)
            scan_issues = []
            entries = watch_store.scan(owner.store, folder, scan_issues)
            if entries is None:
                counts[folder_key] = watch_store.WatchCounts(available=False)
                errors[folder_key] = 'Folder unavailable'
                continue
            names = [entry.key for entry in entries]
            if not scan_issues and watch_store.prune(owner.store, folder, names):
                changed = True
            records = owner.store.seen.get(folder_key, {})
            if any(_unsettled(entry.stamp, moment)
                   and (records.get(entry.key) is None
                        or records[entry.key].stamp() != (
                            entry.stamp.st_size, entry.stamp.st_mtime_ns))
                   and watch_store.key(entry.path) not in export_targets
                   for entry in entries):
                young = True
            counts[folder_key] = watch_store.counts(owner.store, folder, now=moment)
            self.watch_path(folder.path)
        if counts != owner._counts or errors != owner._errors:
            changed = True
        owner._counts = counts
        owner._errors = errors
        if self.intake_open_folder():
            changed = True
        if changed:
            owner._save()
            owner.watchesChanged.emit()
        if young:
            owner._resweep.start(2100)
        elif owner.store.folders:
            owner._resweep.start(10000)
        else:
            owner._resweep.stop()
        owner._auto.dispatch()

    def folder_changed(self):
        owner = self.owner
        folder = owner.session.folder
        if folder is None or not owner.session.facades.folder.folderMode:
            return
        if watch_store.find(owner.store, folder) is None:
            return
        if self.intake_open_folder():
            owner.watchesChanged.emit()

    def intake_open_folder(self):
        owner = self.owner
        if owner._intaking:
            return False
        folder = owner.session.folder
        if folder is None or not owner.session.facades.folder.folderMode:
            return False
        watch = watch_store.find(owner.store, folder)
        if watch is None:
            return False
        owner._intaking = True
        try:
            paths = watch_store.unseen(owner.store, watch)
            if not paths:
                return False
            changed = False
            if watch.policy == 'manual':
                change = owner.records.set_many(
                    watch, paths, state=watch_store.PRESENTED)
                changed = change.changed
                if change.changed:
                    owner._counts[change.folder_key] = change.counts
            added = owner.session.facades.folder.add_paths(paths)
            wanted = set(paths)
            targets = [entry for entry in owner.session.entries
                       if entry.path in wanted and not entry.scanned and not entry.error]
            if targets:
                if owner.session.jobs.busy:
                    owner._scan_pending.update(entry.path for entry in targets)
                elif owner.batch is not None:
                    owner.batch.start_scan(targets, follow=False)
            if changed:
                owner._counts[watch_store.key(watch.path)] = watch_store.counts(
                    owner.store, watch)
            return changed or bool(added)
        finally:
            owner._intaking = False

    def retry_scan(self):
        owner = self.owner
        if owner.session.jobs.busy or not owner._scan_pending:
            return
        paths = set(owner._scan_pending)
        owner._scan_pending.clear()
        targets = [entry for entry in owner.session.entries
                   if entry.path in paths and not entry.scanned and not entry.error]
        if targets and owner.batch is not None:
            owner.batch.start_scan(targets, follow=False)


def _unsettled(stamp, moment):
    return 0 <= moment - stamp.st_mtime < watch_store.STABLE_SECONDS
