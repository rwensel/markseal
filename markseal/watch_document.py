from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

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
    pass


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


def key(path):
    return os.path.normcase(str(Path(path).resolve()))


def file_key(folder, path):
    relative = os.path.relpath(str(path), str(folder))
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        raise ValueError('File is outside the watch.')
    return os.path.normcase(Path(relative).as_posix())


def _migrated_key(folder, name):
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
    return Path(settings_path).parent / STORE_NAME


def find(store, path):
    target = key(path)
    for folder in store.folders:
        if key(folder.path) == target:
            return folder
    return None


def mark(store, folder, path, *, state, export=None, detail='', stamp=None):
    path = Path(path)
    if stamp is None:
        measured = path.stat()
        stamp = (measured.st_size, measured.st_mtime_ns)
    records = store.seen.setdefault(key(folder.path), {})
    records[file_key(folder.path, path)] = SeenFile(
        stamp[0], stamp[1], state, str(export) if export else '', detail)


def export_targets(store):
    targets = set()
    for records in store.seen.values():
        for record in records.values():
            if record.export:
                targets.add(key(record.export))
    return targets


def record(path):
    path = Path(path)
    stamp = path.stat()
    return SeenFile(stamp.st_size, stamp.st_mtime_ns, PRESENTED)


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
