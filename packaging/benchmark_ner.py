"""Accuracy benchmark for local personal-data detection."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from markseal.detection import PERSONAL_CATEGORIES, detect_regions
from markseal.ner import available

HEADER = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
GATES = {
    'Personal names': {'precision': 0.95, 'recall': 0.80},
    'Postal addresses': {'precision': 0.95, 'recall': 0.80},
    'Dates of birth': {'precision': 0.95, 'recall': 0.90},
    'License & ID numbers': {'precision': 0.95, 'recall': 0.90},
}


def make_line(texts, top=20, gap=10):
    words = []
    left = 0
    for text in texts:
        width = max(20, 8 * len(text))
        words.append((text, left, top, left + width, top + 24, 99))
        left += width + gap
    return words


CASES = [
    {
        'name': 'resume',
        'lines': [
            make_line(['Name:', 'Katie', 'Miller']),
            make_line(['Address:', '129', 'Maple', 'Ave,', 'Anytown,', 'USA'], top=60),
            make_line(['DOB:', '01/15/1980'], top=100),
            make_line(['License', '#CSM1234567890'], top=140),
        ],
        'expected': {
            'Personal names': ['Katie Miller'],
            'Postal addresses': ['129 Maple Ave, Anytown, USA'],
            'Dates of birth': ['01/15/1980'],
            'License & ID numbers': ['#CSM1234567890'],
        },
    },
    {
        'name': 'bare-name',
        'lines': [make_line(['Katie', 'Miller'])],
        'expected': {'Personal names': ['Katie Miller']},
    },
    {
        'name': 'two-column',
        'lines': [[
            ('Name:', 0, 20, 64, 44, 99),
            ('Katie', 74, 20, 114, 44, 99),
            ('Miller', 124, 20, 174, 44, 99),
            ('DOB:', 400, 20, 444, 44, 99),
            ('01/15/1980', 454, 20, 534, 44, 99),
        ]],
        'expected': {
            'Personal names': ['Katie Miller'],
            'Dates of birth': ['01/15/1980'],
        },
    },
    {
        'name': 'wrapped-address',
        'lines': [
            make_line(['Address:']),
            make_line(['129', 'Maple', 'Ave,'], top=50),
            make_line(['Anytown,', 'USA'], top=80),
        ],
        'expected': {'Postal addresses': ['129 Maple Ave, Anytown, USA']},
    },
    {
        'name': 'mid-line-license',
        'lines': [
            make_line(['Certified', 'Scrum', 'Master', '(CSM)', '-', 'License',
                       '#CSM1234567890']),
        ],
        'expected': {'License & ID numbers': ['#CSM1234567890']},
    },
    {
        'name': 'control',
        'lines': [
            make_line(['Software', 'Engineer']),
            make_line(['Project', 'Manager'], top=60),
            make_line(['Global', 'Solutions', '(2015-2023)'], top=100),
            make_line(['Hobbies'], top=140),
        ],
        'expected': {},
    },
]


def tsv(lines):
    rows = [HEADER]
    for line_index, words in enumerate(lines, 1):
        for text, left, top, right, bottom, confidence in words:
            rows.append(
                f'1\t{line_index}\t{line_index}\t{line_index}\t{left}\t{top}\t'
                f'{right-left}\t{bottom-top}\t{confidence}\t{text}\n')
    return ''.join(rows)


def covered_text(lines, box):
    left, top, right, bottom = box
    hits = []
    for words in lines:
        for text, word_left, word_top, word_right, word_bottom, _ in words:
            center_x = (word_left + word_right) / 2
            center_y = (word_top + word_bottom) / 2
            if left <= center_x <= right and top <= center_y <= bottom:
                hits.append((word_top, word_left, text))
    return ' '.join(text for _, _, text in sorted(hits))


def detected(case):
    lines = case['lines']
    width = max((word[3] for words in lines for word in words), default=0) + 40
    height = max((word[4] for words in lines for word in words), default=0) + 40
    rules = {}
    boxes = detect_regions(tsv(lines), (width, height), categories=set(PERSONAL_CATEGORIES),
                           min_confidence=40, rules=rules, personal=True)
    found = {category: [] for category in PERSONAL_CATEGORIES}
    for box in boxes:
        text = covered_text(lines, box)
        for category in rules.get(box, ()):
            if category in found and text:
                found[category].append(text)
    return found


def score(expected, found):
    result = {}
    categories = set()
    for item in expected + found:
        categories.update(item)
    for category in sorted(categories):
        true_positive = 0
        false_positive = 0
        false_negative = 0
        for expected_item, found_item in zip(expected, found):
            wanted = set(expected_item.get(category, ()))
            actual = set(found_item.get(category, ()))
            true_positive += len(wanted & actual)
            false_positive += len(actual - wanted)
            false_negative += len(wanted - actual)
        precision = (true_positive / (true_positive + false_positive)
                     if true_positive + false_positive else 1.0)
        recall = (true_positive / (true_positive + false_negative)
                  if true_positive + false_negative else 1.0)
        result[category] = {
            'precision': precision,
            'recall': recall,
            'true_positive': true_positive,
            'false_positive': false_positive,
            'false_negative': false_negative,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not available():
        print('PII model not installed; run packaging/fetch_ner_model.py', file=sys.stderr)
        return 2
    expected = [case['expected'] for case in CASES]
    found = [detected(case) for case in CASES]
    metrics = score(expected, found)
    failures = []
    for category, gates in GATES.items():
        values = metrics.get(category)
        if values is None:
            failures.append(f'{category}: no cases')
            continue
        if values['precision'] < gates['precision']:
            failures.append(f"{category}: precision {values['precision']:.2f}")
        if values['recall'] < gates['recall']:
            failures.append(f"{category}: recall {values['recall']:.2f}")
    for case, result in zip(CASES, found):
        if case['name'] == 'control' and any(result.values()):
            failures.append('control: unexpected suggestions')
    if args.json:
        print(json.dumps({'cases': [case['name'] for case in CASES],
                          'metrics': metrics, 'failures': failures}, indent=2))
    else:
        for category in sorted(metrics):
            values = metrics[category]
            print(f"{category:22} precision {values['precision']:.2f}  "
                  f"recall {values['recall']:.2f}  "
                  f"tp {values['true_positive']} fp {values['false_positive']} "
                  f"fn {values['false_negative']}")
        if failures:
            print('\nFAILED')
            for failure in failures:
                print(' ', failure)
        else:
            print('\nPASSED')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
