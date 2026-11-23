"""One owner for settings defaults, the persisted document and validation.

The document uses snake_case keys; the QML form and ``audit_exports.py``
are adapters that read this one schema.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile

ENGINE_NAMES = ('Tesseract', 'RapidOCR')
METHOD_NAMES = ('Pixelate', 'Solid black')
DEFAULT_TEMPLATE = '{stem}_redacted'
MAX_PARALLEL = 16


class PreferencesError(ValueError):
    """The saved settings could not be read or validated."""


@dataclass
class Preferences:
    sensitivity: str = 'Focused'
    confidence: int = 50
    all_text: bool = False
    enhanced_ocr: bool = False
    color_ocr: bool = False
    show_rules: bool = False
    ocr_engine: str = 'Tesseract'
    method: str = 'Pixelate'
    output_directory: str = ''
    filename_template: str = DEFAULT_TEMPLATE
    include_log: bool = True
    parallel_images: int = 1
    categories: tuple = ()
    blocked_patterns: list = field(default_factory=list)

    def document(self):
        return {
            'sensitivity': self.sensitivity,
            'confidence': self.confidence,
            'all_text': self.all_text,
            'enhanced_ocr': self.enhanced_ocr,
            'color_ocr': self.color_ocr,
            'ocr_engine': self.ocr_engine,
            'categories': list(self.categories),
            'redaction_method': self.method,
            'output_directory': self.output_directory,
            'filename_template': self.filename_template,
            'include_log': self.include_log,
            'parallel_images': self.parallel_images,
            'show_rules': self.show_rules,
            'blocked_patterns': [dict(entry) for entry in self.blocked_patterns],
        }


def _catalog():
    from .core import PATTERNS, PRESETS, output_path
    return PATTERNS, PRESETS, output_path


def preferences_path():
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / '.config'
    return base / 'OfflineScreenshotRedactor' / 'settings.json'


def _category_names(names):
    patterns, _, _ = _catalog()
    chosen = set(names or ())
    return tuple(name for name in patterns if name in chosen)


def _valid_template(template, source):
    _, _, output_path = _catalog()
    try:
        output_path(Path('.'), template, source or Path('example.png'), 1)
    except (ValueError, KeyError, IndexError, AttributeError):
        return False
    return True


def defaults():
    _, presets, _ = _catalog()
    return Preferences(categories=_category_names(presets['Focused']))


def _blocked_entry(entry):
    if not isinstance(entry, dict):
        return None
    text = entry.get('text')
    pattern = entry.get('pattern')
    if not isinstance(text, str) or not isinstance(pattern, str) or not pattern.strip():
        return None
    try:
        re.compile(pattern)
    except re.error:
        return None
    enabled = entry.get('enabled', True)
    return {'text': text.strip(), 'pattern': pattern.strip(),
            'enabled': enabled if isinstance(enabled, bool) else True}


def from_document(document, parallel_limit=MAX_PARALLEL):
    _, presets, _ = _catalog()
    limit = max(1, int(parallel_limit))
    preferences = defaults()
    preset = document.get('sensitivity')
    if isinstance(preset, str) and preset in {*presets, 'Custom'}:
        preferences.sensitivity = preset
    categories = document.get('categories')
    if isinstance(categories, list):
        preferences.categories = _category_names(categories)
    threshold = document.get('confidence')
    if type(threshold) is int and 0 <= threshold <= 100:
        preferences.confidence = threshold
    for key, attribute in (('all_text', 'all_text'), ('enhanced_ocr', 'enhanced_ocr'),
                           ('color_ocr', 'color_ocr'), ('show_rules', 'show_rules'),
                           ('include_log', 'include_log')):
        if isinstance(document.get(key), bool):
            setattr(preferences, attribute, document[key])
    engine = document.get('ocr_engine')
    if engine in ENGINE_NAMES:
        preferences.ocr_engine = engine
    method = document.get('redaction_method')
    if method in METHOD_NAMES:
        preferences.method = method
    workers = document.get('parallel_images')
    if type(workers) is int:
        preferences.parallel_images = max(1, min(limit, workers))
    directory = document.get('output_directory')
    if isinstance(directory, str):
        path = Path(directory) if directory else None
        if path is None or path.is_absolute():
            preferences.output_directory = str(path) if path else ''
    template = document.get('filename_template')
    if isinstance(template, str) and template.strip() and _valid_template(template, None):
        preferences.filename_template = template
    blocked = document.get('blocked_patterns')
    if isinstance(blocked, list):
        loaded = [entry for entry in (_blocked_entry(item) for item in blocked) if entry]
        preferences.blocked_patterns = loaded
    legacy = document.get('custom_pattern')
    if isinstance(legacy, str) and legacy.strip():
        legacy = legacy.strip()
        try:
            re.compile(legacy)
        except re.error:
            return preferences
        if not any(entry['pattern'].casefold() == legacy.casefold()
                   for entry in preferences.blocked_patterns):
            preferences.blocked_patterns.append({
                'text': 'Imported custom pattern', 'pattern': legacy, 'enabled': True,
            })
    return preferences


def load(path, parallel_limit=MAX_PARALLEL):
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return defaults()
    except (OSError, ValueError) as error:
        raise PreferencesError('Saved settings could not be loaded. Using defaults.') from error
    if not isinstance(document, dict):
        raise PreferencesError('Saved settings could not be loaded. Using defaults.')
    return from_document(document, parallel_limit)


def write_preferences(path, preferences):
    path = Path(path)
    document = (preferences.document() if isinstance(preferences, Preferences)
                else dict(preferences))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _checked_confidence(value):
    threshold = int(value)
    if not 0 <= threshold <= 100:
        raise ValueError('OCR confidence must be between 0 and 100.')
    return threshold


def apply_form(current, form, parallel_limit, source=None):
    _, presets, output_path = _catalog()
    limit = max(1, int(parallel_limit))
    threshold = _checked_confidence(form['confidence'])
    workers = int(form['parallel_images'])
    if not 1 <= workers <= limit:
        raise ValueError(f'Parallel image jobs must be between 1 and {limit}.')
    chosen = Path(form['output_directory'].strip()) if form['output_directory'].strip() else None
    if chosen is not None and not chosen.is_absolute():
        raise ValueError('Choose an absolute output folder.')
    name = form['filename_template'].strip()
    if not name:
        raise ValueError('Enter a filename template.')
    output_path(chosen or Path('.'), name, source or Path('example.png'), 1)
    sensitivity = form['sensitivity']
    if isinstance(sensitivity, str) and sensitivity not in {*presets, 'Custom'}:
        raise ValueError('Choose a detection preset.')
    engine = form['ocr_engine']
    if engine not in ENGINE_NAMES:
        raise ValueError('Choose Tesseract or RapidOCR.')
    method = form['method']
    if method not in METHOD_NAMES:
        raise ValueError('Choose pixelation or solid black.')
    return Preferences(
        sensitivity=sensitivity,
        confidence=threshold,
        all_text=bool(form['all_text']),
        enhanced_ocr=bool(form['enhanced_ocr']),
        color_ocr=bool(form['color_ocr']),
        show_rules=current.show_rules,
        ocr_engine=engine,
        method=method,
        output_directory=str(chosen) if chosen is not None else '',
        filename_template=name,
        include_log=bool(form['include_log']),
        parallel_images=workers,
        categories=_category_names(form['categories']),
        blocked_patterns=[dict(entry) for entry in current.blocked_patterns],
    )


def scan_settings(preferences):
    if not 0 <= preferences.confidence <= 100:
        raise ValueError('OCR confidence must be between 0 and 100.')
    learned = tuple(
        (f'Blocked pattern: {entry["text"]}' if entry['text'] else 'Blocked pattern',
         entry['pattern'])
        for entry in preferences.blocked_patterns if entry['enabled']
    )
    return (preferences.all_text, set(preferences.categories), preferences.confidence, '', learned)


def scan_metrics(preferences):
    return {
        'engine': preferences.ocr_engine,
        'confidence': preferences.confidence,
        'enhanced': preferences.enhanced_ocr,
        'color_assisted': preferences.color_ocr,
        'sensitivity': preferences.sensitivity,
        'builtin_category_count': len(preferences.categories),
        'blocked_patterns': sum(1 for entry in preferences.blocked_patterns if entry['enabled']),
        'all_text': preferences.all_text,
    }


def enabled_blocked_patterns(path):
    preferences = load(path)
    candidates = [entry['pattern'] for entry in preferences.blocked_patterns
                  if entry['enabled']]
    valid = []
    for pattern in candidates:
        try:
            re.compile(pattern)
        except re.error:
            continue
        if pattern not in valid:
            valid.append(pattern)
    return tuple(valid)
