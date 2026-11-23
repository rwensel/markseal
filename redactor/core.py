"""Local redaction logic shared by the PySide6 interface and the tests.

Nothing in this module touches the network or the desktop UI.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from performance_log import stage, timed


# Very coarse blocks remove fine detail, but mosaic redaction can remain reversible.
def pixelate(image, boxes, block_size=32):
    out = image.copy()
    for x1, y1, x2, y2 in boxes:
        crop = out.crop((x1, y1, x2, y2))
        small = crop.resize((max(1, (x2-x1)//block_size), max(1, (y2-y1)//block_size)), Image.Resampling.BOX)
        out.paste(small.resize(crop.size, Image.Resampling.NEAREST), (x1, y1))
    return out


PATTERNS = {
    'Emails': r"[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    'URLs': (
        r"(?:https?://|www\.|jdbc:[a-z][a-z0-9_-]*:)\S+"
        r"|(?<![\w@.-])(?:[a-z0-9-]+\.)+(?:com|org|net|io|local|internal)\b"
        r"|\blocalhost(?::\d+)?(?:/\S*)?"
    ),
    'IP addresses': r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    'Ticket IDs': r"\b[A-Z][A-Z0-9]{1,9}-\d+\b",
    'Paths': r"(?:[a-z]:\\|/home/|/users/|\\\\)\S+",
    'Hashes': r"\b[0-9a-f]{7,64}\b",
    'Secrets': (
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:gh[pousr]_|github_pat_|glpat-|sk_(?:live|test)_)[\w-]{12,}"
        r"|\bBearer\s+[\w./+=-]{16,}|-----\s*BEGIN [A-Z0-9 ]*PRIVATE KEY\s*-----"
    ),
    'Infrastructure': (
        r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+\.(?:ya?ml|tf(?:vars)?|kubeconfig|crt|pem|key|p12|pfx)\b"
        r"|(?<![\w.-])/(?:etc|run/secrets|var/run/secrets|vault|secrets|opt)/[\w./-]+"
        r"|\b[a-z][a-z0-9]{1,11}[-_.](?:prod(?:uction)?|stage|staging|dev|test|uat|qa|sandbox)"
        r"[-_.][a-z0-9][a-z0-9_.-]*"
        r"|\b(?-i:[A-Z]{2,6})[_-][a-z][a-z0-9]*(?:[_-][a-z0-9]+){2,}\b"
        r"|\b(?:dc\d{1,4}[a-z]{2,6}(?:_[a-z0-9]+)*"
        r"|[a-z]{1,6}\d{1,4}[-_][a-z]{2,8}(?:prod|stage|staging|dev|qa|uat|test))\b"
        r"|\binternal-[a-z0-9-]{8,}(?:\.[a-z0-9-]+)*\b"
        r"|\bdata\.(?-i:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b"
        r"|\b[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*){3,}\.(?:cron|enabled|endpoint|url|host|schema|quorum)\b"
        r"|\bJAVA_TOOL_OPTIONS\b|(?<!\S)-XX:[^\s]+"
        r"|\b(?:VAULT|KUBE(?:RNETES)?|KAFKA|TLS|AWS|AZURE|GCP|DB|DATABASE|REDIS)"
        r"(?:\s*[_-]\s*[a-z0-9]+)+\b"
        r"|\b[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.(?:kafka|vault|kubernetes|tls|database)"
        r"(?:\.[a-z0-9_-]+)+\b"
        r"|\b(?:secret[_-]?name|secret[_-]?key[_-]?ref|config[_-]?map[_-]?ref|"
        r"cluster[_-]?name|namespace|service[_-]?account[_-]?name)\s*:\s*[\w.-]+"
        r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:svc(?:\.cluster\.local)?|corp|intranet)\b"
        r"|\barn:[a-z0-9-]+:[^\s,]+"
    ),
    'Long identifiers': r"\b[A-Za-z0-9_/-]{24,}\b",
}
PRESETS = {
    'Focused': {'Emails', 'URLs', 'IP addresses', 'Secrets', 'Infrastructure'},
    'Balanced': set(PATTERNS) - {'Long identifiers'},
    'Broad': set(PATTERNS),
}

CREDENTIAL_FIELD = re.compile(
    r"(?:password|passwd|passphrase|bearer\s+token|authorization|(?:api|access)[ _-]?key|"
    r"(?:access|auth|refresh)[ _-]?token|client[ _-]?secret|private[ _-]?key(?:\s+marker)?)",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT = re.compile(
    r"(?<![\w.-])(?:[\w.-]*[_-])?(?:bearer\s+token|authorization|token|password|passwd|"
    r"passphrase|secret|api[_ -]?key|access[_ -]?key(?:[_-]?id)?|private[_ -]?key|"
    r"client[_ -]?secret|secret[_ -]?name)\s*[:=]\s*"
    r'(?P<value>"[^"]+"|\'[^\']+\'|Bearer\s+[^\s,}]+|[^\s,}]+)',
    re.IGNORECASE,
)


def credential_boxes(lines, size, min_confidence):
    """Match a credential label with the nearest distinct value on the same visual row."""
    groups = []
    for words in lines:
        parts = []
        for word in words:
            if not parts:
                parts.append([word])
                continue
            previous = parts[-1][-1]
            max_gap = max(12, min(word[4]-word[2], previous[4]-previous[2]))
            if word[1] - previous[3] > max_gap:
                parts.append([word])
            else:
                parts[-1].append(word)
        for part in parts:
            box = (min(w[1] for w in part), min(w[2] for w in part),
                   max(w[3] for w in part), max(w[4] for w in part))
            groups.append((' '.join(w[0] for w in part), box, max(w[5] for w in part)))

    result = []
    for text, (_, top, right, bottom), confidence in groups:
        label = text.removesuffix(':').strip()
        if confidence < min_confidence or CREDENTIAL_FIELD.fullmatch(label) is None:
            continue
        height = bottom - top
        candidates = []
        for value, bounds, score in groups:
            x1, y1, x2, y2 = bounds
            vertical_overlap = min(bottom, y2) - max(top, y1)
            if (score >= min_confidence and 0 <= x1-right <= 14*height
                    and vertical_overlap >= .55*min(height, y2-y1)):
                candidates.append((value, bounds))
        if not candidates:
            continue
        value, (x1, y1, x2, y2) = min(candidates, key=lambda item: item[1][0])
        if CREDENTIAL_FIELD.fullmatch(value.removesuffix(':').strip()):
            continue
        if label.lower().startswith('private'):
            marker = re.fullmatch(r"(-{0,5})(?:BEGIN|END) (?:[A-Z0-9]+ )*PRIVATE KEY(-{0,5})",
                                  value, re.IGNORECASE)
            if marker is None:
                continue
            # A photographed PEM marker may lose leading/trailing dashes in OCR.
            # Estimate only those expected characters and stay clear of the label.
            char_width = math.ceil((x2-x1) / len(value))
            x1 = max(right+5, x1-(5-len(marker[1]))*char_width)
            x2 += (5-len(marker[2]))*char_width
        result.append((max(0,x1-4), max(0,y1-4), min(size[0],x2+4), min(size[1],y2+4)))
    return result


def _learned_pattern_rules(learned_patterns):
    for item in learned_patterns:
        if isinstance(item, str):
            if item:
                yield 'Blocked pattern', item
            continue
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        label, pattern = item
        if isinstance(pattern, str) and pattern:
            yield str(label or 'Blocked pattern'), pattern


@timed('match_patterns')
def detect_regions(tsv, size, all_text=False, categories=None, min_confidence=0, custom_pattern='',
                   learned_patterns=(), rules=None):
    categories = set(PATTERNS) if categories is None else categories
    expressions = [(name, re.compile(PATTERNS[name], re.IGNORECASE))
                   for name in PATTERNS if name in categories]
    if custom_pattern:
        expressions.append(('Custom pattern', re.compile(custom_pattern, re.IGNORECASE)))
    expressions.extend((label, re.compile(pattern, re.IGNORECASE))
                       for label, pattern in _learned_pattern_rules(learned_patterns))
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        word = row.get('text', '').strip()
        if not word: continue
        try:
            confidence = float(row['conf'])
            left, top, width, height = (int(row[k]) for k in ('left','top','width','height'))
            key = tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
        except (ValueError, KeyError): continue
        if width <= 0 or height <= 0: continue
        lines.setdefault(key, []).append((word, left, top, left+width, top+height, confidence))
    boxes = []
    box_rules = {}
    assignments = []
    for words in lines.values():
        text = ' '.join(word[0] for word in words)
        spans = []
        if all_text:
            spans = [(0, len(text), 'All text')]
        else:
            for label, expression in expressions:
                spans.extend((m.start(), m.end(), label)
                             for m in expression.finditer(text) if m.end() > m.start())
        fields = [(match.span('value'), []) for match in SECRET_ASSIGNMENT.finditer(text)] if (
            not all_text and 'Secrets' in categories) else []
        offset = 0
        for word, x1, y1, x2, y2, confidence in words:
            start, end = offset, offset + len(word)
            for (left, right), field_words in fields:
                if start < right and end > left:
                    field_words.append((x1, y1, x2, y2, confidence))
            matched = []
            if confidence >= min_confidence:
                for left, right, label in spans:
                    if start < right and end > left and label not in matched:
                        matched.append(label)
            if matched:
                box = (max(0,x1-4), max(0,y1-4), min(size[0],x2+4), min(size[1],y2+4))
                if box not in box_rules:
                    box_rules[box] = []
                    boxes.append(box)
                for label in matched:
                    if label not in box_rules[box]:
                        box_rules[box].append(label)
            offset = end + 1
        for _, field_words in fields:
            if field_words and max(word[4] for word in field_words) >= min_confidence:
                x1, y1, x2, y2 = zip(*(word[:4] for word in field_words))
                assignments.append((max(0, min(x1)-4), max(0, min(y1)-4),
                                    min(size[0], max(x2)+4), min(size[1], max(y2)+4)))
    if not all_text and 'Secrets' in categories:
        credentials = credential_boxes(lines.values(), size, min_confidence)
        for source in (assignments, credentials):
            for left, top, right, bottom in source:
                covered = [box for box in boxes if
                           (left <= box[0] and top <= box[1] and box[2] <= right and box[3] <= bottom)]
                for box in covered:
                    boxes.remove(box)
                    box_rules.pop(box, None)
                box = (left, top, right, bottom)
                boxes.append(box)
                box_rules[box] = ['Secrets']
    if rules is not None:
        rules.clear()
        rules.update({box: tuple(labels) for box, labels in box_rules.items()})
    return boxes


@timed('render_redactions')
def apply_redactions(image, boxes, method='Pixelate'):
    if method == 'Pixelate': return pixelate(image, boxes)
    out = image.copy(); draw = ImageDraw.Draw(out)
    for x1, y1, x2, y2 in boxes: draw.rectangle((x1,y1,x2-1,y2-1), fill='black')
    return out


def find_tesseract():
    bundled = Path(__file__).resolve().parent.parent / 'tools' / 'tesseract' / 'tesseract.exe'
    if bundled.is_file(): return str(bundled)
    found = shutil.which('tesseract')
    if found: return found
    for base in (os.environ.get('PROGRAMFILES', ''), os.environ.get('LOCALAPPDATA', '')):
        path = Path(base) / 'Tesseract-OCR' / 'tesseract.exe'
        if path.is_file(): return str(path)
    return None


def preferences_path():
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / '.config'
    return base / 'OfflineScreenshotRedactor' / 'settings.json'


def write_preferences(path, preferences):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(preferences, stream, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


def batch_worker_count(requested, job_count, limit):
    return max(1, min(int(requested), max(1, int(job_count)), max(1, int(limit))))


@dataclass
class FolderImage:
    path: Path
    boxes: list = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    selected: set = field(default_factory=set)
    scanned: bool = False
    incomplete_ocr: tuple = ()
    reviewed: bool = False
    saved: bool = False
    error: str = ''
    stamp: tuple | None = None
    method: str = 'Pixelate'

    @property
    def status(self):
        if self.error:
            return self.error
        if self.saved:
            return 'Saved'
        if self.reviewed:
            return 'Reviewed'
        if self.incomplete_ocr:
            return 'Partial scan · review needed'
        if self.scanned:
            return 'Scanned · review needed'
        if self.boxes:
            return 'Boxes added · review needed'
        return 'Not checked'

    def add_shared_boxes(self, boxes, rules=None, source='Copied box'):
        indices = {box: index for index, box in enumerate(self.boxes)}
        rule_values = rules or {}
        changed = False
        for box in boxes:
            index = indices.get(box)
            if index is None:
                index = len(self.boxes)
                self.boxes.append(box)
                indices[box] = index
                self.rules.setdefault(box, tuple(rule_values.get(box, ()) or (source,)))
            elif box not in self.rules:
                self.rules[box] = tuple(rule_values.get(box, ()) or (source,))
            if index not in self.selected:
                self.selected.add(index)
                changed = True
        kept, kept_selected = strip_contained_selected(self.boxes, self.selected)
        if kept != self.boxes:
            self.boxes[:] = kept
            for box in list(self.rules):
                if box not in self.boxes:
                    del self.rules[box]
            self.selected.clear()
            self.selected.update(kept_selected)
            changed = True
        if changed:
            self.reviewed = self.saved = False
        return changed

    def add_suggestions(self, found, incomplete=(), rules=None):
        if rules is None:
            rules = getattr(found, 'rules', {})
        added = new_ocr_boxes(found, self.boxes)
        self.add_shared_boxes(added, rules, source='OCR suggestion')
        self.scanned = True
        self.incomplete_ocr = tuple(incomplete)
        self.reviewed = self.saved = False
        self.error = ''
        selected_boxes = {box for index, box in enumerate(self.boxes) if index in self.selected}
        return sum(1 for box in added if box in selected_boxes)


def file_stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


@timed('load_image')
def read_folder_image(path, expected=None):
    stamp = file_stamp(path)
    if expected is not None and stamp != expected:
        raise ValueError('Source changed. Reopen the folder and review the new image.')
    with Image.open(path) as source:
        image = source.convert('RGB')
    if file_stamp(path) != stamp:
        raise ValueError('Source changed while reading.')
    return image, stamp


def output_path(directory, template, source, index):
    name = template.format(stem=source.stem, ext=source.suffix[1:].lower(), index=index)
    if not name.lower().endswith('.png'):
        name += '.png'
    if (not name[:-4].strip(' .') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.startswith(' ') or re.fullmatch(r'(?i)(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', name.split('.')[0].rstrip(' '))):
        raise ValueError('Enter a valid filename template without folders.')
    return directory / name


def stage_export(target, write):
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, suffix='.redactor-tmp', delete=False) as stream:
            temporary = Path(stream.name)
            write(stream)
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def publish_export(temporary, target, overwrite=False):
    if overwrite:
        temporary.replace(target)
    elif os.name == 'nt':
        temporary.rename(target)  # On Windows rename fails if target exists.
    else:
        os.link(temporary, target)


PNG_COMPRESSION = 3


def save_export(image, target, log, *, overwrite=False):
    temporary_files = []
    published = []
    try:
        with stage('encode_png', width=image.width, height=image.height, compression_level=PNG_COMPRESSION):
            png = stage_export(target, lambda stream: image.save(
                stream, format='PNG', compress_level=PNG_COMPRESSION))
            temporary_files.append(png)
        log_target = target.with_suffix('.redactions.json')
        if log is not None:
            with stage('encode_coordinate_log'):
                sidecar = stage_export(log_target, lambda stream: stream.write(
                    json.dumps(log, indent=2).encode('utf-8')))
                temporary_files.append(sidecar)
        with stage('publish_export'):
            if log is not None:
                publish_export(sidecar, log_target, overwrite)
                published.append(log_target)
            publish_export(png, target, overwrite)
    except Exception:
        if not overwrite:
            for path in published:
                path.unlink(missing_ok=True)
        raise
    finally:
        for path in temporary_files:
            path.unlink(missing_ok=True)


def write_folder_copy(entry, target, include_log):
    image, _ = read_folder_image(entry.path, entry.stamp)
    boxes = [box for index, box in enumerate(entry.boxes) if index in entry.selected]
    copy = apply_redactions(image, boxes, entry.method)
    copy.info.clear()
    log_path = target.with_suffix('.redactions.json')
    log = {
        'source_filename': entry.path.name,
        'output_filename': target.name,
        'image_dimensions': list(image.size),
        'redaction_rectangles_xyxy': boxes,
        'method': entry.method,
        'created_local_time': datetime.now().isoformat(timespec='seconds'),
    }
    save_export(copy, target, log if include_log else None)


class ScanCancelled(Exception):
    """The user stopped a folder scan before this image finished."""


def cancellable_ocr(command, data, creationflags, cancel, *, timeout=120, env=None):
    if cancel.is_set():
        raise ScanCancelled
    deadline = monotonic() + timeout
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, creationflags=creationflags, env=env) as process:
        pending_input = data
        try:
            while True:
                if cancel.is_set():
                    raise ScanCancelled
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(input=pending_input, timeout=min(0.15, remaining))
                    break
                except subprocess.TimeoutExpired:
                    # communicate retains its input and output across a timeout.
                    pending_input = None
        except (ScanCancelled, subprocess.TimeoutExpired):
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        return stdout


def recognize_regions(image, executable, settings, enhanced=False, cancel=None, *,
                      color_assisted=False, incomplete=None, area=None, area_layout=None,
                      progress=None):
    def report(text):
        if progress is not None:
            progress(text)

    if area is not None:
        report('Scanning area')
        left, top, right, bottom = area
        crop = image.crop(area)
        factor = min(4, 2400 / max(crop.size))
        enlarged = crop.resize((max(1, round(crop.width*factor)), max(1, round(crop.height*factor))), Image.Resampling.LANCZOS)
        boxes = recognize_regions(enlarged, executable, settings, enhanced, cancel,
                                  color_assisted=color_assisted, incomplete=incomplete,
                                  area_layout='7' if crop.width >= 6*crop.height else '6',
                                  progress=progress)
        all_text, _, confidence, pattern = settings[:4]
        learned = settings[4] if len(settings) > 4 else ()
        expressions = []
        if pattern:
            expressions.append(('Custom pattern', re.compile(pattern, re.IGNORECASE)))
        expressions.extend((label, re.compile(value, re.IGNORECASE))
                           for label, value in _learned_pattern_rules(learned))
        if (not boxes and executable is None and not all_text and expressions
                and crop.height <= 180 and crop.width <= min(600, 6*crop.height)):
            if cancel is not None and cancel.is_set():
                raise ScanCancelled
            report('Reading selected label')
            from rapidocr_backend import recognize_single_label
            text, score = recognize_single_label(crop)
            if cancel is not None and cancel.is_set():
                raise ScanCancelled
            if text and score >= confidence:
                matched = tuple(label for label, expression in expressions
                                if expression.fullmatch(text))
                if matched:
                    return BoxList([area], {area: matched})
        sx, sy = crop.width/enlarged.width, crop.height/enlarged.height
        mapped = [(left+math.floor(x1*sx), top+math.floor(y1*sy),
                   min(right, left+math.ceil(x2*sx)), min(bottom, top+math.ceil(y2*sy)))
                  for x1, y1, x2, y2 in boxes]
        mapped_rules = {destination: boxes.rules.get(source, ())
                        for source, destination in zip(boxes, mapped)}
        return BoxList(mapped, mapped_rules)
    # Tesseract processes run serially. Limiting OpenMP threads avoids
    # oversubscription on machines where parallel OCR runs slower.
    environment = {**os.environ, 'OMP_THREAD_LIMIT': '1'}

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ScanCancelled

    def run(source, extra_options=(), timeout=120):
        check_cancel()
        detected = {}
        if executable is None:
            from rapidocr_backend import recognize_words
            with stage('rapidocr_inference', width=source.width, height=source.height):
                tsv = recognize_words(source)
            check_cancel()
            return detect_regions(tsv, source.size, *settings, rules=detected), detected
        data = io.BytesIO()
        with stage('ocr_input_encoding', width=source.width, height=source.height):
            source.save(data, format='PNG')
        command = [executable, 'stdin', 'stdout', *extra_options, 'tsv']
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        if cancel is None:
            with stage('tesseract_inference'):
                result = subprocess.run(command, input=data.getvalue(), capture_output=True,
                                        timeout=timeout, check=True, creationflags=flags, env=environment)
            stdout = result.stdout
        else:
            with stage('tesseract_inference'):
                stdout = cancellable_ocr(command, data.getvalue(), flags, cancel, timeout=timeout, env=environment)
        return detect_regions(stdout.decode('utf-8', errors='replace'), source.size,
                              *settings, rules=detected), detected

    try:
        with stage('standard_ocr_pass') as timing:
            report('Recognizing text')
            found, pass_rules = run(image, ('--psm', area_layout) if area_layout else ())
            boxes = new_ocr_boxes(found)
            rules = {box: pass_rules.get(box, ()) for box in boxes}
            if timing is not None:
                timing['new_suggestions'] = len(boxes)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('Standard OCR timed out. Try a smaller photo or mark redactions manually.') from error

    if not (enhanced or color_assisted):
        return BoxList(boxes, rules)

    check_cancel()
    working = image.copy()
    working.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    enhancement_deadline = monotonic() + 35

    def note_incomplete(reason):
        if incomplete is not None:
            incomplete.append(reason)

    def add_pass(source, name, bounds=None):
        check_cancel()
        remaining = enhancement_deadline - monotonic()
        if remaining <= 0:
            note_incomplete('remaining enhancement passes skipped')
            return False
        try:
            with stage('additional_ocr_pass', pass_name=name) as timing:
                found, found_rules = run(source, ('--psm', area_layout or '11'), timeout=min(15, remaining))
        except subprocess.TimeoutExpired:
            note_incomplete(f'{name} timed out')
            return True
        except subprocess.CalledProcessError:
            note_incomplete(f'{name} failed')
            return True
        previous_count = len(boxes)
        left, top, right, bottom = bounds or (0, 0, image.width, image.height)
        scale_x = (right-left) / source.width
        scale_y = (bottom-top) / source.height
        for x1, y1, x2, y2 in found:
            candidate = (left+math.floor(x1*scale_x), top+math.floor(y1*scale_y),
                         min(right, left+math.ceil(x2*scale_x)), min(bottom, top+math.ceil(y2*scale_y)))
            if not any(same_region(candidate, existing) for existing in boxes):
                boxes.append(candidate)
                labels = found_rules.get((x1, y1, x2, y2), ())
                if labels:
                    rules[candidate] = labels
        if timing is not None:
            timing['new_suggestions'] = len(boxes) - previous_count
        return True

    if color_assisted:
        check_cancel()
        from ocr_preprocess import strike_reduced_variant
        report('Recovering struck-through text')
        with stage('strikethrough_preprocess'):
            strike_reduced = strike_reduced_variant(working)
        if strike_reduced is not None and not add_pass(strike_reduced, 'strikethrough recovery'):
            return BoxList(boxes, rules)

    if enhanced:
        report('Enhancing image')
        with stage('grayscale_preprocess'):
            contrast = ImageOps.autocontrast(ImageOps.grayscale(working).filter(ImageFilter.MedianFilter(3)), cutoff=1)
        if not add_pass(contrast, 'enhanced OCR'):
            return BoxList(boxes, rules)
        if executable is None and area_layout is None:
            from ocr_preprocess import small_text_tiles
            for index, (bounds, tile) in enumerate(small_text_tiles(image), 1):
                report(f'Reading small-text section {index}')
                if not add_pass(tile, f'small-text section {index}', bounds):
                    return BoxList(boxes, rules)
    if color_assisted:
        check_cancel()
        from ocr_preprocess import color_ocr_variants
        with stage('color_preprocess'):
            variants = list(color_ocr_variants(working))
        for index, variant in enumerate(variants, 1):
            report(f'Color pass {index} of {len(variants)}')
            if not add_pass(variant, f'color pass {index}'):
                break
    return BoxList(boxes, rules)


def same_region(first, second):
    if first == second:
        return True
    widths = (first[2]-first[0], second[2]-second[0])
    heights = (first[3]-first[1], second[3]-second[1])
    areas = (widths[0]*heights[0], widths[1]*heights[1])
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1]))
    if overlap >= 0.75 * max(areas):
        return True

    # Different passes can put larger padding around the very same word.
    # Require close centers and comparable dimensions so a word inside a much
    # wider line, or a neighboring label whose edges touch, is still distinct.
    center_dx = abs(first[0]+first[2]-second[0]-second[2]) / 2
    center_dy = abs(first[1]+first[3]-second[1]-second[3]) / 2
    return (overlap >= 0.9 * min(areas)
            and min(widths) >= 0.45 * max(widths)
            and min(heights) >= 0.45 * max(heights)
            and center_dx <= 0.2 * max(widths)
            and center_dy <= 0.2 * max(heights))


def new_ocr_boxes(candidates, existing=()):
    kept = list(existing)
    added = []
    for box in candidates:
        if not any(same_region(box, previous) for previous in kept):
            added.append(box)
            kept.append(box)
    return added


class BoxList(list):
    def __init__(self, iterable=(), rules=None):
        super().__init__(iterable)
        self.rules = {box: tuple(labels) for box, labels in (rules or {}).items() if labels}


def text_from_tsv(tsv):
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        word = row.get('text', '').strip()
        if not word:
            continue
        key = tuple(row.get(name, '') for name in ('page_num', 'block_num', 'par_num', 'line_num'))
        lines.setdefault(key, []).append(word)
    return '\n'.join(' '.join(words) for words in lines.values())


def read_area_text(image, executable, area):
    left, top, right, bottom = area
    crop = image.crop((left, top, right, bottom))
    if max(crop.size) > 0:
        factor = min(3, 1600 / max(crop.size))
        if factor > 1:
            crop = crop.resize((max(1, round(crop.width * factor)),
                                max(1, round(crop.height * factor))), Image.Resampling.LANCZOS)
    border = max(6, crop.height // 20)
    crop = ImageOps.expand(crop, border=border, fill=crop.getpixel((0, 0)))
    if executable is None:
        from rapidocr_backend import recognize_words
        tsv = recognize_words(crop)
    else:
        data = io.BytesIO()
        crop.save(data, format='PNG')
        psm = '7' if crop.width >= 6 * crop.height else '6'
        result = subprocess.run(
            [executable, 'stdin', 'stdout', '--psm', psm, 'tsv'],
            input=data.getvalue(), capture_output=True, timeout=30, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            env={**os.environ, 'OMP_THREAD_LIMIT': '1'},
        )
        tsv = result.stdout.decode('utf-8', errors='replace')
    return text_from_tsv(tsv)


def pattern_from_text(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ''
    patterns = []
    for line in lines:
        words = line.split()
        body = r'\s+'.join(re.escape(word) for word in words)
        if re.match(r'\w', words[0]):
            body = r'\b' + body
        if re.search(r'\w$', words[-1]):
            body += r'\b'
        patterns.append(body)
    patterns.sort(key=len, reverse=True)
    return patterns[0] if len(patterns) == 1 else '(?:' + '|'.join(patterns) + ')'


_IPV4_OCTET = r'(?:25[0-5]|2[0-4]\d|1?\d?\d)'
_IPV4_ADDRESS = rf'(?:{_IPV4_OCTET}\.){{3}}{_IPV4_OCTET}'
_IPV6_ADDRESS = (
    r'(?:'
    r'(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,7}:|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,5}(?::[0-9A-Fa-f]{1,4}){1,2}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,4}(?::[0-9A-Fa-f]{1,4}){1,3}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,3}(?::[0-9A-Fa-f]{1,4}){1,4}|'
    r'(?:[0-9A-Fa-f]{1,4}:){1,2}(?::[0-9A-Fa-f]{1,4}){1,5}|'
    r'[0-9A-Fa-f]{1,4}:(?::[0-9A-Fa-f]{1,4}){1,6}|'
    r':(?::[0-9A-Fa-f]{1,4}){1,7}|'
    r'::|'
    rf'::(?:ffff(?::0{{1,4}})?:)?{_IPV4_ADDRESS}'
    r')'
)
PATTERN_TYPE_LABELS = {
    'ipv4': 'Any IPv4 address',
    'ipv4_cidr': 'Any IPv4 CIDR range',
    'ipv6': 'Any IPv6 address',
    'ipv6_cidr': 'Any IPv6 CIDR range',
    'integer': 'Any integer',
    'uuid': 'Any UUID',
    'email': 'Any email address',
    'url': 'Any URL',
    'hex': 'Any long hex token',
    'mac': 'Any MAC address',
    'date': 'Any ISO date',
}
PATTERN_TYPE_EXPRESSIONS = {
    'ipv4': rf'(?<![\w.]){_IPV4_ADDRESS}(?![\w.])',
    'ipv4_cidr': rf'(?<![\w.]){_IPV4_ADDRESS}/(?:3[0-2]|[12]?\d)(?![\w.])',
    'ipv6': rf'(?<![0-9A-Za-z:]){_IPV6_ADDRESS}(?![0-9A-Za-z:])',
    'ipv6_cidr': rf'(?<![0-9A-Za-z:]){_IPV6_ADDRESS}/(?:12[0-8]|1[01]\d|[1-9]?\d)(?![0-9A-Za-z:])',
    'integer': r'(?<![\w.])[-+]?\d+(?![\w.])',
    'uuid': r'\b[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\b',
    'email': r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b',
    'url': r'(?<![\w])https?://[^\s"\'<>]+',
    'hex': r'\b[0-9A-Fa-f]{8,64}\b',
    'mac': r'\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b',
    'date': r'\b\d{4}-\d{2}-\d{2}\b',
}


def value_pattern_types(text):
    value = text.strip()
    if not value:
        return []
    kinds = []
    try:
        if '/' in value:
            network = ipaddress.ip_network(value, strict=False)
            kinds.append('ipv4_cidr' if network.version == 4 else 'ipv6_cidr')
        else:
            address = ipaddress.ip_address(value)
            kinds.append('ipv4' if address.version == 4 else 'ipv6')
    except ValueError:
        pass
    for kind, expression in PATTERN_TYPE_EXPRESSIONS.items():
        if kind in ('ipv4', 'ipv4_cidr', 'ipv6', 'ipv6_cidr'):
            continue
        if re.fullmatch(expression, value):
            kinds.append(kind)
    return kinds


def value_pattern_expression(text, kind):
    if kind == 'fixed':
        return pattern_from_text(text)
    return PATTERN_TYPE_EXPRESSIONS.get(kind, pattern_from_text(text))


def strip_contained_selected(boxes, selected):
    selected = set(selected)

    def contains(outer, inner):
        outer_area = (outer[2] - outer[0]) * (outer[3] - outer[1])
        inner_area = (inner[2] - inner[0]) * (inner[3] - inner[1])
        return (outer_area > inner_area
                and outer[0] <= inner[0] + 2
                and outer[1] <= inner[1] + 2
                and outer[2] >= inner[2] - 2
                and outer[3] >= inner[3] - 2)

    kept = []
    kept_selected = set()
    for index, box in enumerate(boxes):
        if index in selected and any(
                other != index and other in selected and contains(boxes[other], box)
                for other in range(len(boxes))):
            continue
        if index in selected:
            kept_selected.add(len(kept))
        kept.append(box)
    return kept, kept_selected


def scan_folder_image(path, expected, executable, settings, enhanced=False, cancel=None, *, color_assisted=False, area=None):
    image, stamp = read_folder_image(path, expected)
    incomplete = []
    boxes = recognize_regions(image, executable, settings, enhanced, cancel,
                              color_assisted=color_assisted, incomplete=incomplete, area=area)
    return stamp, boxes, incomplete
