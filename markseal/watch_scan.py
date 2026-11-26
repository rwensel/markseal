from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import images
from .watch_document import (
    EXPORTED, NEEDS_REVIEW, PRESENTED, QUEUED, STABLE_SECONDS, SeenFile,
    WatchCounts, export_targets, file_key, key,
)


def _settled(stamp, moment):
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
        records[entry.key] = SeenFile(
            entry.stamp.st_size, entry.stamp.st_mtime_ns, PRESENTED)
        changed = True
    return changed


def unseen(store, folder, *, now=None):
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
    if entry.incomplete_ocr:
        return NEEDS_REVIEW, 'Partial scan'
    if not entry.selected:
        return NEEDS_REVIEW, 'Nothing found'
    return EXPORTED, ''


def prune(store, folder, names):
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
