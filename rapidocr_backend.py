"""Adapt locally bundled RapidOCR polygons to the redactor's OCR word format."""
import csv
import io
from functools import lru_cache
from pathlib import Path


def model_files():
    try:
        import rapidocr
        import onnxruntime
    except ImportError as error:
        raise OSError('Install requirements-rapidocr.txt to use RapidOCR.') from error
    directory = Path(rapidocr.__file__).resolve().parent / 'models'
    files = {
        'Det': directory / 'PP-OCRv6_det_small.onnx',
        'Rec': directory / 'PP-OCRv6_rec_small.onnx',
        'Cls': directory / 'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
    }
    if not all(path.is_file() for path in files.values()):
        raise OSError('Bundled RapidOCR models are missing. Reinstall requirements-rapidocr.txt.')
    return files


@lru_cache(maxsize=1)
def load_engine():
    files = model_files()
    from rapidocr import RapidOCR

    return RapidOCR(params={
        **{f'{stage}.model_path': str(path) for stage, path in files.items()},
        'Global.log_level': 'error',
        'Global.text_score': 0.0,
        'Global.use_cls': False,
        'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
    })


def result_to_tsv(result, size):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter='\t', lineterminator='\n')
    writer.writerow(('page_num', 'block_num', 'par_num', 'line_num', 'left', 'top',
                     'width', 'height', 'conf', 'text'))
    if result.boxes is None or not result.txts:
        return buffer.getvalue()
    width, height = size
    for index, (polygon, text, confidence) in enumerate(zip(result.boxes, result.txts, result.scores)):
        words = result.word_results[index] if index < len(result.word_results) else None
        # Keep the full line when word coordinates are unavailable or do not
        # represent every recognized character.
        if (not words or any(word[2] is None for word in words) or
                ''.join(text.split()) != ''.join(''.join(word[0].split()) for word in words)):
            words = [(text, confidence, polygon)]
        for token, score, points in words:
            xs, ys = zip(*points)
            left, top = max(0, int(min(xs))), max(0, int(min(ys)))
            right, bottom = min(width, int(max(xs))+1), min(height, int(max(ys))+1)
            if left < right and top < bottom:
                writer.writerow((1, 1, 1, index+1, left, top, right-left, bottom-top,
                                 f'{100*score:.3f}', token))
    return buffer.getvalue()


def recognize_words(image):
    output = load_engine()(image.convert('RGB'), return_word_box=True, use_cls=False)
    return result_to_tsv(output, image.size)
