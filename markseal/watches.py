"""The watched-folder document, intake rules, states, and counts.

One owner for ``watches.json``: this module has no Qt import and never touches
the network. A watch covers the images directly inside its folder, or its whole
subtree when ``recursive`` is set; sidecars and files the app exported are never
intake candidates.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

from . import images

POLICIES = ('manual', 'automatic')
STABLE_SECONDS = 2.0

PRESENTED = 'presented'
QUEUED = 'queued'
EXPORTED = 'exported'
NEEDS_REVIEW = 'needs_review'
STATES = (PRESENTED, QUEUED, EXPORTED, NEEDS_REVIEW)

STORE_NAME = 'watches.json'
DEFAULT_EXPORT_NAME = 'redacted'


class WatchError(ValueError):
    """The watched-folder document could not be read or accepted."""


@dataclass
class WatchedFolder:
    path: Path
    policy: str = 'manual'
    output_directory: Path | None = None
    recursive: bool = False

    def __post_init__(self):
        self.path = Path(self.path)
        if self.output_directory is not None:
            self.output_directory = Path(self.output_directory)
        self.recursive = bool(self.recursive)

    @property
    def export_directory(self):
        """Where automatic exports for this watch go; ``redacted/`` by default."""
        if self.output_directory is not None:
            return self.output_directory
        return self.path / DEFAULT_EXPORT_NAME


@dataclass
class SeenFile:
    size: int
    mtime_ns: int
    state: str
    export: str = ''
    detail: str = ''

    def stamp(self):
        return self.size, self.mtime_ns


@dataclass
class WatchStore:
    folders: list[WatchedFolder] = field(default_factory=list)
    seen: dict[str, dict[str, SeenFile]] = field(default_factory=dict)


@dataclass
class WatchCounts:
    new: int = 0
    queued: int = 0
    existing: int = 0
    needs_review: int = 0
    exported: int = 0
    issues: tuple = ()
    available: bool = True


@dataclass(frozen=True)
class RecordChange:
    changed: bool
    folder_key: str
    counts: WatchCounts | None = None
    error: OSError | None = None


def key(path):
    """One identity for a folder or file: resolved and case-folded on Windows."""
    return os.path.normcase(str(Path(path).resolve()))


def file_key(folder, path):
    """A file's identity: its relative path, case-folded on Windows."""
    relative = os.path.relpath(str(path), str(folder))
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        raise ValueError('File is outside the watch.')
    return os.path.normcase(Path(relative).as_posix())


def _migrated_key(folder, name):
    """A loaded record key as a relative path, or ``None`` when it escapes."""
    candidate = Path(name)
    if candidate.is_absolute():
        return None
    try:
        relative = (Path(folder) / candidate).relative_to(folder)
    except ValueError:
        return None
    if '..' in relative.parts:
        return None
    return os.path.normcase(relative.as_posix())


def store_path(settings_path):
    """The watch document sits beside ``settings.json``."""
    return Path(settings_path).parent / STORE_NAME


def find(store, path):
    target = key(path)
    for folder in store.folders:
        if key(folder.path) == target:
            return folder
    return None


def export_targets(store):
    """Every export path a record remembers, so the app never ingests its own copy."""
    targets = set()
    for records in store.seen.values():
        for record in records.values():
            if record.export:
                targets.add(key(record.export))
    return targets


def record(path):
    """A fresh seen value for a file, from one ``stat``."""
    path = Path(path)
    stamp = path.stat()
    return SeenFile(stamp.st_size, stamp.st_mtime_ns, PRESENTED)


def _settled(stamp, moment):
    """A file counts once it has stopped changing; a future mtime is settled too."""
    age = moment - stamp.st_mtime
    return not 0 <= age < STABLE_SECONDS


def exclusions(store):
    return tuple(folder.export_directory for folder in store.folders)


@dataclass(frozen=True)
class ScanFile:
    key: str
    path: Path
    stamp: os.stat_result


def scan(store, folder, issues=None):
    skip = list(exclusions(store))
    skip.append(folder.export_directory)
    found = images.scan_images(folder.path, recursive=folder.recursive, skip=skip,
                               problems=issues)
    if found is None:
        return None
    return [ScanFile(file_key(folder.path, path), path, stamp)
            for _relative, path, stamp in found]


def _within(parent, child):
    """Whether ``child`` is ``parent`` or sits inside it, across drives safe."""
    parent_text = key(parent)
    child_text = key(child)
    try:
        return os.path.commonpath([parent_text, child_text]) == parent_text
    except ValueError:
        return False


def contains(folder, path):
    target = Path(path)
    if key(folder.path) == key(target):
        return True
    if folder.recursive:
        return _within(folder.path, target)
    return key(target.parent) == key(folder.path)


def folder_for(store, path):
    target = Path(path)
    best = None
    for folder in store.folders:
        if key(folder.path) == key(target):
            return folder
        if not contains(folder, target):
            continue
        if best is None or len(str(folder.path)) > len(str(best.path)):
            best = folder
    return best


def destination(folder, source):
    try:
        relative = Path(os.path.relpath(str(Path(source).parent), str(folder.path)))
    except ValueError:
        return folder.export_directory
    if '..' in relative.parts:
        return folder.export_directory
    return folder.export_directory / relative


def baseline(store, folder, *, nested_only=False):
    """Record current images as presented without scanning or exporting them.

    ``nested_only`` leaves top-level records alone, so turning recursion on
    cannot hide a root-level arrival that has not been swept yet.
    """
    found = scan(store, folder)
    if found is None:
        return False
    records = store.seen.setdefault(key(folder.path), {})
    changed = False
    for entry in found:
        if nested_only and Path(entry.key).parent == Path('.'):
            continue
        if entry.key in records:
            continue
        records[entry.key] = SeenFile(entry.stamp.st_size, entry.stamp.st_mtime_ns,
                                       PRESENTED)
        changed = True
    return changed


def validate(store, folder):
    """A message when the watch cannot be added, otherwise ``None``."""
    if folder.policy not in POLICIES:
        return 'Choose a manual or automatic watch.'
    if not folder.path.is_absolute():
        return 'Choose an absolute folder.'
    if not folder.path.is_dir():
        return 'Choose a folder that exists.'
    folder_key = key(folder.path)
    for other in store.folders:
        if key(other.path) == folder_key:
            return 'That folder is already watched.'
        if _within(other.path, folder.path) or _within(folder.path, other.path):
            return 'Watched folders cannot be inside one another.'
        if key(other.export_directory) == folder_key:
            return 'That folder receives exports from another watch.'
    if folder.output_directory is not None:
        output = folder.output_directory
        if not output.is_absolute():
            return 'Choose an absolute export folder.'
        if key(output) == folder_key:
            return 'Choose an export folder other than the watched folder.'
        for other in store.folders:
            if key(other.path) == key(output):
                return 'Choose an export folder other than a watched folder.'
    return None


def add(store, folder):
    """Validate and register a watch, baselining the images already there.

    Nothing is filtered by age: a screenshot still being written is recorded as
    presented, and its later stamp change makes it new.
    """
    problem = validate(store, folder)
    if problem is not None:
        raise WatchError(problem)
    images = scan(store, folder)
    if images is None:
        raise WatchError('The folder could not be read.')
    baseline = {}
    for entry in images:
        baseline[entry.key] = SeenFile(entry.stamp.st_size, entry.stamp.st_mtime_ns,
                                       PRESENTED)
    store.seen[key(folder.path)] = baseline
    store.folders.append(folder)
    return folder


def remove(store, path):
    """Drop a watch and the records that belong to it."""
    target = key(path)
    store.folders = [folder for folder in store.folders if key(folder.path) != target]
    store.seen.pop(target, None)


def mark(store, folder, path, *, state, export=None, detail='', stamp=None):
    """Write one record for a source file.

    ``stamp`` pins the ``(size, mtime_ns)`` the file had when it was scanned,
    so a source replaced before the record is written stays new. Without it the
    current stamp is read.
    """
    path = Path(path)
    if stamp is None:
        measured = path.stat()
        stamp = (measured.st_size, measured.st_mtime_ns)
    records = store.seen.setdefault(key(folder.path), {})
    records[file_key(folder.path, path)] = SeenFile(
        stamp[0], stamp[1], state, str(export) if export else '', detail)


def unseen(store, folder, *, now=None):
    """Stable images that are new or changed and were not written by the app."""
    images = scan(store, folder)
    if images is None:
        return []
    moment = time.time() if now is None else now
    records = store.seen.get(key(folder.path), {})
    targets = export_targets(store)
    found = []
    for entry in images:
        if key(entry.path) in targets or not _settled(entry.stamp, moment):
            continue
        previous = records.get(entry.key)
        if (previous is not None
                and previous.stamp() == (entry.stamp.st_size, entry.stamp.st_mtime_ns)):
            continue
        found.append(entry.path)
    return found


def pending_queued(store, folder):
    """Files whose ``queued`` record still matches, so a crash resumes them."""
    images = scan(store, folder)
    if images is None:
        return []
    records = store.seen.get(key(folder.path), {})
    found = []
    for entry in images:
        previous = records.get(entry.key)
        if previous is None or previous.state != QUEUED:
            continue
        if previous.stamp() == (entry.stamp.st_size, entry.stamp.st_mtime_ns):
            found.append(entry.path)
    return found


def counts(store, folder, *, now=None):
    """Per-watch counts, all requiring a matching stamp; never mutates the store."""
    scan_issues = []
    images = scan(store, folder, scan_issues)
    if images is None:
        return WatchCounts(available=False)
    moment = time.time() if now is None else now
    records = store.seen.get(key(folder.path), {})
    targets = export_targets(store)
    fresh = queued = existing = review = exported = 0
    issues = []
    for entry in images:
        if key(entry.path) in targets:
            continue
        previous = records.get(entry.key)
        matched = (previous is not None
                   and previous.stamp() == (entry.stamp.st_size, entry.stamp.st_mtime_ns))
        if not matched:
            if _settled(entry.stamp, moment):
                fresh += 1
            continue
        if previous.state == PRESENTED:
            existing += 1
        elif previous.state == QUEUED:
            queued += 1
        elif previous.state == NEEDS_REVIEW:
            review += 1
            if len(issues) < 5:
                issues.append((Path(entry.key).as_posix(), previous.detail))
        elif previous.state == EXPORTED and previous.export:
            if Path(previous.export).is_file():
                exported += 1
    for relative in scan_issues:
        if len(issues) >= 5:
            break
        issues.append((relative, 'Could not read this folder'))
    return WatchCounts(new=fresh, queued=queued, existing=existing,
                       needs_review=review, exported=exported,
                       issues=tuple(issues), available=True)


def automatic_outcome(entry):
    """The lane's decision for one scanned image: state and review detail."""
    if entry.incomplete_ocr:
        return NEEDS_REVIEW, 'Partial scan'
    if not entry.selected:
        return NEEDS_REVIEW, 'Nothing found'
    return EXPORTED, ''


def prune(store, folder, names):
    """Drop records whose file is absent from a successful listing.

    With recursion off, nested records stay because they are outside the
    current scope, not gone; turning the switch back on reuses them.
    """
    records = store.seen.get(key(folder.path))
    if not records:
        return False
    present = set(names)
    stale = [name for name in records
             if name not in present
             and (folder.recursive or Path(name).parent == Path('.'))]
    for name in stale:
        del records[name]
    return bool(stale)


def _folder_document(folder):
    return {
        'path': str(folder.path),
        'policy': folder.policy,
        'output_directory': (str(folder.output_directory)
                             if folder.output_directory is not None else None),
        'recursive': folder.recursive,
    }


def _store_document(store):
    return {
        'folders': [_folder_document(folder) for folder in store.folders],
        'seen': {
            folder_key: {
                name: {
                    'size': item.size,
                    'mtime_ns': item.mtime_ns,
                    'state': item.state,
                    'export': item.export,
                    'detail': item.detail,
                }
                for name, item in records.items()
            }
            for folder_key, records in store.seen.items()
        },
    }


def save(path, store):
    """Write the document atomically: a temporary sibling, then replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(_store_document(store), stream, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class WatchRecords:
    """Apply one watch record transition with its count refresh and save."""

    def __init__(self, store, path):
        self.store = store
        self.path = Path(path)

    def save(self):
        save(self.path, self.store)

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
            mark(self.store, folder, path, state=state, export=export,
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
                mark(self.store, folder, path, state=state, export=export,
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


def _folder_from_document(entry):
    if not isinstance(entry, dict):
        return None
    path = entry.get('path')
    policy = entry.get('policy', 'manual')
    if not isinstance(path, str) or not path or policy not in POLICIES:
        return None
    output = entry.get('output_directory')
    if output is not None and not isinstance(output, str):
        return None
    recursive = entry.get('recursive', False)
    if not isinstance(recursive, bool):
        recursive = False
    folder = WatchedFolder(Path(path), policy, Path(output) if output else None,
                           recursive)
    if not folder.path.is_absolute():
        return None
    if folder.output_directory is not None and not folder.output_directory.is_absolute():
        return None
    return folder


def _record_from_document(name, entry):
    if not isinstance(name, str) or not name or not isinstance(entry, dict):
        return None
    size = entry.get('size')
    mtime_ns = entry.get('mtime_ns')
    state = entry.get('state')
    export = entry.get('export', '')
    detail = entry.get('detail', '')
    if type(size) is not int or type(mtime_ns) is not int or state not in STATES:
        return None
    if not isinstance(export, str) or not isinstance(detail, str):
        return None
    return SeenFile(size, mtime_ns, state, export, detail)


def load(path):
    """Read the document; a missing file is an empty store.

    A malformed top level or an unreadable file raises ``WatchError``.
    Malformed entries inside a well-formed document are dropped individually.
    """
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return WatchStore()
    except (OSError, ValueError) as error:
        raise WatchError('The watched-folder list could not be loaded.') from error
    if not isinstance(document, dict) or not isinstance(document.get('folders'), list):
        raise WatchError('The watched-folder list could not be loaded.')
    store = WatchStore()
    for entry in document['folders']:
        folder = _folder_from_document(entry)
        if folder is not None:
            store.folders.append(folder)
    seen = document.get('seen')
    if isinstance(seen, dict):
        folders_by_key = {key(folder.path): folder for folder in store.folders}
        for folder_key, records in seen.items():
            if not isinstance(folder_key, str) or not isinstance(records, dict):
                continue
            folder = folders_by_key.get(folder_key)
            bucket = {}
            for name, entry in records.items():
                item = _record_from_document(name, entry)
                if item is None:
                    continue
                if folder is not None:
                    name = _migrated_key(folder.path, name)
                    if name is None:
                        continue
                bucket[name] = item
            store.seen[folder_key] = bucket
    return store
