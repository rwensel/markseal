"""Fetch the pinned local PII NER model for builds."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'markseal' / 'models' / 'ner'
REVISION = 'd21aad5b4a7ec82b3d0970fd1ac74a12c087d85e'
BASE = f'https://huggingface.co/knowledgator/gliner-pii-small-v1.0/resolve/{REVISION}/'
ARTIFACTS = {
    'model.onnx': ('onnx/model_quint8.onnx',
                   '891589426ee96f2748b16439f44fad8c3f97e198e002a6637e58dee989500216',
                   82680500),
    'tokenizer.json': ('tokenizer.json',
                       '84b3a9b18f04a0ccd03b72d9f871b7e0bec40fd7021ef50bc30a7c3693c11205',
                       3583593),
    'gliner_config.json': ('gliner_config.json',
                           'c10803bade021f40072b194bc78bc2edd2bf3e60637a6f34cc9b00705bf3c168',
                           4316),
}
MANIFEST = {
    'id': 'knowledgator/gliner-pii-small-v1.0',
    'revision': REVISION,
    'license': 'Apache-2.0',
    'encoder': 'jhu-clsp/ettin-encoder-68m',
    'encoder_license': 'MIT',
    'files': {
        name: {'sha256': sha256, 'size': size}
        for name, (_, sha256, size) in ARTIFACTS.items()
    },
    'prompts': [
        {'prompt': 'person', 'category': 'Personal names', 'threshold': 0.6},
        {'prompt': 'address', 'category': 'Postal addresses', 'threshold': 0.6},
    ],
    'max_words': 400,
}


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def verified(path, expected, size):
    path = Path(path)
    return path.is_file() and path.stat().st_size == size and digest(path) == expected


def fetch(name, source, expected, size):
    destination = TARGET / name
    if verified(destination, expected, size):
        print(f'{name}: present and verified')
        return
    request = urllib.request.Request(BASE + source, headers={'User-Agent': 'MarkSeal build'})
    with urllib.request.urlopen(request, timeout=180) as response:
        data = response.read()
    if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(
            f'{name}: download verification failed; expected {size} bytes and {expected}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    print(f'{name}: downloaded and verified')


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    for name, (source, expected, size) in ARTIFACTS.items():
        fetch(name, source, expected, size)
    (TARGET / 'manifest.json').write_text(
        json.dumps(MANIFEST, indent=2) + '\n', encoding='utf-8')
    print(f'PII NER model ready in {TARGET}')


if __name__ == '__main__':
    main()
