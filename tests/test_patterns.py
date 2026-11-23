"""Blocked pattern validation and normalization."""
import unittest

from tests.support import (
    patterns,
)


class PatternDialogTests(unittest.TestCase):
    def test_pattern_validation_rejects_empty_and_invalid_expressions(self):
        self.assertEqual(patterns.pattern_error('   '), patterns.EMPTY_MESSAGE)
        self.assertIsNotNone(patterns.pattern_error('['))
        self.assertIsNone(patterns.pattern_error(r'\bsecret-\d+\b'))
        self.assertIsNone(patterns.compile_error(r'\bsecret-\d+\b'))
        self.assertIsNotNone(patterns.compile_error('('))

    def test_duplicate_patterns_are_case_insensitive_and_trimmed(self):
        entries = [{'pattern': r'\bToken-\d+\b', 'text': '', 'enabled': True}]
        self.assertTrue(patterns.duplicate_pattern(entries, r'  \bToken-\d+\b  '))
        self.assertFalse(patterns.duplicate_pattern(entries, r'\bother\b'))

    def test_blocked_entry_and_rename_normalize_whitespace(self):
        entry = patterns.blocked_entry('  Token  ', r'  \btoken\b  ')
        self.assertEqual(entry, {'text': 'Token', 'pattern': r'\btoken\b', 'enabled': True})
        self.assertTrue(patterns.rename_entry(entry, '  New name  '))
        self.assertEqual(entry['text'], 'New name')
        self.assertFalse(patterns.rename_entry(entry, 'New name'))
