"""Update manifest parsing, version comparison, and checksum verification."""
import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from markseal import updates


class FakeResponse:
    def __init__(self, data, headers=None):
        self._data = data
        self._offset = 0
        self.headers = headers or {}

    def read(self, amount=-1):
        if amount < 0:
            chunk, self._offset = self._data[self._offset:], len(self._data)
            return chunk
        chunk = self._data[self._offset:self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def manifest(version='2.1.0', **overrides):
    document = {
        'version': version,
        'notes': 'Fixes and speed.',
        'page_url': 'https://example.test/v2.1.0',
        'downloads': {'windows-x64': {'url': 'https://example.test/setup.exe', 'sha256': 'a' * 64}},
    }
    document.update(overrides)
    return json.dumps(document).encode('utf-8')


class VersionTests(unittest.TestCase):
    def test_parse_version_strips_prefix_and_pads(self):
        self.assertEqual(updates.parse_version('v2.1'), (2, 1))
        self.assertEqual(updates.parse_version('2.0.0'), (2, 0, 0))

    def test_is_newer_compares_numerically(self):
        self.assertTrue(updates.is_newer('2.1.0', '2.0.0'))
        self.assertFalse(updates.is_newer('2.0.0', '2.0.0'))
        self.assertFalse(updates.is_newer('1.9.9', '2.0.0'))
        self.assertTrue(updates.is_newer('2.0.10', '2.0.9'))


class PlatformTests(unittest.TestCase):
    def test_platform_key_covers_x64_and_arm64(self):
        cases = (
            ('win32', 'AMD64', 'windows-x64'),
            ('win32', 'ARM64', 'windows-aarch64'),
            ('linux', 'x86_64', 'linux-x64'),
            ('linux', 'aarch64', 'linux-aarch64'),
            ('darwin', 'x86_64', 'macos-x64'),
            ('darwin', 'arm64', 'macos-aarch64'),
        )
        for system, machine, expected in cases:
            with self.subTest(system=system, machine=machine):
                with unittest.mock.patch.object(updates.sys, 'platform', system), \
                     unittest.mock.patch.object(updates.platform, 'machine', return_value=machine):
                    self.assertEqual(updates.platform_key(), expected)


class CheckTests(unittest.TestCase):
    def test_returns_update_when_manifest_is_newer(self):
        def opener(url):
            return FakeResponse(manifest())

        with unittest.mock.patch.object(updates, 'platform_key', return_value='windows-x64'):
            info = updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json', opener=opener)
        self.assertIsNotNone(info)
        self.assertEqual(info.version, '2.1.0')
        self.assertEqual(info.notes, 'Fixes and speed.')
        self.assertEqual(info.download_url, 'https://example.test/setup.exe')

    def test_returns_none_when_up_to_date(self):
        def opener(url):
            return FakeResponse(manifest(version='2.0.0'))

        with unittest.mock.patch.object(updates, 'platform_key', return_value='windows-x64'):
            self.assertIsNone(updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json', opener=opener))

    def test_network_and_parse_failures_raise_update_error(self):
        def broken(url):
            raise OSError('offline')

        with self.assertRaises(updates.UpdateError):
            updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json', opener=broken)
        with self.assertRaises(updates.UpdateError):
            updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json',
                                     opener=lambda url: FakeResponse(b'not json'))

    def test_missing_platform_artifact_raises(self):
        def opener(url):
            return FakeResponse(manifest(downloads={'linux-x64': {'url': 'x'}}))

        with unittest.mock.patch.object(updates, 'platform_key', return_value='windows-x64'):
            with self.assertRaises(updates.UpdateError):
                updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json', opener=opener)


    def test_missing_checksum_is_rejected(self):
        def opener(url):
            return FakeResponse(manifest(downloads={
                'windows-x64': {'url': 'https://example.test/setup.exe', 'sha256': ''}}))

        with unittest.mock.patch.object(updates, 'platform_key', return_value='windows-x64'):
            with self.assertRaises(updates.UpdateError):
                updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json',
                                         opener=opener)

    def test_non_https_urls_are_rejected(self):
        with self.assertRaises(updates.UpdateError):
            updates.check_for_update(current='2.0.0', url='http://example.test/manifest.json',
                                     opener=lambda url: FakeResponse(manifest()))

        def opener(url):
            return FakeResponse(manifest(downloads={
                'windows-x64': {'url': 'http://example.test/setup.exe', 'sha256': 'a' * 64}}))

        with unittest.mock.patch.object(updates, 'platform_key', return_value='windows-x64'):
            with self.assertRaises(updates.UpdateError):
                updates.check_for_update(current='2.0.0', url='https://example.test/manifest.json',
                                         opener=opener)


class DownloadTests(unittest.TestCase):
    def info(self, payload):
        return updates.UpdateInfo('2.1.0', '', '', 'https://example.test/setup.exe',
                                  hashlib.sha256(payload).hexdigest())

    def test_download_verifies_checksum(self):
        payload = b'installer-bytes'
        with TemporaryDirectory() as folder:
            path = updates.download_update(
                self.info(payload), directory=folder,
                opener=lambda url: FakeResponse(payload, {'Content-Length': str(len(payload))}))
            self.assertEqual(Path(path).read_bytes(), payload)

    def test_checksum_mismatch_removes_the_file(self):
        payload = b'installer-bytes'
        bad = updates.UpdateInfo('2.1.0', '', '', 'https://example.test/setup.exe', 'deadbeef')
        with TemporaryDirectory() as folder:
            with self.assertRaises(updates.UpdateError):
                updates.download_update(
                    bad, directory=folder,
                    opener=lambda url: FakeResponse(payload, {'Content-Length': str(len(payload))}))
            self.assertEqual(list(Path(folder).iterdir()), [])


    def test_missing_checksum_is_rejected_before_download(self):
        payload = b'installer-bytes'
        info = updates.UpdateInfo('2.1.0', '', '', 'https://example.test/setup.exe', '')
        with TemporaryDirectory() as folder:
            with self.assertRaises(updates.UpdateError):
                updates.download_update(info, directory=folder,
                                        opener=lambda url: FakeResponse(payload))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_non_https_download_is_rejected(self):
        info = updates.UpdateInfo('2.1.0', '', '', 'http://example.test/setup.exe', 'a' * 64)
        with TemporaryDirectory() as folder:
            with self.assertRaises(updates.UpdateError):
                updates.download_update(info, directory=folder,
                                        opener=lambda url: FakeResponse(b'x'))


if __name__ == '__main__':
    unittest.main()
