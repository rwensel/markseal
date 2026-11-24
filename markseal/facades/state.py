"""Session state shared by the QML facades."""
from __future__ import annotations

import os
from pathlib import Path

from .. import ocr, preferences
from ..review import Review


class Facades:
    def __init__(self):
        self.review = None
        self.folder = None
        self.settings = None
        self.watches = None


class SessionState:
    def __init__(self, preferences_file=None):
        self.review = Review()
        self.entries = []
        self.active = None
        self.row_selection = set()
        self.row_anchor = None
        self.folder = None
        self.output_directory = None
        self.output_directory_override = None
        self.preference_file = (Path(preferences_file) if preferences_file
                                else preferences.preferences_path())
        self.parallel_limit = max(1, min(16, os.cpu_count() or 4))
        self.pasted_image = False
        self.preferences = preferences.defaults()
        self.facades = Facades()
        self.alerts = None
        self.jobs = None

    def scan_engine(self):
        return ocr.make_engine()

    def output_directory_for(self, folder):
        if folder is None:
            return None
        watches = self.facades.watches
        if watches is not None:
            directory = watches.output_for(folder)
            if directory is not None:
                return directory
        return self.output_directory_override or Path(folder) / 'redacted'

    def store_active(self):
        if self.active is None or self.review.image is None:
            return
        if not 0 <= self.active < len(self.entries):
            return
        entry = self.entries[self.active]
        if entry.reviewed and not self.review.confirmed:
            entry.saved = False
        entry.reviewed = self.review.confirmed

    def scan_settings(self):
        return preferences.scan_settings(self.preferences)

    def scan_metrics(self):
        return preferences.scan_metrics(self.preferences)
