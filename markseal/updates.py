"""The only network seam: check for, download, and hand off an app update."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

DEFAULT_MANIFEST_URL = 'https://example.invalid/markseal/latest.json'
MANIFEST_URL = os.environ.get('MARKSEAL_UPDATE_URL', DEFAULT_MANIFEST_URL)
TIMEOUT = 8


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
    parts = []
    for piece in str(text).strip().lstrip('vV').split('.'):
        digits = ''.join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    length = max(len(a), len(b))
    a += (0,) * (length - len(a))
    b += (0,) * (length - len(b))
    return a > b


def platform_key():
    if sys.platform.startswith('win'):
        return 'windows-x64'
    if sys.platform == 'darwin':
        return 'macos'
    return 'linux-x64'


def _open(url, timeout=TIMEOUT):
    request = urllib.request.Request(url, headers={'User-Agent': f'Markseal/{__version__}'})
    return urllib.request.urlopen(request, timeout=timeout)


def check_for_update(*, current=None, url=None, opener=None):
    current = current or __version__
    open_url = opener or _open
    try:
        with open_url(url or MANIFEST_URL) as response:
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
    return UpdateInfo(
        version=version.strip(),
        notes=str(document.get('notes', '')),
        page_url=str(document.get('page_url', '')),
        download_url=str(artifact['url']),
        sha256=str(artifact.get('sha256', '')),
    )


def download_update(info, *, directory=None, opener=None, progress=None):
    open_url = opener or _open
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
    if info.sha256 and digest.hexdigest().lower() != info.sha256.lower():
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
