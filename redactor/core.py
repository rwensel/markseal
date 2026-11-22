"""Local redaction logic shared by the PySide6 interface and the tests.

Nothing in this module touches the network or the desktop UI.
"""
from __future__ import annotations

import csv
import io
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


@timed('match_patterns')
def detect_regions(tsv, size, all_text=False, categories=None, min_confidence=0, custom_pattern=''):
    categories = set(PATTERNS) if categories is None else categories
    expressions = [re.compile(PATTERNS[name], re.IGNORECASE) for name in PATTERNS if name in categories]
    if custom_pattern: expressions.append(re.compile(custom_pattern, re.IGNORECASE))
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
    assignments = []
    for words in lines.values():
        text = ' '.join(word[0] for word in words)
        spans = []
        if all_text:
            spans = [(0, len(text))]
        else:
            for expression in expressions:
                spans.extend((m.start(), m.end()) for m in expression.finditer(text) if m.end() > m.start())
        fields = [(match.span('value'), []) for match in SECRET_ASSIGNMENT.finditer(text)] if (
            not all_text and 'Secrets' in categories) else []
        offset = 0
        for word, x1, y1, x2, y2, confidence in words:
            start, end = offset, offset + len(word)
            for (left, right), field_words in fields:
                if start < right and end > left:
                    field_words.append((x1, y1, x2, y2, confidence))
            if confidence >= min_confidence and any(start < right and end > left for left, right in spans):
                box = (max(0,x1-4), max(0,y1-4), min(size[0],x2+4), min(size[1],y2+4))
                if box not in boxes: boxes.append(box)
            offset = end + 1
        for _, field_words in fields:
            if field_words and max(word[4] for word in field_words) >= min_confidence:
                x1, y1, x2, y2 = zip(*(word[:4] for word in field_words))
                assignments.append((max(0, min(x1)-4), max(0, min(y1)-4),
                                    min(size[0], max(x2)+4), min(size[1], max(y2)+4)))
    if not all_text and 'Secrets' in categories:
        credentials = credential_boxes(lines.values(), size, min_confidence)
        for left, top, right, bottom in assignments + credentials:
            boxes = [box for box in boxes if not
                     (left <= box[0] and top <= box[1] and box[2] <= right and box[3] <= bottom)]
            boxes.append((left, top, right, bottom))
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

    def add_shared_boxes(self, boxes):
        indices = {box: index for index, box in enumerate(self.boxes)}
        changed = False
        for box in boxes:
            index = indices.get(box)
            if index is None:
                index = len(self.boxes)
                self.boxes.append(box)
                indices[box] = index
            if index not in self.selected:
                self.selected.add(index)
                changed = True
        if changed:
            self.reviewed = self.saved = False
        return changed

    def add_suggestions(self, found, incomplete=()):
        added = new_ocr_boxes(found, self.boxes)
        self.add_shared_boxes(added)
        self.scanned = True
        self.incomplete_ocr = tuple(incomplete)
        self.reviewed = self.saved = False
        self.error = ''
        return len(added)


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
                      color_assisted=False, incomplete=None, area=None, area_layout=None):
    if area is not None:
        left, top, right, bottom = area
        crop = image.crop(area)
        factor = min(4, 2400 / max(crop.size))
        enlarged = crop.resize((max(1, round(crop.width*factor)), max(1, round(crop.height*factor))), Image.Resampling.LANCZOS)
        boxes = recognize_regions(enlarged, executable, settings, enhanced, cancel,
                                  color_assisted=color_assisted, incomplete=incomplete,
                                  area_layout='7' if crop.width >= 6*crop.height else '6')
        all_text, _, confidence, pattern = settings
        if (not boxes and executable is None and not all_text and pattern
                and crop.height <= 180 and crop.width <= min(600, 6*crop.height)):
            if cancel is not None and cancel.is_set():
                raise ScanCancelled
            from rapidocr_backend import recognize_single_label
            text, score = recognize_single_label(crop)
            if cancel is not None and cancel.is_set():
                raise ScanCancelled
            if text and score >= confidence and re.fullmatch(pattern, text, re.IGNORECASE):
                return [area]
        sx, sy = crop.width/enlarged.width, crop.height/enlarged.height
        return [(left+math.floor(x1*sx), top+math.floor(y1*sy),
                 min(right, left+math.ceil(x2*sx)), min(bottom, top+math.ceil(y2*sy)))
                for x1, y1, x2, y2 in boxes]
    # Tesseract processes run serially. Limiting OpenMP threads avoids
    # oversubscription on machines where parallel OCR runs slower.
    environment = {**os.environ, 'OMP_THREAD_LIMIT': '1'}

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ScanCancelled

    def run(source, extra_options=(), timeout=120):
        check_cancel()
        if executable is None:
            from rapidocr_backend import recognize_words
            with stage('rapidocr_inference', width=source.width, height=source.height):
                tsv = recognize_words(source)
            check_cancel()
            return detect_regions(tsv, source.size, *settings)
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
        return detect_regions(stdout.decode('utf-8', errors='replace'), source.size, *settings)

    try:
        with stage('standard_ocr_pass') as timing:
            boxes = new_ocr_boxes(run(image, ('--psm', area_layout) if area_layout else ()))
            if timing is not None:
                timing['new_suggestions'] = len(boxes)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('Standard OCR timed out. Try a smaller photo or mark redactions manually.') from error

    if not (enhanced or color_assisted):
        return boxes

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
                found = run(source, ('--psm', area_layout or '11'), timeout=min(15, remaining))
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
        if timing is not None:
            timing['new_suggestions'] = len(boxes) - previous_count
        return True

    if color_assisted:
        check_cancel()
        from ocr_preprocess import strike_reduced_variant
        with stage('strikethrough_preprocess'):
            strike_reduced = strike_reduced_variant(working)
        if strike_reduced is not None and not add_pass(strike_reduced, 'strikethrough recovery'):
            return boxes

    if enhanced:
        with stage('grayscale_preprocess'):
            contrast = ImageOps.autocontrast(ImageOps.grayscale(working).filter(ImageFilter.MedianFilter(3)), cutoff=1)
        if not add_pass(contrast, 'enhanced OCR'):
            return boxes
        if executable is None and area_layout is None:
            from ocr_preprocess import small_text_tiles
            for index, (bounds, tile) in enumerate(small_text_tiles(image), 1):
                if not add_pass(tile, f'small-text section {index}', bounds):
                    return boxes
    if color_assisted:
        check_cancel()
        from ocr_preprocess import color_ocr_variants
        with stage('color_preprocess'):
            variants = list(color_ocr_variants(working))
        for index, variant in enumerate(variants, 1):
            if not add_pass(variant, f'color pass {index}'):
                break
    return boxes


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


def scan_folder_image(path, expected, executable, settings, enhanced=False, cancel=None, *, color_assisted=False, area=None):
    image, stamp = read_folder_image(path, expected)
    incomplete = []
    boxes = recognize_regions(image, executable, settings, enhanced, cancel,
                              color_assisted=color_assisted, incomplete=incomplete, area=area)
    return stamp, boxes, incomplete
