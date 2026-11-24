"""Build THIRD_PARTY_NOTICES.txt from the installed runtime packages."""
from __future__ import annotations

import hashlib
import platform
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LICENSE_DIR = Path(__file__).resolve().parent / 'licenses'

# (display name, distribution, license, license file names, fallback license)
COMPONENTS = (
    ('Qt for Python (PySide6)', 'PySide6', 'LGPL-3.0-only',
     ('lgpl-3.0.txt', 'gpl-3.0.txt'), None),
    ('Shiboken6', 'shiboken6', 'LGPL-3.0-only', (), None),
    ('RapidOCR', 'rapidocr', 'Apache-2.0', ('LICENSE', 'MODEL_LICENSES.md'), None),
    ('ONNX Runtime', 'onnxruntime', 'MIT', ('LICENSE', 'ThirdPartyNotices.txt'), None),
    ('tokenizers', 'tokenizers', 'Apache-2.0', ('LICENSE',), None),
    ('OpenCV', 'opencv-python-headless', 'Apache-2.0',
     ('LICENSE.txt', 'LICENSE-3RD-PARTY.txt'), None),
    ('NumPy', 'numpy', 'BSD-3-Clause', ('LICENSE.txt',), None),
    ('Pillow', 'pillow', 'HPND', ('LICENSE',), None),
    ('pypdfium2 (PDFium)', 'pypdfium2', 'BSD-3-Clause AND Apache-2.0',
     ('LICENSES/Apache-2.0.txt', 'BUILD_LICENSES/pdfium.txt'), None),
    ('PyYAML', 'PyYAML', 'MIT', ('LICENSE',), None),
    ('tqdm', 'tqdm', 'MPL-2.0 AND MIT', ('LICENCE',), None),
    ('Shapely', 'shapely', 'BSD-3-Clause',
     ('LICENSE.txt', 'LICENSE_GEOS', 'LICENSE_win32'), None),
    ('pyclipper', 'pyclipper', 'MIT', ('LICENSE',), None),
    ('six', 'six', 'MIT', ('LICENSE',), None),
    ('protobuf', 'protobuf', 'BSD-3-Clause', ('LICENSE',), None),
    ('FlatBuffers', 'flatbuffers', 'Apache-2.0', (), 'Apache-2.0'),
    ('OmegaConf', 'omegaconf', 'BSD-3-Clause', ('LICENSE', 'LICENSE-antlr4'), None),
    ('requests', 'requests', 'Apache-2.0', ('LICENSE', 'NOTICE'), None),
    ('colorlog', 'colorlog', 'MIT', ('LICENSE',), None),
    ('coloredlogs', 'coloredlogs', 'MIT', ('LICENSE.txt',), None),
    ('humanfriendly', 'humanfriendly', 'MIT', ('LICENSE.txt',), None),
    ('certifi', 'certifi', 'MPL-2.0', ('LICENSE',), None),
    ('charset-normalizer', 'charset-normalizer', 'MIT', ('LICENSE',), None),
    ('idna', 'idna', 'BSD-3-Clause', ('LICENSE.md',), None),
    ('urllib3', 'urllib3', 'MIT', ('LICENSE.txt',), None),
    ('packaging', 'packaging', 'Apache-2.0 OR BSD-2-Clause',
     ('LICENSE', 'LICENSE.APACHE', 'LICENSE.BSD'), None),
    ('setuptools', 'setuptools', 'MIT', ('LICENSE',), None),
    ('pyreadline3', 'pyreadline3', 'BSD-3-Clause', ('LICENSE.md',), None),
    ('PyInstaller', 'pyinstaller', 'GPL-2.0-or-later with bootloader exception',
     ('COPYING.txt',), None),
)

FALLBACKS = {
    'Apache-2.0': ('opencv-python-headless', 'cv2/LICENSE.txt'),
    'MIT': ('onnxruntime', 'LICENSE'),
    'BSD-3-Clause': ('numpy', 'LICENSE.txt'),
}


def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return 'unknown'


def locate(name, relative):
    try:
        return Path(metadata.distribution(name).locate_file(relative))
    except (metadata.PackageNotFoundError, KeyError):
        return None


def license_paths(name, filenames):
    try:
        files = metadata.distribution(name).files or ()
    except metadata.PackageNotFoundError:
        return []
    found = []
    for recorded in files:
        text = str(recorded).replace('\\', '/')
        if not any(text == candidate or text.endswith('/' + candidate)
                   for candidate in filenames):
            continue
        path = Path(metadata.distribution(name).locate_file(recorded))
        if path.is_file():
            found.append(path)
    return sorted(set(found))


def main():
    sections = []
    seen = {}
    lines = [
        'THIRD-PARTY NOTICES',
        '',
        'MarkSeal is built with the open-source components below. Each component',
        'keeps its own license; the texts follow the component list.',
        '',
        'Qt for Python (PySide6) is used under LGPL-3.0. The Qt libraries stay',
        'replaceable in the installed application; the corresponding source is at',
        'https://code.qt.io/cgit/pyside/pyside-setup.git/ and',
        'https://download.qt.io/official_releases/QtForPython/.',
        '',
        'COMPONENTS',
        '',
    ]
    for display, dist, license_name, filenames, fallback in COMPONENTS:
        lines.append(f'{display} {version(dist)} - {license_name}')
    lines += [
        'Python ' + platform.python_version() + ' - PSF-2.0',
        'YuNet face detection model - MIT',
        'GLiNER PII Small model (Knowledgator/Wordcab) - Apache-2.0',
        'GLiNER runtime (urchade/GLiNER) - Apache-2.0',
        'Ettin encoder (jhu-clsp/ettin-encoder-68m) - MIT',
        '',
        'LICENSE TEXTS',
        '',
    ]

    entries = []
    for display, dist, license_name, filenames, fallback in COMPONENTS:
        paths = license_paths(dist, filenames)
        if not paths and fallback:
            source = FALLBACKS.get(fallback)
            path = locate(*source) if source else None
            paths = [path] if path and path.is_file() else []
        entries.append((display, license_name, paths))
    entries.append(('Python', 'PSF-2.0', [Path(sys.base_prefix) / 'LICENSE.txt']))
    entries.append(('YuNet face detection model', 'MIT', [LICENSE_DIR / 'yunet-mit.txt']))
    entries.append(('GLiNER PII Small model', 'Apache-2.0',
                    [LICENSE_DIR / 'gliner-apache-2.0.txt']))
    entries.append(('GLiNER runtime', 'Apache-2.0',
                    [LICENSE_DIR / 'gliner-apache-2.0.txt']))
    entries.append(('Ettin encoder', 'MIT', [LICENSE_DIR / 'ettin-mit.txt']))

    for display, license_name, paths in entries:
        for path in paths:
            if not path or not path.is_file():
                continue
            text = path.read_text(encoding='utf-8', errors='replace').strip()
            text = '\n'.join(
                line for line in text.splitlines()
                if line.strip() != '#include ./SHARED/Apache-2.0.txt'
            )
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
            if digest in seen:
                continue
            seen[digest] = display
            sections.append(f'{"=" * 78}\n{display} - {license_name}\n{"=" * 78}\n{text}')
    lines.append('\n\n'.join(sections) + '\n')
    output = ROOT / 'THIRD_PARTY_NOTICES.txt'
    output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Wrote {output} ({output.stat().st_size} bytes, {len(seen)} license texts)')


if __name__ == '__main__':
    main()
