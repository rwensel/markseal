"""OCR seam: one adapter interface, multi-pass orchestration, and area reads."""
from __future__ import annotations

import csv
import io
import math
import re
import subprocess
from time import monotonic

from PIL import Image, ImageFilter, ImageOps

from .performance_log import stage

from .boxset import BoxList, new_ocr_boxes, same_region
from .detection import detect_regions, learned_pattern_rules
from .images import read_folder_image
from .jobs import ScanCancelled


class RapidEngine:
    single_label = True

    def recognize(self, image, *, psm=None, cancel=None, timeout=120):
        from .rapidocr_backend import recognize_words
        with stage('rapidocr_inference', width=image.width, height=image.height):
            return recognize_words(image)

    def read_label(self, crop):
        from .rapidocr_backend import recognize_single_label
        return recognize_single_label(crop)


def make_engine():
    from .rapidocr_backend import model_files
    model_files()
    return RapidEngine()


def recognize_regions(image, engine, settings, enhanced=False, cancel=None, *,
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
        boxes = recognize_regions(enlarged, engine, settings, enhanced, cancel,
                                  color_assisted=color_assisted, incomplete=incomplete,
                                  area_layout='7' if crop.width >= 6*crop.height else '6',
                                  progress=progress)
        all_text, _, confidence, pattern = settings[:4]
        learned = settings[4] if len(settings) > 4 else ()
        expressions = []
        if pattern:
            expressions.append(('Custom pattern', re.compile(pattern, re.IGNORECASE)))
        expressions.extend((label, re.compile(value, re.IGNORECASE))
                           for label, value in learned_pattern_rules(learned))
        if (not boxes and engine.single_label and not all_text and expressions
                and crop.height <= 180 and crop.width <= min(600, 6*crop.height)):
            if cancel is not None and cancel.is_set():
                raise ScanCancelled
            report('Reading selected label')
            text, score = engine.read_label(crop)
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

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ScanCancelled

    def run(source, psm=None, timeout=120):
        check_cancel()
        detected = {}
        tsv = engine.recognize(source, psm=psm, cancel=cancel, timeout=timeout)
        check_cancel()
        return detect_regions(tsv, source.size, *settings, rules=detected), detected

    try:
        with stage('standard_ocr_pass') as timing:
            report('Recognizing text')
            found, pass_rules = run(image, psm=area_layout)
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
                found, found_rules = run(source, psm=area_layout or '11', timeout=min(15, remaining))
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
        from .ocr_preprocess import strike_reduced_variant
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
        if engine.single_label and area_layout is None:
            from .ocr_preprocess import small_text_tiles
            for index, (bounds, tile) in enumerate(small_text_tiles(image), 1):
                report(f'Reading small-text section {index}')
                if not add_pass(tile, f'small-text section {index}', bounds):
                    return BoxList(boxes, rules)
    if color_assisted:
        check_cancel()
        from .ocr_preprocess import color_ocr_variants
        with stage('color_preprocess'):
            variants = list(color_ocr_variants(working))
        for index, variant in enumerate(variants, 1):
            report(f'Color pass {index} of {len(variants)}')
            if not add_pass(variant, f'color pass {index}'):
                break
    return BoxList(boxes, rules)


def text_from_tsv(tsv):
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        word = row.get('text', '').strip()
        if not word:
            continue
        key = tuple(row.get(name, '') for name in ('page_num', 'block_num', 'par_num', 'line_num'))
        lines.setdefault(key, []).append(word)
    return '\n'.join(' '.join(words) for words in lines.values())


def read_area_text(image, engine, area):
    left, top, right, bottom = area
    crop = image.crop((left, top, right, bottom))
    if max(crop.size) > 0:
        factor = min(3, 1600 / max(crop.size))
        if factor > 1:
            crop = crop.resize((max(1, round(crop.width * factor)),
                                max(1, round(crop.height * factor))), Image.Resampling.LANCZOS)
    border = max(6, crop.height // 20)
    crop = ImageOps.expand(crop, border=border, fill=crop.getpixel((0, 0)))
    psm = '7' if crop.width >= 6 * crop.height else '6'
    return text_from_tsv(engine.recognize(crop, psm=psm, timeout=30))


def scan_folder_image(path, expected, engine, settings, enhanced=False, cancel=None, *, color_assisted=False, area=None):
    image, stamp = read_folder_image(path, expected)
    incomplete = []
    boxes = recognize_regions(image, engine, settings, enhanced, cancel,
                              color_assisted=color_assisted, incomplete=incomplete, area=area)
    return stamp, boxes, incomplete
