"""Local GLiNER token-level NER for personal names and addresses."""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .suggestions import SuggestionSet, padded_box

MODEL_DIRECTORY = Path(__file__).resolve().parent / 'models' / 'ner'
MANIFEST_FILENAME = 'manifest.json'
MODEL_FILENAME = 'model.onnx'
TOKENIZER_FILENAME = 'tokenizer.json'
PROMPT_ENT = '<<ENT>>'
PROMPT_SEP = '<<SEP>>'
CAPTURE = frozenset({'Personal names', 'Postal addresses'})
CODE_SHAPE = re.compile(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]+$')
MODEL_SPLIT = re.compile(r"[A-Za-z][A-Za-z'.-]*/[A-Za-z][A-Za-z'.-]*")
STREET_SUFFIXES = frozenset({
    'street', 'st', 'avenue', 'ave', 'road', 'rd', 'lane', 'ln', 'boulevard', 'blvd',
    'drive', 'dr', 'court', 'ct', 'way', 'place', 'pl', 'terrace', 'ter',
    'parkway', 'pkwy', 'highway', 'hwy', 'circle', 'cir', 'square', 'sq',
})

_SESSIONS = {}
_LOCK = threading.Lock()


@dataclass(frozen=True)
class Prompt:
    text: str
    category: str
    threshold: float


@dataclass(frozen=True)
class Manifest:
    model_id: str
    revision: str
    prompts: tuple
    max_words: int


def load_manifest(model_dir=None):
    root = Path(model_dir) if model_dir else MODEL_DIRECTORY
    try:
        document = json.loads((root / MANIFEST_FILENAME).read_text(encoding='utf-8'))
        prompts = tuple(
            Prompt(str(item['prompt']), str(item['category']), float(item['threshold']))
            for item in document['prompts']
        )
        max_words = int(document.get('max_words', 400))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not prompts or max_words < 1:
        return None
    return Manifest(str(document.get('id', '')), str(document.get('revision', '')),
                    prompts, max_words)


def available(model_dir=None):
    root = Path(model_dir) if model_dir else MODEL_DIRECTORY
    return (load_manifest(root) is not None
            and (root / MODEL_FILENAME).is_file()
            and (root / TOKENIZER_FILENAME).is_file())


def prompt_words(prompts):
    words = []
    for prompt in prompts:
        words.extend((PROMPT_ENT, prompt.text))
    words.append(PROMPT_SEP)
    return words


def build_inputs(words, prompt_tokens, tokenizer):
    texts = [str(word[0]) if isinstance(word, (tuple, list)) else str(word)
             for word in words]
    encoding = tokenizer.encode(list(prompt_tokens) + texts, is_pretokenized=True)
    ids = list(encoding.ids)
    word_ids = list(encoding.word_ids)
    if not ids or len(ids) != len(word_ids):
        raise ValueError('tokenizer output is incomplete')
    prompt_count = len(prompt_tokens)
    mask = []
    for word_id in word_ids:
        if word_id is None or word_id < prompt_count:
            mask.append(0)
        else:
            mask.append(word_id - prompt_count + 1)
    inputs = {
        'input_ids': np.array([ids], dtype=np.int64),
        'attention_mask': np.ones((1, len(ids)), dtype=np.int64),
        'words_mask': np.array([mask], dtype=np.int64),
        'text_lengths': np.array([[len(words)]], dtype=np.int64),
    }
    return inputs, len(words)


def decode_spans(logits, words, prompts):
    values = np.asarray(logits)
    if values.ndim != 4 or not len(words) or not prompts:
        return []
    batch = values[0]
    length = min(batch.shape[0], len(words))
    classes = min(batch.shape[1], len(prompts))
    if not length or not classes:
        return []
    probabilities = 1.0 / (1.0 + np.exp(-batch[:length, :classes, :]))
    candidates = []
    for class_index in range(classes):
        prompt = prompts[class_index]
        starts = [index for index in range(length)
                  if probabilities[index, class_index, 0] > prompt.threshold]
        ends = [index for index in range(length)
                if probabilities[index, class_index, 1] > prompt.threshold]
        for start in starts:
            for end in ends:
                if end < start:
                    continue
                inside = probabilities[start:end + 1, class_index, 2]
                if inside.min() <= prompt.threshold:
                    continue
                score = min(probabilities[start, class_index, 0],
                            probabilities[end, class_index, 1], inside.min())
                candidates.append((start, end, prompt.category, float(score)))
    candidates.sort(key=lambda span: -span[3])
    kept = []
    for span in candidates:
        if all(span[1] < other[0] or span[0] > other[1] for other in kept):
            kept.append(span)
    return sorted(kept, key=lambda span: span[0])


def _resources(model_dir):
    root = Path(model_dir) if model_dir else MODEL_DIRECTORY
    key = str(root.resolve())
    with _LOCK:
        if key not in _SESSIONS:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(4, os.cpu_count() or 1)
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            session = ort.InferenceSession(
                str(root / MODEL_FILENAME), sess_options=options,
                providers=['CPUExecutionProvider'])
            tokenizer = Tokenizer.from_file(str(root / TOKENIZER_FILENAME))
            _SESSIONS[key] = (session, tokenizer)
        return _SESSIONS[key]


def _valid_span(words, category):
    text = ' '.join(str(word[0]) for word in words).strip()
    if category == 'Personal names':
        return (len(text) >= 3 and re.search(r'[A-Za-z]', text) is not None
                and CODE_SHAPE.fullmatch(text) is None)
    if category == 'Postal addresses':
        if ',' in text:
            return True
        tokens = [token.strip('.,;:#()[]') for token in text.split()]
        if any(token.lower() in STREET_SUFFIXES for token in tokens):
            return True
        return len(tokens) >= 3 and any(token.isdigit() for token in tokens)
    return True


def _model_words(words):
    model = []
    sources = []
    for word in words:
        text = str(word[0])
        if MODEL_SPLIT.fullmatch(text) is None:
            model.append(word)
            sources.append(word)
            continue
        for part in text.split('/'):
            model.append((part,) + tuple(word[1:]))
            sources.append(word)
    return model, sources


def detect_entities(lines, size, min_confidence, categories, *, model_dir=None,
                    session=None, tokenizer=None):
    selected = set(categories) & CAPTURE
    if not selected:
        return [], {}
    manifest = load_manifest(model_dir)
    if manifest is None:
        return [], {}
    prompts = tuple(prompt for prompt in manifest.prompts if prompt.category in selected)
    if not prompts:
        return [], {}
    if session is None or tokenizer is None:
        if not available(model_dir):
            return [], {}
        try:
            session, tokenizer = _resources(model_dir)
        except Exception:
            return [], {}
    prompt_tokens = prompt_words(prompts)
    found = SuggestionSet()
    for line in lines:
        words = [word for word in line if str(word[0]).strip()]
        if not words:
            continue
        model_words, sources = _model_words(words)
        size_words = max(1, manifest.max_words)
        for offset in range(0, len(model_words), size_words):
            chunk = model_words[offset:offset + size_words]
            source_chunk = sources[offset:offset + size_words]
            try:
                inputs, _ = build_inputs(chunk, prompt_tokens, tokenizer)
                output = session.run(None, inputs)
                logits = output[0] if isinstance(output, (list, tuple)) else output
            except Exception:
                continue
            for start, end, category, _ in decode_spans(logits, chunk, prompts):
                value = []
                for word in source_chunk[start:end + 1]:
                    if not value or value[-1] is not word:
                        value.append(word)
                if (any(word[5] < min_confidence for word in value)
                        or not _valid_span(value, category)):
                    continue
                found.add(padded_box(value, size), category)
    return found.parts()
