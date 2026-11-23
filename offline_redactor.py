"""Offline image markseal. Requires Python 3, Pillow, and PySide6. No network calls."""
from markseal.core import (
    IMAGE_SUFFIXES,
    PATTERNS,
    PRESETS,
    FolderImage,
    ScanCancelled,
    apply_redactions,
    detect_regions,
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
from markseal.review import Review
from markseal.app import main

if __name__ == '__main__':
    raise SystemExit(main())
