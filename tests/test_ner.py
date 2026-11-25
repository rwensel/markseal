"""Local PII NER runtime."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from markseal.ner import Prompt, _model_words, build_inputs, decode_spans, detect_entities, load_manifest


class FakeEncoding:
    ids = [1, 2, 3, 4, 5, 6]
    word_ids = [None, 0, 1, 2, 3, 4]


class FakeTokenizer:
    def encode(self, words, is_pretokenized=True):
        return FakeEncoding()


class FakeSession:
    def __init__(self, logits):
        self.logits = logits
        self.calls = 0

    def run(self, names, inputs):
        self.calls += 1
        return [self.logits]


def word(text, left, confidence=99):
    return (text, left, 20, left + 60, 44, confidence)


class NerTests(unittest.TestCase):
    def manifest(self, directory, max_words=400):
        path = Path(directory) / 'manifest.json'
        path.write_text(json.dumps({
            'id': 'test',
            'revision': 'test',
            'prompts': [
                {'prompt': 'person', 'category': 'Personal names', 'threshold': 0.6},
                {'prompt': 'address', 'category': 'Postal addresses', 'threshold': 0.6},
            ],
            'max_words': max_words,
        }), encoding='utf-8')
        return path.parent

    def test_model_words_split_alpha_slash_pairs(self):
        words = [word('John/Jane', 10), word('https://example.com', 80),
                 word('and/or', 200), word('12/14', 260)]
        model, sources = _model_words(words)
        self.assertEqual([item[0] for item in model],
                         ['John', 'Jane', 'https://example.com', 'and', 'or', '12/14'])
        self.assertIs(sources[0], words[0])
        self.assertIs(sources[1], words[0])

    def test_slash_pair_span_maps_to_original_box(self):
        words = [word('John/Jane', 10), word('Doe', 100)]
        logits = np.full((1, 3, 2, 3), 0.05)
        logits[0, 1, 0, 0] = 0.9
        logits[0, 2, 0, 1] = 0.9
        logits[0, 1:3, 0, 2] = 0.9
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, rules = detect_entities(
                [words], (300, 100), 50, {'Personal names'}, model_dir=root,
                session=FakeSession(logits), tokenizer=FakeTokenizer())
        self.assertEqual(boxes, [(6, 16, 164, 48)])
        self.assertEqual(rules[boxes[0]], ('Personal names',))

    def test_build_inputs_marks_prompt_words_zero(self):
        inputs, count = build_inputs(
            ['Katie', 'Miller'], ['<<ENT>>', 'person', '<<SEP>>'], FakeTokenizer())
        self.assertEqual(count, 2)
        self.assertEqual(inputs['words_mask'].tolist(), [[0, 0, 0, 0, 1, 2]])
        self.assertEqual(inputs['text_lengths'].tolist(), [[2]])

    def test_decode_spans_pairs_start_and_end_scores(self):
        logits = np.array([[[[0.9, 0.1, 0.9]], [[0.1, 0.9, 0.9]]]])
        spans = decode_spans(
            logits, ['Katie', 'Miller'], [Prompt('person', 'Personal names', 0.6)])
        self.assertEqual(spans[0][:3], (0, 1, 'Personal names'))

    def test_decode_spans_rejects_a_low_inside_word(self):
        logits = np.array([[[[0.9, 0.1, 0.9]], [[0.1, 0.1, 0.1]], [[0.1, 0.9, 0.9]]]])
        self.assertEqual(
            decode_spans(logits, ['a', 'b', 'c'],
                         [Prompt('person', 'Personal names', 0.6)]), [])

    def test_detect_entities_maps_a_span_to_a_box(self):
        logits = np.array([[[[0.9, 0.1, 0.9]], [[0.1, 0.9, 0.9]]]])
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, rules = detect_entities(
                [[word('Katie', 10), word('Miller', 80)]], (300, 100), 50,
                {'Personal names'}, model_dir=root, session=FakeSession(logits),
                tokenizer=FakeTokenizer())
        self.assertEqual(boxes, [(6, 16, 144, 48)])
        self.assertEqual(rules[boxes[0]], ('Personal names',))

    def test_missing_manifest_returns_empty(self):
        session = FakeSession(np.zeros((1, 2, 1, 3)))
        with tempfile.TemporaryDirectory() as folder:
            boxes, rules = detect_entities(
                [[word('Katie', 10), word('Miller', 80)]], (300, 100), 50,
                {'Personal names'}, model_dir=folder, session=session,
                tokenizer=FakeTokenizer())
        self.assertEqual((boxes, rules), ([], {}))
        self.assertEqual(session.calls, 0)

    def test_disabled_categories_skip_the_model(self):
        session = FakeSession(np.zeros((1, 2, 1, 3)))
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, rules = detect_entities(
                [[word('Katie', 10)]], (300, 100), 50, {'Emails'},
                model_dir=root, session=session, tokenizer=FakeTokenizer())
        self.assertEqual((boxes, rules), ([], {}))
        self.assertEqual(session.calls, 0)

    def test_low_confidence_words_reject_the_span(self):
        logits = np.array([[[[0.9, 0.1, 0.9]], [[0.1, 0.9, 0.9]]]])
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, _ = detect_entities(
                [[word('Katie', 10, 10), word('Miller', 80, 99)]], (300, 100), 50,
                {'Personal names'}, model_dir=root, session=FakeSession(logits),
                tokenizer=FakeTokenizer())
        self.assertEqual(boxes, [])

    def span_logits(self, length, category):
        values = np.full((1, length, 2, 3), 0.05)
        values[0, 0, category, 0] = 0.9
        values[0, length - 1, category, 1] = 0.9
        values[0, :, category, 2] = 0.9
        return values

    def test_code_shaped_span_is_not_a_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, _ = detect_entities(
                [[word('GC5678', 10)]], (300, 100), 50, {'Personal names'},
                model_dir=root, session=FakeSession(self.span_logits(1, 0)),
                tokenizer=FakeTokenizer())
        self.assertEqual(boxes, [])

    def test_address_without_a_street_cue_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, _ = detect_entities(
                [[word('Gate', 10), word('3', 80)]], (300, 100), 50,
                {'Personal names', 'Postal addresses'}, model_dir=root,
                session=FakeSession(self.span_logits(2, 1)), tokenizer=FakeTokenizer())
        self.assertEqual(boxes, [])

    def test_address_with_a_comma_is_kept(self):
        words = [word('123', 10), word('Fictitious', 80), word('Lane,', 150),
                 word('Imaginary', 220), word('City,', 290)]
        with tempfile.TemporaryDirectory() as folder:
            root = self.manifest(folder)
            boxes, rules = detect_entities(
                [words], (400, 100), 50, {'Personal names', 'Postal addresses'},
                model_dir=root, session=FakeSession(self.span_logits(len(words), 1)),
                tokenizer=FakeTokenizer())
        self.assertEqual(len(boxes), 1)
        self.assertEqual(rules[boxes[0]], ('Postal addresses',))

    def test_corrupt_manifest_returns_none(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'manifest.json').write_text('{', encoding='utf-8')
            self.assertIsNone(load_manifest(folder))
