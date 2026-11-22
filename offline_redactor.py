"""Offline image redactor. Requires Python 3, Pillow, and PySide6. No network calls."""
from redactor.core import (
    IMAGE_SUFFIXES,
    PATTERNS,
    PRESETS,
    FolderImage,
    ScanCancelled,
    apply_redactions,
    detect_regions,
    find_tesseract,
    new_ocr_boxes,
    output_path,
    pixelate,
    preferences_path,
    read_folder_image,
    recognize_regions,
    save_export,
    write_folder_copy,
    write_preferences,
)
from redactor.review import Review
from redactor.app import main

if __name__ == '__main__':
    raise SystemExit(main())
