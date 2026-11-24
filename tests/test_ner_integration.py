"""Real-model PII NER integration."""
import unittest
from pathlib import Path

from markseal.ner import MODEL_DIRECTORY, detect_entities


def word(text, left, top=20, width=60, confidence=99):
    return (text, left, top, left + width, top + 24, confidence)


@unittest.skipUnless((Path(MODEL_DIRECTORY) / 'model.onnx').is_file(),
                     'PII model not installed')
class NerIntegrationTests(unittest.TestCase):
    def test_resume_name_and_address_are_detected(self):
        lines = [
            [word('Name:', 0, width=50), word('Katie', 60), word('Miller', 130)],
            [word('Address:', 0, top=60, width=70), word('129', 80, top=60, width=40),
             word('Maple', 130, top=60), word('Ave,', 200, top=60, width=50),
             word('Anytown,', 260, top=60, width=80), word('USA', 350, top=60, width=40)],
        ]
        boxes, rules = detect_entities(
            lines, (800, 400), 50, {'Personal names', 'Postal addresses'})
        labels = {label for labels in rules.values() for label in labels}
        self.assertIn('Personal names', labels)
        self.assertIn('Postal addresses', labels)
