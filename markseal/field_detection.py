"""Deterministic personal-field detection from labelled OCR lines."""
from __future__ import annotations

import re
import statistics

from .suggestions import SuggestionSet, padded_box

LABELS = {
    'Personal names': (
        'name', 'full name', 'first name', 'given name', 'last name', 'surname',
        'family name', 'middle name', 'legal name', 'customer name', 'employee name',
        'contact name', 'patient name', 'account holder', 'account name', 'cardholder name',
    ),
    'Postal addresses': (
        'address', 'addr', 'home address', 'mailing address', 'postal address',
        'street address', 'residence address', 'address line 1', 'address line 2',
        'property address', 'billing address', 'shipping address', 'delivery address',
        'residential address', 'current address', 'permanent address',
        'city', 'town', 'state', 'province', 'zip', 'zip code', 'postal code', 'postcode',
    ),
    'Dates of birth': (
        'dob', 'date of birth', 'birth date', 'birthdate', 'born',
    ),
    'License & ID numbers': (
        'license', 'licence', 'license no', 'licence no', 'license number',
        'licence number', 'driver license', 'drivers license', 'dl', 'dln', 'dl no',
        'id', 'id no', 'id number', 'identification', 'identification number',
        'passport', 'passport no', 'passport number', 'national id',
    ),
}
STOP_LABELS = frozenset({'email', 'phone', 'tel', 'telephone', 'mobile'})
VALUE_STOP_WORDS = frozenset({'is', 'of', 'the', 'and', 'for', 'at', 'in', 'on', 'to', 'was'})
PLACEHOLDERS = frozenset({'n/a', 'na', 'none', 'null', '-', '--', '—'})
MONTHS = frozenset({
    'january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december', 'jan', 'feb', 'mar', 'apr',
    'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec',
})
BULLETS = frozenset({'-', '—', '•', '·', '*'})


def _normal(text):
    text = text.lower().replace('’', "'").replace("'", '')
    return text.strip(':#.,;()[]{}*_- ').strip()


def _label_table():
    table = []
    for category, phrases in LABELS.items():
        for phrase in phrases:
            tokens = tuple(_normal(part) for part in phrase.split())
            if tokens:
                table.append((tokens, category))
    table.sort(key=lambda item: -len(item[0]))
    return tuple(table)


_LABELS = _label_table()


def _is_filler(text):
    normalized = _normal(text)
    if not normalized or normalized in BULLETS:
        return True
    return re.fullmatch(r'\d+[.)]?', normalized) is not None


def _label_at(words, index):
    for tokens, category in _LABELS:
        if index + len(tokens) > len(words):
            continue
        found = tuple(_normal(words[index + offset][0]) for offset in range(len(tokens)))
        if found == tokens:
            return len(tokens), category
    return None


def _has_separator(words, end_index):
    if words[end_index][0].rstrip().endswith((':', '#', '.')):
        return True
    if end_index + 1 < len(words):
        following = words[end_index + 1][0].lstrip()
        if following.startswith(('#', ':')):
            return True
    return False


def _is_separator(text):
    normalized = _normal(text)
    return not normalized or normalized in BULLETS


def _line_height(words):
    heights = [max(1, word[4] - word[2]) for word in words]
    return statistics.median(heights) if heights else 24


def _value_words(words, start, height, address=False):
    value = []
    previous = None
    index = start
    while index < len(words):
        word = words[index]
        match = _label_at(words, index)
        if match is not None:
            length, category = match
            if (not address or category != 'Postal addresses'
                    or _has_separator(words, index + length - 1)):
                break
        if _normal(word[0]) in STOP_LABELS:
            break
        if previous is not None and word[1] - previous[3] > 2.5 * height:
            break
        if value or not _is_separator(word[0]):
            value.append(word)
        previous = word
        index += 1
    return value, index


def _column_start(words, left, height):
    for index, word in enumerate(words):
        if left - 0.5 * height <= word[1] <= left + 8 * height:
            return index
    return None


def _next_line_value(lines, line_index, left, bottom, height):
    if line_index + 1 >= len(lines):
        return []
    following = lines[line_index + 1]
    if not following:
        return []
    top = min(word[2] for word in following)
    if top - bottom > 1.5 * height:
        return []
    start = _column_start(following, left, height)
    if start is None:
        return []
    value, _ = _value_words(following, start, height)
    return value


def _ends_wrap(value):
    return bool(value) and value[-1][0].rstrip().endswith((',', '-', '–'))


def _looks_like_label_line(words):
    return len(words) <= 4 and words[-1][0].rstrip().endswith((':', '#'))


def _extend_address(lines, line_index, value, left, bottom, height):
    result = list(value)
    current_bottom = max((word[4] for word in value), default=bottom)
    remaining = 2 if not value else (1 if _ends_wrap(value) else 0)
    next_index = line_index + 1
    while remaining > 0 and next_index < len(lines):
        following = lines[next_index]
        if not following:
            break
        top = min(word[2] for word in following)
        if top - current_bottom > 1.5 * height:
            break
        start = _column_start(following, left, height)
        if start is None:
            break
        run, _ = _value_words(following, start, height, address=True)
        if not run or _normal(run[0][0]) in VALUE_STOP_WORDS or _looks_like_label_line(run):
            break
        result.extend(run)
        current_bottom = max(word[4] for word in run)
        remaining -= 1
        next_index += 1
    return result


def _valid_value(value, category):
    text = ' '.join(word[0] for word in value)
    compact = ''.join(character for character in text if character.isalnum())
    if not compact or compact.lower() in PLACEHOLDERS:
        return False
    if category == 'License & ID numbers':
        return len(compact) >= 4 and any(character.isdigit() for character in compact)
    if category == 'Dates of birth':
        if len(compact) < 4 or not any(character.isdigit() for character in compact):
            return False
        groups = re.findall(r'\d+', text)
        month = any(_normal(word[0]) in MONTHS for word in value)
        return len(groups) >= 2 or month
    return len(compact) >= 2


def field_boxes(lines, size, min_confidence, categories):
    selected = set(categories) & set(LABELS)
    if not selected:
        return [], {}
    lines = [list(line) for line in lines if line]
    found = SuggestionSet()
    for line_index, words in enumerate(lines):
        if not words:
            continue
        height = _line_height(words)
        index = 0
        while index < len(words):
            match = _label_at(words, index)
            if match is None:
                index += 1
                continue
            length, category = match
            if category not in selected:
                index += length
                continue
            at_start = all(_is_filler(word[0]) for word in words[:index])
            if at_start and words[index + length - 1][0].rstrip().endswith(','):
                index += length
                continue
            if not at_start and not _has_separator(words, index + length - 1):
                index += length
                continue
            label_left = words[index][1]
            label_bottom = words[index + length - 1][4]
            value, stop = _value_words(
                words, index + length, height, category == 'Postal addresses')
            if category in ('Personal names', 'Postal addresses') and value:
                if _normal(value[0][0]) in VALUE_STOP_WORDS:
                    value = []
            if category == 'Postal addresses':
                value = _extend_address(
                    lines, line_index, value, label_left, label_bottom, height)
            elif not value:
                value = _next_line_value(
                    lines, line_index, label_left, label_bottom, height)
            kept = [word for word in value if word[5] >= min_confidence]
            if kept and _valid_value(kept, category):
                found.add(padded_box(kept, size), category)
            index = max(index + length, stop)
    return found.parts()
