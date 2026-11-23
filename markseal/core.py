"""Compatibility facade re-exporting Markseal's local processing modules.

Nothing imported here touches the network or the desktop UI.
"""
from __future__ import annotations

from .boxset import (
    BoxList, FolderImage, new_ocr_boxes, same_region, strip_contained_selected,
)
from .detection import (
    PATTERNS, PATTERN_TYPE_EXPRESSIONS, PATTERN_TYPE_LABELS, PRESETS,
    _learned_pattern_rules, credential_boxes, detect_regions, learned_pattern_rules,
    pattern_from_text, value_pattern_expression, value_pattern_types,
)
from .export import output_path, save_export, write_folder_copy
from .images import IMAGE_SUFFIXES, file_stamp, read_folder_image
from .jobs import ScanCancelled, batch_worker_count
from .ocr import (
    RapidEngine, TesseractEngine, cancellable_ocr, find_tesseract, make_engine,
    read_area_text, recognize_regions, scan_folder_image, text_from_tsv,
)
from .preferences import preferences_path, write_preferences
from .redaction import apply_redactions, pixelate
