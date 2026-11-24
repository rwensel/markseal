"""Shared imports and fakes for the MarkSeal test suite."""
import subprocess
import json
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock, Thread
from PIL import Image
from unittest.mock import patch
from types import SimpleNamespace
from markseal import rapidocr_backend
from markseal.rapidocr_backend import result_to_tsv
from markseal.performance_log import PerformanceRun, stage
from markseal.core import (
    PRESETS, BoxList, FolderImage, apply_redactions, batch_worker_count, detect_regions,
    new_ocr_boxes, pattern_from_text, pixelate, read_area_text, recognize_regions, save_export,
    scan_folder_image, text_from_tsv, value_pattern_expression, value_pattern_types,
)
from markseal.review import Review
from markseal.jobs import JobRunner, progress_line
from markseal.boxset import BoxSet, image_status
from markseal.ocr import RapidEngine, make_engine
from markseal import preferences
from markseal.preferences import Preferences, PreferencesError
from markseal import patterns
from markseal import themes
from markseal import export
from markseal import core
from markseal.viewport import Viewport
from markseal import audit_exports




class FakeEngine:
    def __init__(self, tsv='', outcomes=None):
        self.tsv = tsv
        self.outcomes = list(outcomes) if outcomes is not None else None
        self.calls = []
        self.single_label = False
        self.label = ('', 0.0)

    def recognize(self, image, *, psm=None, cancel=None, timeout=120):
        self.calls.append({'psm': psm, 'timeout': timeout, 'size': image.size})
        if self.outcomes is None:
            return self.tsv
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def read_label(self, crop):
        return self.label
