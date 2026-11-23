"""Validation for blocked-pattern input, with no Qt dependency."""
from __future__ import annotations

import re

EMPTY_MESSAGE = 'Enter a pattern or cancel.'


def pattern_error(pattern):
    text = pattern.strip()
    if not text:
        return EMPTY_MESSAGE
    try:
        re.compile(text)
    except re.error as error:
        return str(error)
    return None


def compile_error(pattern):
    try:
        re.compile(pattern)
    except re.error as error:
        return str(error)
    return None


def duplicate_pattern(entries, pattern):
    folded = pattern.strip().casefold()
    return any(entry['pattern'].casefold() == folded for entry in entries)


def blocked_entry(text, pattern):
    return {'text': text.strip(), 'pattern': pattern.strip(), 'enabled': True}


def rename_entry(entry, name):
    name = name.strip()
    if name == entry.get('text', ''):
        return False
    entry['text'] = name
    return True
