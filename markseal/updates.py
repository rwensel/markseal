"""The only network seam: check for, download, and hand off an app update."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import __version__

DEFAULT_MANIFEST_URL = 'https://updates.staginglane.app/stable/latest.json'
BETA_MANIFEST_URL = os.environ.get(
    'MARKSEAL_BETA_UPDATE_URL', 'https://updates.staginglane.app/beta/latest.json')
MANIFEST_URL = os.environ.get('MARKSEAL_UPDATE_URL', DEFAULT_MANIFEST_URL)
TIMEOUT = 8


def manifest_url(channel='stable'):
    override = os.environ.get('MARKSEAL_UPDATE_URL', '').strip()
    return override or (BETA_MANIFEST_URL if channel == 'beta' else DEFAULT_MANIFEST_URL)


class UpdateError(Exception):
    """The update check or download could not complete."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    notes: str
    page_url: str
    download_url: str
    sha256: str


def parse_version(text):
    base = str(text).strip().lstrip('vV').split('+', 1)[0].split('-', 1)[0]
    parts = []
    for piece in base.split('.'):
        digits = ''.join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


_PRERELEASE_RANKS = {'dev': 0, 'alpha': 1, 'a': 1, 'beta': 2, 'b': 2,
                     'pre': 3, 'preview': 3, 'rc': 3}


def _release_key(text):
    raw = str(text).strip().lstrip('vV').split('+', 1)[0]
    base, separator, suffix = raw.partition('-')
    if not separator:
        return parse_version(base), (4, 0)
    label = re.match(r'[a-z]+', suffix.lower())
    rank = _PRERELEASE_RANKS.get(label.group(0) if label else '', 0)
    number = int(''.join(ch for ch in suffix if ch.isdigit()) or 0)
    return parse_version(base), (rank, number)


def is_newer(latest, current):
    a_base, a_pre = _release_key(latest)
    b_base, b_pre = _release_key(current)
    length = max(len(a_base), len(b_base))
    a_base += (0,) * (length - len(a_base))
    b_base += (0,) * (length - len(b_base))
    return (a_base, a_pre) > (b_base, b_pre)


def platform_key():
    machine = platform.machine().lower()
    arm = machine in ('arm64', 'aarch64')
    if sys.platform.startswith('win'):
        return 'windows-aarch64' if arm else 'windows-x64'
    if sys.platform == 'darwin':
        return 'macos-aarch64' if arm else 'macos-x64'
    return 'linux-aarch64' if arm else 'linux-x64'


def _require_https(url, label):
    if urlparse(str(url)).scheme.lower() != 'https':
        raise UpdateError(f'{label} must use HTTPS.')


def _open(url, timeout=TIMEOUT):
    request = urllib.request.Request(url, headers={'User-Agent': f'Markseal/{__version__}'})
    return urllib.request.urlopen(request, timeout=timeout)


def check_for_update(*, current=None, url=None, opener=None):
    current = current or __version__
    open_url = opener or _open
    manifest_url = url or MANIFEST_URL
    _require_https(manifest_url, 'Update manifest URL')
    try:
        with open_url(manifest_url) as response:
            document = json.loads(response.read().decode('utf-8'))
    except (OSError, ValueError) as error:
        raise UpdateError(str(error)) from error
    if not isinstance(document, dict):
        raise UpdateError('Update manifest is not an object.')
    version = document.get('version')
    if not isinstance(version, str) or not version.strip():
        raise UpdateError('Update manifest has no version.')
    if not is_newer(version, current):
        return None
    downloads = document.get('downloads')
    artifact = downloads.get(platform_key()) if isinstance(downloads, dict) else None
    if not isinstance(artifact, dict) or not artifact.get('url'):
        raise UpdateError('No update for this platform.')
    download_url = str(artifact['url'])
    _require_https(download_url, 'Update download URL')
    sha256 = str(artifact.get('sha256', '')).strip()
    if not sha256:
        raise UpdateError('Update manifest has no checksum.')
    return UpdateInfo(
        version=version.strip(),
        notes=str(document.get('notes', '')),
        page_url=str(document.get('page_url', '')),
        download_url=download_url,
        sha256=sha256,
    )


def download_update(info, *, directory=None, opener=None, progress=None):
    open_url = opener or _open
    _require_https(info.download_url, 'Update download URL')
    expected = info.sha256.strip().lower()
    if not expected:
        raise UpdateError('Update has no checksum to verify.')
    directory = Path(directory or tempfile.mkdtemp(prefix='markseal-update-'))
    directory.mkdir(parents=True, exist_ok=True)
    name = Path(info.download_url.split('?')[0]).name or f'Markseal-{info.version}'
    target = directory / name
    digest = hashlib.sha256()
    try:
        with open_url(info.download_url) as response, open(target, 'wb') as stream:
            total = int(response.headers.get('Content-Length') or 0)
            done = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None and total:
                    progress(done / total)
    except OSError as error:
        target.unlink(missing_ok=True)
        raise UpdateError(str(error)) from error
    if digest.hexdigest().lower() != expected:
        target.unlink(missing_ok=True)
        raise UpdateError('Downloaded update failed its checksum.')
    return target


def launch_installer(path):
    path = str(path)
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except OSError as error:
        raise UpdateError(str(error)) from error
