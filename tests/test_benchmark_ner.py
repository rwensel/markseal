"""Accuracy benchmark scoring."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('benchmark_ner', ROOT / 'packaging' / 'benchmark_ner.py')
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


class BenchmarkTests(unittest.TestCase):
    def test_score_counts_true_and_false_positives(self):
        result = benchmark.score(
            [{'Personal names': ['Katie Miller']}],
            [{'Personal names': ['Katie Miller', 'Software Engineer']}])
        self.assertEqual(result['Personal names']['precision'], 0.5)
        self.assertEqual(result['Personal names']['recall'], 1.0)

    def test_score_treats_missing_detections_as_false_negatives(self):
        result = benchmark.score(
            [{'Postal addresses': ['129 Maple Ave']}],
            [{}])
        self.assertEqual(result['Postal addresses']['precision'], 1.0)
        self.assertEqual(result['Postal addresses']['recall'], 0.0)
