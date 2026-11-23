import unittest
import subprocess
import json
import re
import time
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock, Thread
from PIL import Image
from unittest.mock import patch
from types import SimpleNamespace
import rapidocr_backend
from rapidocr_backend import result_to_tsv
from performance_log import PerformanceRun, stage
from redactor.core import (
    PRESETS, BoxList, FolderImage, apply_redactions, batch_worker_count, detect_regions,
    new_ocr_boxes, pattern_from_text, pixelate, read_area_text, recognize_regions, save_export,
    text_from_tsv, value_pattern_expression, value_pattern_types,
)
from redactor.review import Review
from redactor.jobs import JobRunner, progress_line

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
        review = Review()
        review.load(Image.new('RGB', (200, 200)), Path('test.png'))
        review.set_view_size(100, 100)
        review.boxes = [(10, 10, 60, 60), (80, 80, 110, 110)]
        review.selected = set()
        review.confirmed = False
        review.press(15, 15)
        review.release(15, 15)
        self.assertEqual(review.selected, {0})
        self.assertEqual(review.selected_boxes(), [(10, 10, 60, 60)])
        review.confirmed = True
        review.press(15, 15)
        review.release(15, 15)
        self.assertEqual(review.selected, set())
        self.assertFalse(review.confirmed)
        review.press(60, 60)
        review.release(80, 80)
        self.assertEqual(review.boxes[-1], (120, 120, 161, 161))
        self.assertIn(2, review.selected)

    def test_new_suggestions_start_selected_without_reselecting_existing(self):
        review = Review()
        review.image = Image.new('RGB', (200, 200))
        review.boxes = [(1, 1, 10, 10)]
        review.selected = set()
        review.confirmed = True
        added = review.add_suggestions([(1, 1, 10, 10), (20, 20, 40, 40)])
        self.assertEqual(added, 1)
        self.assertEqual(review.selected, {1})
        self.assertFalse(review.confirmed)

    def test_nested_selected_suggestions_keep_only_the_outer_box(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        other = (200, 10, 260, 60)
        added = review.add_suggestions([inner, outer, other])
        self.assertEqual(added, 2)
        self.assertEqual(review.boxes, [outer, other])
        self.assertEqual(review.selected, {0, 1})

    def test_suggestion_inside_existing_selected_area_is_skipped(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        review.boxes = [outer]
        review.selected = {0}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([(20, 20, 60, 40)]), 0)
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertTrue(review.confirmed)

    def test_outer_suggestion_replaces_existing_selected_inner_box(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        inner = (20, 20, 60, 40)
        outer = (10, 10, 120, 60)
        review.boxes = [inner]
        review.selected = {0}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([outer]), 1)
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertFalse(review.confirmed)

    def test_unselected_outer_box_does_not_remove_selected_inner_box(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        review.boxes = [outer, inner]
        review.selected = {1}
        self.assertEqual(review.add_suggestions([(200, 10, 260, 60)]), 1)
        self.assertEqual(review.boxes, [outer, inner, (200, 10, 260, 60)])
        self.assertEqual(review.selected, {1, 2})

    def test_folder_suggestions_skip_boxes_inside_selected_area(self):
        entry = FolderImage(Path('example.png'))
        outer = (10, 10, 120, 60)
        entry.boxes = [outer]
        entry.selected = {0}
        self.assertEqual(entry.add_suggestions([(20, 20, 60, 40)]), 0)
        self.assertEqual(entry.boxes, [outer])
        self.assertEqual(entry.selected, {0})

    def test_scan_cleans_existing_nested_selected_boxes(self):
        review = Review()
        review.image = Image.new('RGB', (400, 300))
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        review.boxes = [outer, inner]
        review.selected = {0, 1}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([]), 0)
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertFalse(review.confirmed)

    def test_zoom_keeps_pointer_location_and_selection_coordinates(self):
        review = Review()
        review.load(Image.new('RGB', (1000, 1000)), Path('test.png'))
        review.set_view_size(500, 500)
        self.assertAlmostEqual(review.scale, 0.5)
        self.assertTrue(review.zoom_at(250, 250, 1))
        self.assertAlmostEqual((250-review.offset_x) / review.scale, 500)
        self.assertAlmostEqual((250-review.offset_y) / review.scale, 500)
        self.assertGreater(review.scale, 0.5)

    def test_small_image_is_centered_in_the_view(self):
        review = Review()
        review.load(Image.new('RGB', (200, 100)), Path('small.png'))
        review.set_view_size(500, 400)
        self.assertEqual(review.scale, 1.0)
        self.assertAlmostEqual(review.offset_x, 150)
        self.assertAlmostEqual(review.offset_y, 150)

    def test_recognizer_reports_progress_stages(self):
        image = Image.new('RGB', (120, 80), 'white')
        stages = []
        with patch('redactor.core.subprocess.run', return_value=SimpleNamespace(stdout=b'tsv')), \
             patch('redactor.core.detect_regions', return_value=[]):
            recognize_regions(image, 'ocr', (False,), progress=stages.append)
        self.assertIn('Recognizing text', stages)

    def test_confidence_patterns_and_word_boundaries(self):
        tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t95\tContact\n'
               '5\t1\t1\t1\t1\t2\t50\t20\t100\t10\t92\ta@example.com\n'
               '5\t1\t1\t1\t1\t3\t180\t20\t40\t10\t10\tnoise\n')
        self.assertEqual(detect_regions(tsv, (300,100), categories={'Emails'}, min_confidence=50), [(46,16,154,34)])
        self.assertEqual(detect_regions(tsv, (300,100), categories={'URLs'}, min_confidence=50), [])
        self.assertEqual(len(detect_regions(tsv, (300,100), all_text=True, min_confidence=50)), 2)
        self.assertEqual(detect_regions(tsv, (300,100), categories=set(), custom_pattern='Contact', min_confidence=50), [(6,16,44,34)])

    def test_generated_pattern_matches_the_selected_text_and_not_neighbors(self):
        pattern = pattern_from_text('DemoOnly_Pass-91!q')
        self.assertIsNotNone(re.search(pattern, 'demoOnly_pass-91!q', re.IGNORECASE))
        self.assertIsNone(re.search(pattern, 'DemoOnly_Pass-92!q', re.IGNORECASE))
        self.assertIsNone(re.search(pattern_from_text('Contact'), 'Contacted', re.IGNORECASE))
        multi = pattern_from_text('Crownfern Analytics\npass 42')
        self.assertIsNotNone(re.search(multi, 'CROWNFERN analytics', re.IGNORECASE))
        self.assertIsNotNone(re.search(multi, 'PASS 42', re.IGNORECASE))
        self.assertIsNone(re.search(multi, 'pass 43', re.IGNORECASE))
        prefix = pattern_from_text('Crownfern\nCrownfern Analytics')
        self.assertEqual(re.search(prefix, 'Crownfern Analytics', re.IGNORECASE).group(0),
                         'Crownfern Analytics')

    def test_scan_and_review_keep_rule_labels_and_manual_provenance(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv = header + '1\t1\t1\t1\t10\t20\t100\t20\t95\ta@example.com\n'
        rules = {}
        boxes = detect_regions(tsv, (300, 100), categories={'Emails'}, rules=rules)
        self.assertEqual(rules[boxes[0]], ('Emails',))
        combined = {}
        detect_regions(tsv, (300, 100), categories={'Emails'},
                       learned_patterns=[('Blocked pattern: email', r'.+')], rules=combined)
        self.assertEqual(set(combined[boxes[0]]), {'Emails', 'Blocked pattern: email'})

        learned_tsv = header + '1\t1\t1\t1\t10\t20\t80\t20\t95\tContact\n'
        learned_rules = {}
        learned_boxes = detect_regions(
            learned_tsv, (300, 100), categories=set(),
            learned_patterns=[('Blocked pattern: Contact', r'\bContact\b')], rules=learned_rules,
        )
        self.assertEqual(learned_rules[learned_boxes[0]], ('Blocked pattern: Contact',))

        all_rules = {}
        all_boxes = detect_regions(tsv, (300, 100), all_text=True, categories=set(), rules=all_rules)
        self.assertEqual(all_rules[all_boxes[0]], ('All text',))

        image = Image.new('RGB', (120, 80), 'white')
        result = BoxList([(10, 10, 40, 30)], {(10, 10, 40, 30): ('Emails',)})
        review = Review()
        review.load(image, Path('rules.png'))
        review.set_view_size(120, 80)
        review.add_suggestions(result)
        self.assertEqual(review.rules, {(10, 10, 40, 30): ('Emails',)})
        review.press(50, 50)
        review.release(80, 70)
        manual = review.boxes[-1]
        self.assertEqual(review.rules[manual], ('Manual box',))
        review.undo()
        self.assertNotIn(manual, review.rules)

        inner = (20, 20, 60, 40)
        outer = (10, 10, 120, 60)
        review.boxes = [inner]
        review.selected = {0}
        review.confirmed = True
        review.rules = {inner: ('Manual box',)}
        review.add_suggestions(BoxList([outer], {outer: ('Secrets',)}))
        self.assertEqual(review.rules, {outer: ('Secrets',)})

        entry = FolderImage(Path('rules.png'))
        entry.add_shared_boxes([(1, 1, 5, 5)], source='Anchor match')
        self.assertEqual(entry.rules[(1, 1, 5, 5)], ('Anchor match',))
        entry.add_suggestions(BoxList([(10, 10, 20, 20)], {(10, 10, 20, 20): ('URLs',)}))
        self.assertEqual(entry.rules[(10, 10, 20, 20)], ('URLs',))
        copied = FolderImage(Path('copied.png'))
        copied.add_shared_boxes([(2, 2, 4, 4)], source='Copied box')
        self.assertEqual(copied.rules[(2, 2, 4, 4)], ('Copied box',))

    def test_value_type_detection_generates_range_patterns(self):
        cases = [
            ('192.0.2.85', 'ipv4', '203.0.113.9', '999.1.1.1'),
            ('192.0.2.85/32', 'ipv4_cidr', '198.51.100.0/24', '192.0.2.85/33'),
            ('2001:db8::1', 'ipv6', '::1', 'gggg::1'),
            ('::ffff:192.0.2.128', 'ipv6', '2001:db8::1', 'gggg::1'),
            ('2001:db8::1/64', 'ipv6_cidr', '2001:db8:1::/48', '2001:db8::1/129'),
            ('550e8400-e29b-41d4-a716-446655440000', 'uuid', '123e4567-e89b-12d3-a456-426614174000', 'not-a-uuid'),
            ('user@example.com', 'email', 'ops@example.org', 'not-an-email'),
            ('https://example.com/path', 'url', 'http://internal.example', 'example.com'),
            ('12345678', 'integer', '42', '12.5'),
            ('deadbeefdeadbeef', 'hex', '0123456789abcdef', 'xyz'),
            ('aa:bb:cc:dd:ee:ff', 'mac', '00:11:22:33:44:55', 'aa:bb:cc:dd:ee'),
            ('2026-11-23', 'date', '2027-01-01', '23-11-2026'),
        ]
        for text, kind, match, miss in cases:
            with self.subTest(text=text, kind=kind):
                self.assertIn(kind, value_pattern_types(text))
                expression = value_pattern_expression(text, kind)
                self.assertIsNotNone(re.search(expression, text, re.IGNORECASE))
                self.assertIsNotNone(re.search(expression, match, re.IGNORECASE))
                self.assertIsNone(re.search(expression, miss, re.IGNORECASE))
        self.assertEqual(value_pattern_expression('Crownfern Analytics', 'fixed'),
                         pattern_from_text('Crownfern Analytics'))
        self.assertEqual(value_pattern_types('ordinary words'), [])

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
        with patch('redactor.core.subprocess.run',
                   return_value=SimpleNamespace(stdout=tsv.encode('utf-8'))) as run:
            self.assertEqual(read_area_text(image, 'ocr', (10, 10, 200, 70)),
                             'Crownfern Analytics\npass 42')
        self.assertEqual(run.call_args.args[0][-1], 'tsv')
        found = detect_regions(tsv, (240, 90), categories=set(),
                               learned_patterns=[pattern_from_text('Crownfern Analytics')])
        self.assertEqual(len(found), 2)

    def test_credential_values_cover_password_and_bearer_without_the_label_or_status(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        rows = [
            (1, 20, 20, 80, 24, 'Password'),
            (2, 240, 21, 165, 23, 'DemoOnly_Pass-91!q'),
            (3, 750, 23, 90, 25, 'Local testing'),
            (4, 20, 65, 106, 24, 'Bearer token'),
            (5, 240, 66, 58, 23, 'Bearer'),
            (5, 306, 66, 165, 24, 'fixture.VeryLongSyntheticToken'),
            (6, 750, 67, 83, 23, 'Read only'),
            (7, 20, 110, 80, 24, 'Password'),
            (8, 750, 110, 90, 24, 'Local testing'),
        ]
        tsv = header + ''.join(f'1\t1\t1\t{line}\t{x}\t{y}\t{w}\t{h}\t95\t{text}\n'
                               for line,x,y,w,h,text in rows)
        self.assertCountEqual(detect_regions(tsv, (1000, 160), categories={'Secrets'}),
                              [(236, 17, 409, 48), (236, 62, 475, 94)])
        self.assertEqual(detect_regions(tsv, (1000, 160), categories=set()), [])

    def test_inline_secret_assignment_spans_the_value_only(self):
        tsv = ('page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '1\t1\t1\t1\t10\t10\t80\t20\t95\tPassword:\n'
               '1\t1\t1\t1\t95\t10\t53\t20\t95\t"""alpha"\n'
               '1\t1\t1\t1\t155\t10\t46\t20\t95\tbeta"\n')
        self.assertCountEqual(detect_regions(tsv, (320, 100), categories={'Secrets'}),
                              [(91, 6, 205, 34)])

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
        with patch('redactor.core.subprocess.run', side_effect=[
            standard, subprocess.TimeoutExpired('ocr', 15),
        ]) as run, patch('redactor.core.detect_regions', return_value=[box]):
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
        learned = (False, set(), 40, '', (('Blocked pattern: CRE', r'\b(?:CRE|DOD)\b'),))
        with patch('rapidocr_backend.recognize_words', return_value=''), \
             patch('rapidocr_backend.recognize_single_label', return_value=('CRE', 95)):
            result = recognize_regions(image, None, learned, area=area)
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

    def test_batch_worker_count_is_bounded_by_jobs_and_limit(self):
        self.assertEqual(batch_worker_count(3, 10, 8), 3)
        self.assertEqual(batch_worker_count(0, 10, 8), 1)
        self.assertEqual(batch_worker_count(99, 4, 8), 4)
        self.assertEqual(batch_worker_count(2, 0, 8), 1)

    def test_parallel_performance_traces_remain_valid_jsonl(self):
        with TemporaryDirectory() as folder, patch('performance_log.log_directory', return_value=Path(folder)):
            run = PerformanceRun('Scanning', 4)
            barrier = Barrier(4)

            def record(index):
                barrier.wait()
                with run.image(index):
                    pass

            threads = [Thread(target=record, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            run.finish()

            events = [json.loads(line) for line in run.path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(sum(event.get('event') == 'image' for event in events), 4)
            self.assertEqual(events[-1]['event'], 'finish')
            self.assertEqual(events[-1]['attempted'], 4)
            self.assertEqual(events[-1]['failed'], 0)

    def test_rapidocr_pool_allows_concurrent_engine_calls(self):
        active = [0]
        peak = [0]
        guard = Lock()
        barrier = Barrier(2)

        class FakeEngine:
            def __call__(self, image, **options):
                with guard:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                barrier.wait()
                with guard:
                    active[0] -= 1
                return SimpleNamespace(boxes=None, txts=None)

        rapidocr_backend._engines = Queue()
        try:
            with patch('rapidocr_backend._create_engine', side_effect=lambda: FakeEngine()):
                threads = [Thread(target=rapidocr_backend.recognize_words,
                                  args=(Image.new('RGB', (20, 20)),)) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
        finally:
            rapidocr_backend._engines = Queue()
        self.assertEqual(peak[0], 2)

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

class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.log_patch = patch('performance_log.log_directory',
                               return_value=Path(self.temporary.name))
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def drain_until(self, runner, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = runner.poll()
            if events is not None and predicate(events):
                return events
            time.sleep(0.005)
        self.fail('runner did not reach the expected state')

    def test_parallel_batch_runs_workers_together_within_the_limit(self):
        runner = JobRunner(limit=2)
        barrier = Barrier(2)
        guard = Lock()
        active = [0]
        peak = [0]
        accepted = []

        def operation(job):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            barrier.wait(5)
            with guard:
                active[0] -= 1
            return job

        self.assertTrue(runner.start('Parallel', [0, 1, 2, 3], operation,
                                     lambda index, result, error: accepted.append(index),
                                     workers=8))
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.finished)
        self.assertEqual(events.completed, 4)
        self.assertEqual(sorted(accepted), [0, 1, 2, 3])
        self.assertEqual(peak[0], 2)

    def test_cancel_stops_queued_work_and_reports_the_remaining_count(self):
        runner = JobRunner(limit=1)
        cancel = Event()
        release = Event()
        started = []

        def operation(job):
            started.append(job)
            release.wait(5)
            return job

        self.assertTrue(runner.start('Cancel', [0, 1, 2], operation,
                                     lambda index, result, error: None, cancel=cancel))
        events = self.drain_until(runner, lambda item: bool(item.started))
        self.assertEqual(events.started, (0,))
        self.assertTrue(runner.cancel())
        self.assertTrue(runner.cancel_pending)
        release.set()
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.finished)
        self.assertEqual(started, [0])
        self.assertTrue(events.summary.canceled)
        text, detail = events.summary.lines()
        self.assertEqual(text, 'Scan canceled · 1/3 processed')
        self.assertIn('2 remaining', detail)

    def test_started_and_result_rows_follow_the_folder_rows(self):
        runner = JobRunner(limit=1)
        gate = Event()
        first, second = Path('a.png'), Path('b.png')

        def operation(job):
            gate.wait(5)
            return job

        self.assertTrue(runner.start('Rows', [first, second], operation,
                                     lambda index, result, error: None,
                                     rows={first: 0, second: 1}))
        events = self.drain_until(runner, lambda item: bool(item.started))
        self.assertEqual(events.started, (0,))
        self.assertEqual(runner.job_rows, [0, 1])
        gate.set()
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertEqual(events.result_rows, (0, 1))

    def test_failures_are_aggregated_through_accept(self):
        runner = JobRunner(limit=1)
        seen = []

        def operation(job):
            if job == 1:
                raise ValueError('broken job')
            return job

        self.assertTrue(runner.start('Failing', [0, 1, 2], operation,
                                     lambda index, result, error: seen.append((index, error)),
                                     workers=1))
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.finished)
        self.assertEqual(events.summary.failures, ('broken job',))
        self.assertEqual(events.summary.completed, 3)
        self.assertIn((1, 'broken job'), seen)
        self.assertEqual(events.summary.lines(),
                         ('Failing finished · 3/3 processed', '2 succeeded · 1 failed'))

    def test_paced_batch_releases_one_image_at_a_time(self):
        runner = JobRunner(limit=1)
        shown = []

        self.assertTrue(runner.start('Paced', [0, 1], lambda job: job,
                                     lambda index, result, error: None,
                                     show_image=shown.append))
        generation = runner.generation
        self.assertTrue(runner.paced)
        self.assertEqual(runner.next_paced(generation), 0)
        self.assertEqual(shown, [0])
        self.assertTrue(runner.release_paced(generation))
        self.drain_until(runner, lambda item: item.completed == 1)
        self.assertEqual(runner.next_paced(generation), 1)
        self.assertEqual(shown, [0, 1])
        self.assertTrue(runner.release_paced(generation))
        self.assertTrue(runner.wait(5))
        self.assertTrue(runner.poll().finished)
        self.assertIsNone(runner.next_paced(generation))

    def test_completed_batch_finishes_the_performance_trace(self):
        runner = JobRunner(limit=1)
        self.assertTrue(runner.start('Trace', [0, 1], lambda job: job,
                                     lambda index, result, error: None,
                                     metrics_settings={'engine': 'Fake'}))
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.summary.trace_available)
        trace_files = list(Path(self.temporary.name).glob('*.jsonl'))
        self.assertEqual(len(trace_files), 1)
        entries = [json.loads(line) for line in
                   trace_files[0].read_text(encoding='utf-8').splitlines()]
        self.assertEqual(entries[0]['operation'], 'Trace')
        self.assertEqual(entries[0]['settings']['parallel_jobs'], 1)
        self.assertEqual(entries[-1]['event'], 'finish')
        self.assertEqual(entries[-1]['attempted'], 2)

    def test_progress_line_names_the_current_image_and_parallel_note(self):
        jobs = [Path('one.png'), Path('two.png')]
        self.assertEqual(progress_line('Scanning', 0, 2, jobs, 1),
                         ('Scanning · 0/2 processed (0%)', 'Current image: one.png'))
        self.assertEqual(progress_line('Scanning', 1, 2, jobs, 2),
                         ('Scanning · 1/2 processed (50%) · 2 parallel',
                          '2 parallel workers'))

    def test_runner_accepts_only_one_batch_at_a_time(self):
        runner = JobRunner(limit=1)
        gate = Event()

        def operation(job):
            gate.wait(5)
            return job

        self.assertTrue(runner.start('First', [0], operation,
                                     lambda index, result, error: None))
        self.assertFalse(runner.start('Second', [1], operation,
                                      lambda index, result, error: None))
        gate.set()
        self.assertTrue(runner.wait(5))
        runner.poll()
        self.assertFalse(runner.busy)
        self.assertFalse(runner.start('Second', [], operation,
                                      lambda index, result, error: None))


if __name__ == '__main__': unittest.main()
