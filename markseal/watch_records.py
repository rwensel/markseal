from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import watch_document
from .watch_document import (
    NEEDS_REVIEW, PRESENTED, QUEUED, WatchCounts, file_key, key,
)
from .watch_scan import counts


@dataclass(frozen=True)
class RecordChange:
    changed: bool
    folder_key: str
    counts: WatchCounts | None = None
    error: OSError | None = None


class WatchRecords:
    """Apply one watch record transition with its count refresh and save."""
    def __init__(self, store, path):
        self.store = store
        self.path = Path(path)

    def save(self):
        watch_document.save(self.path, self.store)

    def counts_for(self, folder):
        return counts(self.store, folder)

    def _snapshot(self, folder_key, record_key):
        records = self.store.seen.get(folder_key)
        return records, None if records is None else records.get(record_key)

    @staticmethod
    def _restore(folder_key, record_key, snapshot):
        records, previous = snapshot
        current = records if records is not None else {}
        if previous is None:
            current.pop(record_key, None)
        else:
            current[record_key] = previous

    def set(self, folder, path, *, state, export=None, detail='', stamp=None):
        folder_key = key(folder.path)
        record_key = file_key(folder.path, path)
        snapshot = self._snapshot(folder_key, record_key)
        try:
            watch_document.mark(self.store, folder, path, state=state, export=export,
                                detail=detail, stamp=stamp)
        except OSError as error:
            return RecordChange(False, folder_key, error=error)
        try:
            self.save()
        except OSError as error:
            self._restore(folder_key, record_key, snapshot)
            return RecordChange(False, folder_key, error=error)
        return RecordChange(True, folder_key, counts(self.store, folder))

    def set_many(self, folder, paths, *, state, export=None, detail='', stamp=None):
        folder_key = key(folder.path)
        snapshots = []
        changed = False
        error = None
        for path in paths:
            record_key = file_key(folder.path, path)
            snapshots.append((record_key, self._snapshot(folder_key, record_key)))
            try:
                watch_document.mark(self.store, folder, path, state=state, export=export,
                                    detail=detail, stamp=stamp)
                changed = True
            except OSError as exc:
                error = error or exc
        if not changed:
            return RecordChange(False, folder_key, counts(self.store, folder), error)
        try:
            self.save()
        except OSError as exc:
            for record_key, snapshot in snapshots:
                self._restore(folder_key, record_key, snapshot)
            return RecordChange(False, folder_key, error=exc)
        return RecordChange(True, folder_key, counts(self.store, folder), error)

    def forget(self, folder, paths):
        folder_key = key(folder.path)
        records = self.store.seen.get(folder_key)
        if not records:
            return RecordChange(False, folder_key, counts(self.store, folder))
        removed = {}
        for path in paths:
            record_key = file_key(folder.path, path)
            if record_key in records:
                removed[record_key] = records.pop(record_key)
        if not removed:
            return RecordChange(False, folder_key, counts(self.store, folder))
        try:
            self.save()
        except OSError as error:
            records.update(removed)
            return RecordChange(False, folder_key, error=error)
        return RecordChange(True, folder_key, counts(self.store, folder))

    def process_existing(self, folder, *, automatic):
        folder_key = key(folder.path)
        records = self.store.seen.get(folder_key, {})
        paths = []
        for name, record in list(records.items()):
            if record.state not in (PRESENTED, NEEDS_REVIEW):
                continue
            source = folder.path / name
            try:
                stamp = source.stat()
            except OSError:
                continue
            if (stamp.st_size, stamp.st_mtime_ns) != record.stamp():
                continue
            paths.append(source)
        if not paths:
            return RecordChange(False, folder_key, counts(self.store, folder))
        if automatic:
            return self.set_many(folder, paths, state=QUEUED)
        return self.forget(folder, paths)
