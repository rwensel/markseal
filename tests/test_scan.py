import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest import mock

from PIL import Image

from markseal import preferences
from markseal.jobs import ScanCancelled
from markseal.scan import Scan, ScanError
from tests.support import FakeEngine

TSV = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
       '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n')


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.preferences = preferences.defaults()

    def scan(self, engine=None, **kwargs):
        return Scan(
            self.preferences,
            engine_factory=lambda: engine or FakeEngine(TSV),
            **kwargs,
        )

    def test_image_returns_suggestions_and_incomplete_passes(self):
        progress = []
        result = self.scan().image(
            Image.new('RGB', (200, 100), 'white'), progress=progress.append)

        self.assertTrue(result.found)
        self.assertEqual(result.incomplete, ())
        self.assertIn('Recognizing text', progress)

    def test_file_returns_the_stamp_and_suggestions(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'shot.png'
            Image.new('RGB', (200, 100), 'white').save(path)
            result = self.scan().file(path, None)
            stamp = path.stat()

        self.assertEqual(result.stamp, (stamp.st_size, stamp.st_mtime_ns))
        self.assertTrue(result.found)

    def test_cancellation_reaches_the_ocr_pass(self):
        cancel = Event()
        cancel.set()
        with self.assertRaises(ScanCancelled):
            self.scan().image(
                Image.new('RGB', (200, 100), 'white'), cancel=cancel)

    def test_unavailable_engine_is_classified(self):
        with self.assertRaises(ScanError) as caught:
            Scan(
                self.preferences,
                engine_factory=lambda: (_ for _ in ()).throw(OSError('missing')),
            )

        self.assertEqual(caught.exception.kind, 'unavailable')

    def test_invalid_settings_are_classified(self):
        with mock.patch('markseal.preferences.scan_settings',
                        side_effect=ValueError('bad pattern')):
            with self.assertRaises(ScanError) as caught:
                self.scan()

        self.assertEqual(caught.exception.kind, 'invalid_settings')

    def test_file_uses_the_injected_reader(self):
        image = Image.new('RGB', (30, 20), 'white')
        reader_calls = []

        def reader(path, expected):
            reader_calls.append((path, expected))
            return image, ('stamp-size', 'stamp-time')

        result = self.scan(image_reader=reader).file(Path('shot.png'), 'expected')

        self.assertEqual(reader_calls, [(Path('shot.png'), 'expected')])
        self.assertEqual(result.stamp, ('stamp-size', 'stamp-time'))


if __name__ == '__main__':
    unittest.main()
