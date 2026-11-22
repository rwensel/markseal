"""Read-only checks for exported copies and their coordinate logs."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw


def audit_export(original, exported, boxes):
    if original.size != exported.size:
        raise ValueError('image dimensions differ')
    mask = Image.new('L', original.size)
    draw = ImageDraw.Draw(mask)
    width, height = original.size
    for left, top, right, bottom in boxes:
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError('invalid redaction coordinates')
        draw.rectangle((left, top, right-1, bottom-1), fill=255)
    diff = ImageChops.difference(original, exported)
    diff.paste((0, 0, 0), (0, 0), mask)
    return not bool(diff.getbbox()), mask


def classify_coverage(mask, boxes):
    counts = dict(covered=0, partial=0, uncovered=0)
    for left, top, right, bottom in boxes:
        covered = mask.crop((left, top, right, bottom)).histogram()[255]
        status = 'uncovered' if not covered else 'covered' if covered == (right-left)*(bottom-top) else 'partial'
        counts[status] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('originals', type=Path)
    parser.add_argument('exports', type=Path)
    parser.add_argument('--ocr', action='store_true', help='Run local RapidOCR Broad passes on originals and exports.')
    parser.add_argument('--use-app-pattern', action='store_true',
                        help='Also test the saved custom expression without printing it.')
    args = parser.parse_args()
    custom = ''
    if args.use_app_pattern:
        if not args.ocr:
            parser.error('--use-app-pattern requires --ocr')
        from offline_redactor import preferences_path
        try:
            saved = json.loads(preferences_path().read_text(encoding='utf-8'))
            custom = saved.get('custom_pattern', '')
        except (OSError, ValueError, AttributeError):
            parser.error('No readable app settings found')
        if not isinstance(custom, str) or not custom:
            parser.error('Set a custom expression in the app first')
    for path in sorted(args.exports.glob('*.png')):
        item = {'export': path.name}
        try:
            with Image.open(path) as file:
                file.verify()
            sidecar = path.with_suffix('.redactions.json')
            if not sidecar.is_file():
                raise ValueError('coordinate log missing')
            log = json.loads(sidecar.read_text(encoding='utf-8'))
            source = log['source_filename']
            if Path(source).name != source:
                raise ValueError('invalid source filename in log')
            with Image.open(args.originals / source) as file:
                original = file.convert('RGB')
            with Image.open(path) as file:
                exported = file.convert('RGB')
            boxes = log['redaction_rectangles_xyxy']
            exact, mask = audit_export(original, exported, boxes)
            item.update(outside_pixels_unchanged=exact, logged_boxes=len(boxes),
                        wide_boxes=sum(right-left >= .25*original.width for left, top, right, bottom in boxes),
                        masked_percent=round(100*mask.histogram()[255]/(mask.width*mask.height), 3))
            if args.ocr:
                from offline_redactor import PRESETS, recognize_regions
                settings = (False, PRESETS['Broad'], 40, custom)
                suggested = recognize_regions(original, None, settings)
                item['ocr_candidates'] = classify_coverage(mask, suggested)
                residual = recognize_regions(exported, None, settings)
                item['export_ocr_candidates'] = classify_coverage(mask, residual)
        except (OSError, ValueError, SyntaxError, KeyError) as error:
            item['issue'] = str(error)
        print(json.dumps(item), flush=True)


if __name__ == '__main__':
    main()
