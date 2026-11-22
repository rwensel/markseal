import unittest
import subprocess
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from offline_redactor import PRESETS, FolderImage, recognize_regions, new_ocr_boxes
from PIL import Image
from offline_redactor import pixelate, detect_regions, Redactor, apply_redactions
from unittest.mock import Mock, patch
from types import SimpleNamespace
from rapidocr_backend import result_to_tsv
from offline_redactor import save_export
from performance_log import PerformanceRun, stage

class RedactionTests(unittest.TestCase):
    def test_pixelate_preserves_pixels_outside_box(self):
        im = Image.new('RGB', (100, 80), 'white')
        for x in range(10, 70):
            for y in range(10, 50): im.putpixel((x, y), (x*3, y*5, 40))
        out = pixelate(im, [(10, 10, 70, 50)])
        self.assertEqual(im.getpixel((5, 5)), out.getpixel((5, 5)))
        self.assertNotEqual(im.getpixel((12, 12)), out.getpixel((12, 12)))
        self.assertEqual(im.getpixel((12, 12)), (36, 60, 40))

    def test_solid_redaction_changes_only_selected_area(self):
        im = Image.new('RGB', (50, 50), 'white')
        out = apply_redactions(im, [(10, 10, 20, 20)], 'Solid black')
        self.assertEqual(out.getpixel((12, 12)), (0, 0, 0))
        self.assertEqual(out.getpixel((20, 20)), (255, 255, 255))

    def test_select_confirm_and_change_selection(self):
        app = Redactor.__new__(Redactor)
        app.image = Image.new('RGB', (200, 200)); app.scale = 0.5
        app.offset_x = 0; app.offset_y = 0
        app.boxes = [(10, 10, 60, 60), (80, 80, 110, 110)]
        app.selected = set(); app.confirmed = False
        app.path = SimpleNamespace(name='test.png')
        app.status = Mock(); app.render = Mock()
        app.start = (15, 15); app.up(SimpleNamespace(x=15, y=15))
        self.assertEqual(app.selected, {0})
        self.assertEqual(app.selected_boxes(), [(10, 10, 60, 60)])
        app.confirm_selection(); self.assertTrue(app.confirmed)
        app.start = (15, 15); app.up(SimpleNamespace(x=15, y=15))
        self.assertEqual(app.selected, set()); self.assertFalse(app.confirmed)
        app.start = (60, 60); app.up(SimpleNamespace(x=80, y=80))
        self.assertEqual(app.boxes[-1], (120, 120, 161, 161))
        self.assertIn(2, app.selected)

    def test_new_suggestions_start_selected_without_reselecting_existing(self):
        app = Redactor.__new__(Redactor)
        app.image = Image.new('RGB', (200, 200)); app.boxes = [(1, 1, 10, 10)]
        app.selected = set(); app.confirmed = True
        app.all_text = Mock(); app.all_text.get.return_value = False
        app.confidence = Mock(); app.confidence.get.return_value = 50
        app.custom_pattern = Mock(); app.custom_pattern.get.return_value = ''
        app.category_vars = {}
        app.enhanced_ocr = Mock(); app.enhanced_ocr.get.return_value = False
        app.color_ocr = Mock(); app.color_ocr.get.return_value = False
        app.ocr_engine = Mock(); app.ocr_engine.get.return_value = "Tesseract"
        app.sensitivity = Mock(); app.sensitivity.get.return_value = "Focused"
        app.render = Mock(); app.status = Mock()
        result = SimpleNamespace(stdout=b'tsv')
        with patch('offline_redactor.find_tesseract', return_value='ocr'), \
             patch('offline_redactor.subprocess.run', return_value=result), \
             patch('offline_redactor.detect_regions', return_value=[(1, 1, 10, 10), (20, 20, 40, 40)]), \
             patch('offline_redactor.messagebox.showinfo'), \
             patch('offline_redactor.PerformanceRun'):
            app.find()
        self.assertEqual(app.selected, {1})
        self.assertFalse(app.confirmed)

    def test_zoom_keeps_pointer_location_and_selection_coordinates(self):
        app = Redactor.__new__(Redactor)
        app.image = Image.new('RGB', (1000, 1000))
        app.canvas = Mock(); app.canvas.winfo_width.return_value = 500; app.canvas.winfo_height.return_value = 500
        app.zoom = 1.0; app.scale = 0.5; app.offset_x = 0; app.offset_y = 0
        app.pan_start = None
        app.render = Mock()
        app.mouse_zoom(SimpleNamespace(x=250, y=250, delta=120, num=None))
        self.assertAlmostEqual((250-app.offset_x) / app.scale, 500)
        self.assertAlmostEqual((250-app.offset_y) / app.scale, 500)
        self.assertGreater(app.scale, 0.5)

    def test_confidence_patterns_and_word_boundaries(self):
        tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t95\tContact\n'
               '5\t1\t1\t1\t1\t2\t50\t20\t100\t10\t92\ta@example.com\n'
               '5\t1\t1\t1\t1\t3\t180\t20\t40\t10\t10\tnoise\n')
        self.assertEqual(detect_regions(tsv, (300,100), categories={'Emails'}, min_confidence=50), [(46,16,154,34)])
        self.assertEqual(detect_regions(tsv, (300,100), categories={'URLs'}, min_confidence=50), [])
        self.assertEqual(len(detect_regions(tsv, (300,100), all_text=True, min_confidence=50)), 2)
        self.assertEqual(detect_regions(tsv, (300,100), categories=set(), custom_pattern='Contact', min_confidence=50), [(6,16,44,34)])

    def test_focused_detects_infrastructure_and_credentials(self):
        lines = [
            ["---", "a/team/prod/deploy.yaml"],
            ["name:", "VAULT_CACERT_PATH"],
            ["value:", "/vault/tls/service_ca.crt"],
            ["name:", "service.kafka.listener.enabled"],
            ["secretName:", "service-tls"],
            ["client_secret:", "fake-value-123"],
            ["status:", "healthy"],
        ]
        tsv = "page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        for line, words in enumerate(lines, 1):
            for column, word in enumerate(words, 1):
                tsv += f"1\t1\t1\t{line}\t{column*200}\t{line*30}\t150\t20\t90\t{word}\n"
        found = detect_regions(tsv, (700, 500), categories=PRESETS['Focused'], min_confidence=50)
        self.assertEqual({(box[1]+4)//30 for box in found}, set(range(1, 7)))
        self.assertIn((396, 176, 554, 204), found)

    def test_optional_ocr_timeout_keeps_completed_suggestions(self):
        image = Image.new('RGB', (120, 80), 'white')
        incomplete = []
        box = (10, 10, 70, 35)
        standard = SimpleNamespace(stdout=b'tsv')
        with patch('offline_redactor.subprocess.run', side_effect=[
            standard, subprocess.TimeoutExpired('ocr', 15),
        ]) as run, patch('offline_redactor.detect_regions', return_value=[box]):
            result = recognize_regions(image, 'ocr', (False,), enhanced=True, incomplete=incomplete)
        self.assertEqual(result, [box])
        self.assertEqual(incomplete, ['enhanced OCR timed out'])
        self.assertLessEqual(run.call_args.kwargs['timeout'], 15)
        entry = FolderImage(SimpleNamespace(name='example.png'))
        entry.add_suggestions(result, incomplete)
        self.assertEqual(entry.selected, {0})
        self.assertEqual(entry.status, 'Partial scan · review needed')

    def test_small_area_model_fallback_requires_exact_label_and_confidence(self):
        image = Image.new('RGB', (200, 140), 'white')
        area = (20, 10, 100, 42)
        settings = (False, set(), 40, r'\b(?:CRE|DOD)\b')
        with patch('rapidocr_backend.recognize_words', return_value=''):
            for text, confidence, expected in [('CRE', 95, [area]), ('DOO', 95, []),
                                                ('other CRE', 95, []), ('DOD', 20, [])]:
                with self.subTest(text=text, confidence=confidence):
                    with patch('rapidocr_backend.recognize_single_label', return_value=(text, confidence)):
                        self.assertEqual(recognize_regions(image, None, settings, area=area), expected)

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
        with patch('ocr_preprocess.small_text_tiles', return_value=[((500, 300, 1100, 700), tile)]), \
             patch('rapidocr_backend.recognize_words', side_effect=['', '', tsv]):
            self.assertEqual(recognize_regions(image, None, settings, enhanced=True), [(548, 338, 592, 362)])

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
        from ocr_preprocess import strike_reduced_variant

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

    def test_environment_names_and_bare_merge_request_numbers(self):
        cases = [('ABC_PROD_MOBILE', True, False), ('ABC-stage-web-gateway', True, False),
                 ('safe formatting', False, False), ('!42', False, False), ('42', False, False)]
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        for label, infrastructure, ticket in cases:
            with self.subTest(label=label):
                tsv = header + f'1\t1\t1\t1\t10\t10\t80\t20\t95\t{label}\n'
                self.assertEqual(bool(detect_regions(tsv, (200, 100), categories={'Infrastructure'})), infrastructure)
                self.assertEqual(bool(detect_regions(tsv, (200, 100), categories={'Ticket IDs'})), ticket)

    def test_detects_specific_config_formats_without_matching_ordinary_prose(self):
        examples = [
            ('ABC_harden-cache_pdb_fix', 'Infrastructure'),
            ('dc42abc_AUDIT', 'Infrastructure'),
            ('ns1-abcstage', 'Infrastructure'),
            ('data.ENV_PROFILE', 'Infrastructure'),
            ('system.worker.outbox.schedule.cron', 'Infrastructure'),
            ('jdbc:hive2://server:10000/db', 'URLs'),
            ('node.cluster.example.com', 'URLs'),
            ('safe formatting', None),
            ('configmap.yaml', None),
        ]
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        for text, category in examples:
            with self.subTest(text=text):
                rows = header + f'1\t1\t1\t1\t10\t10\t100\t20\t95\t{text}\n'
                self.assertEqual(bool(detect_regions(rows, (200,100), categories={'Infrastructure','URLs'})),
                                 category is not None)

    def test_model_word_boxes_keep_regex_matches_tight(self):
        def polygon(left, right):
            return [(left, 12), (right, 12), (right, 27), (left, 27)]

        result = SimpleNamespace(
            boxes=[polygon(10, 160)], txts=('Status BFE',), scores=(0.98,),
            word_results=((('Status', .95, polygon(10, 75)), ('BFE', .99, polygon(110, 160))),),
        )
        settings = (False, set(), 40, r'\bBFE\b')
        rows = result_to_tsv(result, (200, 100))
        self.assertEqual(detect_regions(rows, (200, 100), *settings), [(106, 8, 165, 32)])

    def test_failed_png_encoding_does_not_publish_partial_file(self):
        class BrokenImage:
            width = height = 100

            def save(self, stream, **options):
                stream.write(b'incomplete')
                raise OSError('write failed')

        with TemporaryDirectory() as folder:
            target = Path(folder) / 'test.png'
            with self.assertRaises(OSError):
                save_export(BrokenImage(), target, {'boxes': []})
            self.assertEqual(list(Path(folder).iterdir()), [])
            target.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                save_export(Image.new('RGB', (10, 10)), target, {'boxes': []})
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_performance_log_records_timings_without_exception_message(self):
        with TemporaryDirectory() as folder, patch('performance_log.log_directory', return_value=Path(folder)):
            run = PerformanceRun('Scanning', 1)
            with self.assertRaises(OSError), run.image(0), stage('OCR'):
                raise OSError('private filename')
            run.finish()
            raw = run.path.read_text(encoding='utf-8')
            self.assertNotIn('private filename', raw)
            start, image, end = map(json.loads, raw.splitlines())
            self.assertEqual(image['image_index'], 1)
            self.assertEqual(image['stages'][0]['error_type'], 'OSError')
            self.assertGreaterEqual(image['stages'][0]['elapsed_ms'], 0)
            self.assertEqual(end['failed'], 1)

    def test_detects_sensitive_line_but_not_generic_text(self):
        rows = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t90\t10\t95\tuser@example.com\n5\t1\t1\t1\t2\t1\t10\t50\t50\t10\t95\tDashboard\n'
        self.assertEqual(detect_regions(rows, (200, 100)), [(6, 16, 104, 34)])
        self.assertEqual(len(detect_regions(rows, (200, 100), all_text=True)), 2)

if __name__ == '__main__': unittest.main()
