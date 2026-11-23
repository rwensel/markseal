"""OCR pipeline and engine adapter behavior."""
import unittest

from tests.support import (
    FakeEngine,
    FolderImage,
    Image,
    Path,
    RapidEngine,
    SimpleNamespace,
    TemporaryDirectory,
    TesseractEngine,
    detect_regions,
    make_engine,
    new_ocr_boxes,
    patch,
    pattern_from_text,
    read_area_text,
    recognize_regions,
    result_to_tsv,
    scan_folder_image,
    subprocess,
    text_from_tsv,
)


class OcrPipelineTests(unittest.TestCase):
    def test_recognizer_reports_progress_stages(self):
        image = Image.new('RGB', (120, 80), 'white')
        stages = []
        with patch('redactor.ocr.detect_regions', return_value=[]):
            recognize_regions(image, FakeEngine('tsv'), (False,), progress=stages.append)
        self.assertIn('Recognizing text', stages)

    def test_selected_area_text_can_be_read_and_used_as_a_learned_pattern(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv = header + (
            '1\t1\t1\t1\t10\t10\t80\t20\t95\tCrownfern\n'
            '1\t1\t1\t1\t100\t10\t70\t20\t95\tAnalytics\n'
            '1\t1\t1\t2\t10\t40\t40\t20\t95\tpass\n'
            '1\t1\t1\t2\t60\t40\t20\t20\t95\t42\n'
        )
        self.assertEqual(text_from_tsv(tsv), 'Crownfern Analytics\npass 42')
        image = Image.new('RGB', (240, 90), 'white')
        engine = TesseractEngine('ocr')
        with patch('redactor.ocr.subprocess.run',
                   return_value=SimpleNamespace(stdout=tsv.encode('utf-8'))) as run:
            self.assertEqual(read_area_text(image, engine, (10, 10, 200, 70)),
                             'Crownfern Analytics\npass 42')
        self.assertEqual(run.call_args.args[0][-1], 'tsv')
        found = detect_regions(tsv, (240, 90), categories=set(),
                               learned_patterns=[pattern_from_text('Crownfern Analytics')])
        self.assertEqual(len(found), 2)

    def test_optional_ocr_timeout_keeps_completed_suggestions(self):
        image = Image.new('RGB', (120, 80), 'white')
        incomplete = []
        box = (10, 10, 70, 35)
        engine = FakeEngine(outcomes=['tsv', subprocess.TimeoutExpired('ocr', 15)])
        with patch('redactor.ocr.detect_regions', return_value=[box]):
            result = recognize_regions(image, engine, (False,), enhanced=True, incomplete=incomplete)
        self.assertEqual(result, [box])
        self.assertEqual(incomplete, ['enhanced OCR timed out'])
        self.assertLessEqual(engine.calls[-1]['timeout'], 15)
        entry = FolderImage(SimpleNamespace(name='example.png'))
        entry.add_suggestions(result, incomplete)
        self.assertEqual(entry.selected, {0})
        self.assertEqual(entry.status, 'Partial scan · review needed')

    def test_small_area_model_fallback_requires_exact_label_and_confidence(self):
        image = Image.new('RGB', (200, 140), 'white')
        area = (20, 10, 100, 42)
        settings = (False, set(), 40, r'\b(?:CRE|DOD)\b')
        for text, confidence, expected in [('CRE', 95, [area]), ('DOO', 95, []),
                                            ('other CRE', 95, []), ('DOD', 20, [])]:
            with self.subTest(text=text, confidence=confidence):
                engine = FakeEngine('')
                engine.single_label = True
                engine.label = (text, confidence)
                self.assertEqual(recognize_regions(image, engine, settings, area=area), expected)
        learned = (False, set(), 40, '', (('Blocked pattern: CRE', r'\b(?:CRE|DOD)\b'),))
        engine = FakeEngine('')
        engine.single_label = True
        engine.label = ('CRE', 95)
        result = recognize_regions(image, engine, learned, area=area)
        self.assertEqual(result, [area])
        self.assertEqual(result.rules[area], ('Blocked pattern: CRE',))

    def test_nested_ocr_duplicates_are_suppressed_without_merging_neighbors(self):
        tight = (1154, 1103, 1221, 1159)
        padded = (1143, 1078, 1243, 1188)
        neighboring = (1215, 1104, 1283, 1158)
        wider_line = (850, 1080, 1514, 1188)
        self.assertEqual(new_ocr_boxes([tight, padded, neighboring, wider_line]),
                         [tight, neighboring, wider_line])
        self.assertEqual(new_ocr_boxes([tight], [padded]), [])

        entry = FolderImage(SimpleNamespace(name='example.png'), boxes=[tight])
        self.assertEqual(entry.add_suggestions([padded, neighboring]), 1)
        self.assertEqual(entry.boxes, [tight, neighboring])
        self.assertEqual(entry.selected, {1})

    def test_enhanced_model_maps_tile_boxes_back_to_full_image(self):
        image = Image.new('RGB', (1200, 800), 'white')
        tile = Image.new('RGB', (1200, 800), 'white')
        settings = (False, set(), 40, r'\bBFE\b')
        tsv = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '1\t1\t1\t1\t100\t80\t80\t40\t95\tBFE\n')
        engine = FakeEngine(outcomes=['', '', tsv])
        engine.single_label = True
        with patch('redactor.ocr_preprocess.small_text_tiles', return_value=[((500, 300, 1100, 700), tile)]):
            self.assertEqual(recognize_regions(image, engine, settings, enhanced=True), [(548, 338, 592, 362)])

    def test_model_places_matched_word_even_if_other_characters_lack_boxes(self):
        def polygon(left, right):
            return [(left, 12), (right, 12), (right, 27), (left, 27)]

        fragments = tuple((char, .99, polygon(left, left+10))
                          for char, left in zip('IDBFE', (12, 22, 70, 80, 90)))
        result = SimpleNamespace(
            boxes=[polygon(10, 110)], txts=('ID: BFE',), scores=(.98,),
            word_results=(fragments,),
        )
        rows = result_to_tsv(result, (200, 100))
        self.assertEqual(detect_regions(rows, (200, 100), False, set(), 40, r'\bBFE\b'),
                         [(66, 8, 105, 32)])

    def test_strikethrough_pass_reduces_stroke_without_moving_pixels(self):
        from PIL import ImageDraw
        from redactor.ocr_preprocess import strike_reduced_variant

        image = Image.new('RGB', (320, 100), 'white')
        draw = ImageDraw.Draw(image)
        draw.line((20, 55, 219, 55), fill='#a32233', width=2)
        draw.rectangle((250, 30, 260, 42), fill='black')
        enhanced = strike_reduced_variant(image)
        self.assertIsNotNone(enhanced)
        self.assertEqual(enhanced.size, image.size)
        self.assertEqual(enhanced.getpixel((100, 55)), (255, 255, 255))
        self.assertEqual(enhanced.getpixel((256, 36)), (0, 0, 0))
        self.assertEqual(image.getpixel((100, 55)), (163, 34, 51))
        self.assertIsNone(strike_reduced_variant(Image.new('RGB', (320, 100), 'white')))


class OcrAdapterTests(unittest.TestCase):
    def test_fake_adapter_drives_the_whole_pass_pipeline(self):
        image = Image.new('RGB', (1200, 800), 'white')
        settings = (False, {'Emails'}, 40, '')
        engine = FakeEngine(outcomes=['', ''])
        with patch('redactor.ocr_preprocess.strike_reduced_variant', return_value=None), \
             patch('redactor.ocr_preprocess.small_text_tiles', return_value=[]), \
             patch('redactor.ocr_preprocess.color_ocr_variants', return_value=[]):
            recognize_regions(image, engine, settings, enhanced=True, color_assisted=True)
        self.assertEqual([call['psm'] for call in engine.calls], [None, '11'])

    def test_tesseract_and_rapid_adapters_return_the_same_box_shape(self):
        tsv = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n')
        image = Image.new('RGB', (300, 100), 'white')
        settings = (False, {'Emails'}, 50, '')
        with patch('redactor.ocr.subprocess.run',
                   return_value=SimpleNamespace(stdout=tsv.encode('utf-8'))):
            tesseract = recognize_regions(image, TesseractEngine('ocr'), settings)
        with patch('redactor.rapidocr_backend.recognize_words', return_value=tsv):
            rapid = recognize_regions(image, RapidEngine(), settings)
        self.assertEqual(tesseract, rapid)
        self.assertEqual(tesseract, [(6, 16, 114, 44)])

    def test_make_engine_validates_the_requested_backend(self):
        self.assertIsInstance(make_engine('Tesseract', executable='ocr'), TesseractEngine)
        with patch('redactor.rapidocr_backend.model_files', return_value={}):
            engine = make_engine('RapidOCR')
        self.assertIsInstance(engine, RapidEngine)
        self.assertTrue(engine.single_label)
        with patch('redactor.rapidocr_backend.model_files', side_effect=OSError('missing models')):
            with self.assertRaises(OSError):
                make_engine('RapidOCR')
        with patch('redactor.ocr.find_tesseract', return_value=None):
            with self.assertRaises(OSError):
                make_engine('Tesseract')

    def test_area_scan_rescales_adapter_boxes_to_source_pixels(self):
        image = Image.new('RGB', (200, 100), 'white')
        tsv = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '1\t1\t1\t1\t40\t20\t80\t20\t95\ta@example.com\n')
        engine = FakeEngine(tsv)
        result = recognize_regions(image, engine, (False, {'Emails'}, 40, ''),
                                   area=(20, 10, 100, 42))
        self.assertEqual(result, [(29, 14, 51, 21)])
        self.assertEqual(engine.calls[0]['size'], (320, 128))

    def test_single_label_fallback_is_reserved_for_detectorless_adapters(self):
        image = Image.new('RGB', (200, 140), 'white')
        area = (20, 10, 100, 42)
        settings = (False, set(), 40, r'\bCRE\b')
        engine = FakeEngine('')
        engine.label = ('CRE', 95)
        self.assertEqual(recognize_regions(image, engine, settings, area=area), [])

    def test_folder_scan_passes_the_adapter_through(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'one.png'
            Image.new('RGB', (120, 80), 'white').save(path)
            tsv = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
                   '1\t1\t1\t1\t10\t20\t80\t20\t95\ta@example.com\n')
            engine = FakeEngine(tsv)
            stamp, boxes, incomplete = scan_folder_image(
                path, None, engine, (False, {'Emails'}, 50, ''))
        self.assertEqual(boxes, [(6, 16, 94, 44)])
        self.assertEqual(incomplete, [])
