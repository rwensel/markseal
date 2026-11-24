"""Adapt locally bundled RapidOCR polygons to MarkSeal's OCR word format."""
import csv
import io
import re
from difflib import SequenceMatcher
from pathlib import Path
from queue import Empty, Queue
from threading import Lock

from PIL import Image, ImageOps
from .performance_log import stage

def model_files():
    try:
        import rapidocr
        import onnxruntime
    except ImportError as error:
        raise OSError('Install the rapidocr extra (pip install -e ".[rapidocr]") to use RapidOCR.') from error
    directory = Path(rapidocr.__file__).resolve().parent / 'models'
    files = {
        'Det': directory / 'PP-OCRv6_det_small.onnx',
        'Rec': directory / 'PP-OCRv6_rec_small.onnx',
        'Cls': directory / 'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
    }
    if not all(path.is_file() for path in files.values()):
        raise OSError('Bundled RapidOCR models are missing. Reinstall the rapidocr extra (pip install -e ".[rapidocr]").')
    return files


def _create_engine():
    files = model_files()
    from rapidocr import RapidOCR

    with stage('load_rapidocr_engine'):
        return RapidOCR(params={
            **{f'{stage}.model_path': str(path) for stage, path in files.items()},
            'Global.log_level': 'error',
            'Global.text_score': 0.0,
            'Global.use_cls': False,
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        })


class EnginePool:
    def __init__(self, create=None):
        self._create = create or _create_engine
        self._idle = Queue()
        self._lock = Lock()

    def borrow(self):
        try:
            return self._idle.get_nowait()
        except Empty:
            pass
        with self._lock:
            try:
                return self._idle.get_nowait()
            except Empty:
                return self._create()

    def release(self, engine):
        self._idle.put(engine)

    def close(self):
        while True:
            try:
                self._idle.get_nowait()
            except Empty:
                return


_pool = EnginePool()


def positioned_words(text, confidence, line_polygon, fragments):
    """Keep recognized text intact and use character coordinates where they align."""
    if not fragments:
        return [(text, confidence, line_polygon)]

    # Older/fallback results can contain whole words instead of characters.
    if any(len(token.strip()) > 1 for token, _, _ in fragments):
        if (all(points is not None for _, _, points in fragments) and
                text.split() == [token.strip() for token, _, _ in fragments]):
            return fragments
        return [(text, confidence, line_polygon)]

    chars = [(token.strip(), score, points) for token, score, points in fragments if token.strip()]
    visible = [(index, char) for index, char in enumerate(text) if not char.isspace()]
    original = ''.join(char for _, char in visible)
    located = ''.join(char for char, _, _ in chars)
    aligned = {}
    for start, detected, count in SequenceMatcher(None, original, located, autojunk=False).get_matching_blocks():
        for offset in range(count):
            _, score, points = chars[detected+offset]
            if points is not None:
                aligned[visible[start+offset][0]] = (detected+offset, score, points)

    words = []
    for match in re.finditer(r'\S+', text):
        letters = [aligned.get(i) for i in range(match.start(), match.end())]
        if any(letter is None for letter in letters) or (original != located and original.count(match.group()) > 1):
            words.append((match.group(), confidence, line_polygon))
            continue
        indexes, scores, polygons = zip(*letters)
        if indexes[-1]-indexes[0]+1 != len(indexes):
            words.append((match.group(), confidence, line_polygon))
            continue
        points = [point for polygon in polygons for point in polygon]
        words.append((match.group(), sum(scores)/len(scores), points))
    return words


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
        for token, score, points in positioned_words(text, confidence, polygon, words):
            xs, ys = zip(*points)
            left, top = max(0, int(min(xs))), max(0, int(min(ys)))
            right, bottom = min(width, int(max(xs))+1), min(height, int(max(ys))+1)
            if left < right and top < bottom:
                writer.writerow((1, 1, 1, index+1, left, top, right-left, bottom-top,
                                 f'{100*score:.3f}', token))
    return buffer.getvalue()


def recognize_words(image):
    engine = _pool.borrow()
    try:
        output = engine(image.convert('RGB'), return_word_box=True, return_single_char_box=True,
                        use_det=True, use_cls=False)
    finally:
        _pool.release(engine)
    return result_to_tsv(output, image.size)



def recognize_single_label(crop):
    """Read one user-selected label without requiring the text detector to find it."""
    image = crop.convert('RGB')
    factor = min(3, 1200 / max(image.size))
    image = image.resize((max(1, round(image.width*factor)), max(1, round(image.height*factor))),
                         Image.Resampling.LANCZOS)
    image = ImageOps.expand(image, border=10, fill=image.getpixel((0, 0)))
    engine = _pool.borrow()
    try:
        output = engine(image, return_word_box=False, use_det=False, use_cls=False)
    finally:
        _pool.release(engine)
    if output.txts and output.scores:
        return output.txts[0].strip(), 100 * output.scores[0]
    return '', 0.0
