import unittest
import subprocess
from offline_redactor import PRESETS, FolderImage, recognize_regions
from PIL import Image
from offline_redactor import pixelate, detect_regions, Redactor, apply_redactions
from unittest.mock import Mock, patch
from types import SimpleNamespace

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
        app.render = Mock(); app.status = Mock()
        result = SimpleNamespace(stdout=b'tsv')
        with patch('offline_redactor.find_tesseract', return_value='ocr'), \
             patch('offline_redactor.subprocess.run', return_value=result), \
             patch('offline_redactor.detect_regions', return_value=[(1, 1, 10, 10), (20, 20, 40, 40)]), \
             patch('offline_redactor.messagebox.showinfo'):
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

    def test_detects_sensitive_line_but_not_generic_text(self):
        rows = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t90\t10\t95\tuser@example.com\n5\t1\t1\t1\t2\t1\t10\t50\t50\t10\t95\tDashboard\n'
        self.assertEqual(detect_regions(rows, (200, 100)), [(6, 16, 104, 34)])
        self.assertEqual(len(detect_regions(rows, (200, 100), all_text=True)), 2)

if __name__ == '__main__': unittest.main()
