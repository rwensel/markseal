from __future__ import annotations

from . import watch_scan
from .watch_document import (
    POLICIES, PRESENTED, SeenFile, WatchError, key, within,
)


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
        if within(other.path, folder.path) or within(
                folder.path, other.path):
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
    images = watch_scan.scan(store, folder)
    if images is None:
        raise WatchError('The folder could not be read.')
    baseline = {}
    for entry in images:
        baseline[entry.key] = SeenFile(
            entry.stamp.st_size, entry.stamp.st_mtime_ns, PRESENTED)
    store.seen[key(folder.path)] = baseline
    store.folders.append(folder)
    return folder


def remove(store, path):
    """Drop a watch and the records that belong to it."""
    target = key(path)
    store.folders = [folder for folder in store.folders if key(folder.path) != target]
    store.seen.pop(target, None)
