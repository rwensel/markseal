from __future__ import annotations

import re
from dataclasses import dataclass

from . import images, ocr
from . import preferences as preference_module
from .boxset import BoxList


class ScanError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ScannedImage:
    found: BoxList
    incomplete: tuple


@dataclass(frozen=True)
class ScannedFile:
    stamp: tuple
    found: BoxList
    incomplete: tuple


class Scan:
    def __init__(self, preferences, *, engine_factory=ocr.make_engine,
                 image_reader=images.read_folder_image):
        self.preferences = preferences
        self._image_reader = image_reader
        try:
            self.engine = engine_factory()
            self.settings = preference_module.scan_settings(preferences)
        except OSError as error:
            raise ScanError('unavailable', str(error)) from error
        except (ValueError, re.error) as error:
            raise ScanError('invalid_settings', str(error)) from error

    def image(self, image, *, area=None, progress=None, cancel=None):
        incomplete = []
        found = ocr.recognize_regions(
            image,
            self.engine,
            self.settings,
            self.preferences.enhanced_ocr,
            cancel,
            color_assisted=self.preferences.color_ocr,
            incomplete=incomplete,
            area=area,
            progress=progress,
        )
        return ScannedImage(found, tuple(incomplete))

    def file(self, path, expected, *, area=None, cancel=None):
        image, stamp = self._image_reader(path, expected)
        result = self.image(image, area=area, cancel=cancel)
        return ScannedFile(stamp, result.found, result.incomplete)
