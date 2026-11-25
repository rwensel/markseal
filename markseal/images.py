"""Supported image files, change stamps, safe reads, and folder scans."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from PIL import Image

from .performance_log import timed


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


def file_stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _within(parent, child):
    """Whether ``child`` resolves inside ``parent``, across drives safe."""
    parent_text = os.path.normcase(str(parent))
    child_text = os.path.normcase(str(child))
    try:
        return os.path.commonpath([parent_text, child_text]) == parent_text
    except ValueError:
        return False


def _reparse(entry):
    """Whether an entry is a symlink or another Windows reparse point."""
    try:
        if entry.is_symlink():
            return True
        attributes = entry.stat(follow_symlinks=False).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))


def scan_images(folder, *, recursive=False, skip=(), problems=None):
    """``(relative, path, stat)`` for images in a folder, sorted by path.

    With ``recursive`` the walk covers subfolders but never follows symlinks or
    Windows junctions. Any directory in ``skip`` (such as a watch's export
    folder) is left out. An unreadable root returns ``None``; an unreadable
    subfolder is skipped so one bad folder does not hide the rest, and its
    relative path is appended to ``problems`` when a list is supplied.
    """
    folder = Path(folder)
    try:
        root = folder.resolve()
    except OSError:
        return None
    skipped = set()
    for item in skip:
        if item is None:
            continue
        try:
            skipped.add(Path(item).resolve())
        except OSError:
            continue
    found = []
    visited = set()
    unreadable = False

    def walk(directory, top):
        nonlocal unreadable
        try:
            resolved = directory.resolve()
        except OSError:
            if top:
                unreadable = True
            elif problems is not None:
                problems.append(directory.relative_to(folder).as_posix())
            return
        if resolved in visited or not _within(root, resolved):
            return
        visited.add(resolved)
        try:
            entries = os.scandir(directory)
        except OSError:
            if top:
                unreadable = True
            elif problems is not None:
                problems.append(directory.relative_to(folder).as_posix())
            return
        with entries:
            for entry in entries:
                try:
                    if recursive and _reparse(entry):
                        continue
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        if not recursive:
                            continue
                        try:
                            target = path.resolve()
                        except OSError:
                            continue
                        if target in skipped:
                            continue
                        walk(path, False)
                    elif entry.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                        found.append((path.relative_to(folder).as_posix(), path,
                                      entry.stat()))
                except OSError:
                    continue

    walk(folder, True)
    if unreadable:
        return None
    found.sort(key=lambda item: (item[0].casefold(), item[0]))
    return found


@timed('load_image')
def read_folder_image(path, expected=None):
    stamp = file_stamp(path)
    if expected is not None and stamp != expected:
        raise ValueError('Source changed. Reopen the folder and review the new image.')
    with Image.open(path) as source:
        image = source.convert('RGB')
    if file_stamp(path) != stamp:
        raise ValueError('Source changed while reading.')
    return image, stamp
