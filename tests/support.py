"""Shared imports and fakes for the redactor test suite."""
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
from redactor import rapidocr_backend
from redactor.rapidocr_backend import result_to_tsv
from redactor.performance_log import PerformanceRun, stage
from redactor.core import (
    PRESETS, BoxList, FolderImage, apply_redactions, batch_worker_count, detect_regions,
    new_ocr_boxes, pattern_from_text, pixelate, read_area_text, recognize_regions, save_export,
    scan_folder_image, text_from_tsv, value_pattern_expression, value_pattern_types,
)
from redactor.review import Review
from redactor.jobs import JobRunner, progress_line
from redactor.boxset import BoxSet, image_status
from redactor.ocr import RapidEngine, TesseractEngine, make_engine
from redactor import preferences
from redactor.preferences import Preferences, PreferencesError
from redactor import patterns
from redactor import themes
from redactor import export
from redactor import core
from redactor.viewport import Viewport
from redactor import audit_exports




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
