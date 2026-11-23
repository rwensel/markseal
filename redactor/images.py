"""Supported image files, change stamps and safe reads."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .performance_log import timed


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


def file_stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


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
