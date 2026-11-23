import unittest
import subprocess
import json
import re
import time
from pathlib import Path
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
    scan_folder_image, text_from_tsv, value_pattern_expression, value_pattern_types,
)
from redactor.review import Review
from redactor.jobs import JobRunner, progress_line
from redactor.boxset import BoxSet, image_status
from redactor.ocr import RapidEngine, TesseractEngine, make_engine
from redactor import preferences
from redactor.preferences import Preferences, PreferencesError
from redactor import patterns
from redactor import themes
from redactor import export
from redactor import core
from redactor.viewport import Viewport
import audit_exports


class FakeEngine:
    def __init__(self, tsv='', outcomes=None):
        self.tsv = tsv
        self.outcomes = list(outcomes) if outcomes is not None else None
        self.calls = []
        self.single_label = False
        self.label = ('', 0.0)

    def recognize(self, image, *, psm=None, cancel=None, timeout=120):
        self.calls.append({'psm': psm, 'timeout': timeout, 'size': image.size})
        if self.outcomes is None:
            return self.tsv
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def read_label(self, crop):
        return self.label

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
        with patch('redactor.ocr.detect_regions', return_value=[]):
            recognize_regions(image, FakeEngine('tsv'), (False,), progress=stages.append)
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
        engine = TesseractEngine('ocr')
        with patch('redactor.ocr.subprocess.run',
                   return_value=SimpleNamespace(stdout=tsv.encode('utf-8'))) as run:
            self.assertEqual(read_area_text(image, engine, (10, 10, 200, 70)),
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
        with patch('ocr_preprocess.small_text_tiles', return_value=[((500, 300, 1100, 700), tile)]):
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

        pool = rapidocr_backend.EnginePool(lambda: FakeEngine())
        with patch('rapidocr_backend._pool', pool):
            threads = [Thread(target=rapidocr_backend.recognize_words,
                              args=(Image.new('RGB', (20, 20)),)) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
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

class ModuleSplitTests(unittest.TestCase):
    def test_public_launcher_reexports_keep_resolving(self):
        import offline_redactor
        for name in ('IMAGE_SUFFIXES', 'PATTERNS', 'PRESETS', 'FolderImage', 'ScanCancelled',
                     'apply_redactions', 'detect_regions', 'find_tesseract', 'new_ocr_boxes',
                     'output_path', 'pixelate', 'preferences_path', 'read_folder_image',
                     'recognize_regions', 'save_export', 'write_folder_copy',
                     'write_preferences'):
            self.assertTrue(hasattr(offline_redactor, name), name)

    def test_each_concept_lives_in_its_sibling_module(self):
        from redactor import detection, images, ocr, redaction
        self.assertIs(detection.detect_regions, core.detect_regions)
        self.assertIs(detection.pattern_from_text, core.pattern_from_text)
        self.assertIs(redaction.pixelate, core.pixelate)
        self.assertIs(redaction.apply_redactions, core.apply_redactions)
        self.assertIs(images.read_folder_image, core.read_folder_image)
        self.assertIs(ocr.recognize_regions, core.recognize_regions)
        self.assertIs(ocr.scan_folder_image, core.scan_folder_image)

    def test_engine_pool_reuses_idle_engines_and_clears_on_close(self):
        created = []

        def create():
            created.append(object())
            return created[-1]

        pool = rapidocr_backend.EnginePool(create)
        first = pool.borrow()
        pool.release(first)
        self.assertIs(pool.borrow(), first)
        self.assertEqual(len(created), 1)
        pool.close()
        second = pool.borrow()
        self.assertIsNot(second, first)
        self.assertEqual(len(created), 2)


class PatternDialogTests(unittest.TestCase):
    def test_pattern_validation_rejects_empty_and_invalid_expressions(self):
        self.assertEqual(patterns.pattern_error('   '), patterns.EMPTY_MESSAGE)
        self.assertIsNotNone(patterns.pattern_error('['))
        self.assertIsNone(patterns.pattern_error(r'\bsecret-\d+\b'))
        self.assertIsNone(patterns.compile_error(r'\bsecret-\d+\b'))
        self.assertIsNotNone(patterns.compile_error('('))

    def test_duplicate_patterns_are_case_insensitive_and_trimmed(self):
        entries = [{'pattern': r'\bToken-\d+\b', 'text': '', 'enabled': True}]
        self.assertTrue(patterns.duplicate_pattern(entries, r'  \bToken-\d+\b  '))
        self.assertFalse(patterns.duplicate_pattern(entries, r'\bother\b'))

    def test_blocked_entry_and_rename_normalize_whitespace(self):
        entry = patterns.blocked_entry('  Token  ', r'  \btoken\b  ')
        self.assertEqual(entry, {'text': 'Token', 'pattern': r'\btoken\b', 'enabled': True})
        self.assertTrue(patterns.rename_entry(entry, '  New name  '))
        self.assertEqual(entry['text'], 'New name')
        self.assertFalse(patterns.rename_entry(entry, 'New name'))


class ViewportTests(unittest.TestCase):
    def test_point_mapping_round_trips_at_the_letterbox_edges(self):
        view = Viewport()
        view.set_view_size(500, 400)
        view.reset((200, 100))
        self.assertAlmostEqual(view.scale, 1.0)
        self.assertAlmostEqual(view.offset_x, 150)
        self.assertAlmostEqual(view.offset_y, 150)
        self.assertEqual(view.image_coordinates(150, 150), (0, 0))
        self.assertEqual(view.image_coordinates(349, 249), (199, 99))
        self.assertEqual(view.image_coordinates(10, 10), (-140, -140))

    def test_zoom_anchors_the_pointer_at_the_same_image_pixel(self):
        view = Viewport()
        view.set_view_size(500, 500)
        view.reset((1000, 1000))
        before = view.image_coordinates(250, 250)
        self.assertTrue(view.zoom_at(250, 250, 1))
        self.assertEqual(view.image_coordinates(250, 250), before)
        self.assertGreater(view.zoom, 1.0)

    def test_drag_boxes_normalize_every_direction_with_exclusive_edges(self):
        view = Viewport()
        view.set_view_size(200, 200)
        view.reset((200, 200))
        expected = (10, 10, 41, 31)
        self.assertEqual(view.drag_box(10, 10, start=(40, 30)), expected)
        self.assertEqual(view.drag_box(40, 30, start=(10, 10)), expected)
        self.assertEqual(view.drag_box(10, 30, start=(40, 10)), expected)
        self.assertEqual(view.drag_box(40, 10, start=(10, 30)), expected)

    def test_drag_rect_tracks_the_pointer_in_view_space(self):
        view = Viewport()
        view.set_view_size(100, 100)
        view.reset((100, 100))
        self.assertTrue(view.begin_drag(20, 30))
        self.assertEqual(view.drag_rect(60, 10), (20, 10, 40, 20))
        self.assertEqual(view.take_drag(), (20, 30))
        self.assertIsNone(view.drag_rect(60, 10))

    def test_capture_region_clamps_to_the_image_at_zoom(self):
        view = Viewport()
        view.set_view_size(200, 200)
        view.reset((100, 100))
        view.zoom_at(100, 100, 1)
        self.assertEqual(view.drag_region(-50, -50, start=(500, 500)), (0, 0, 100, 100))

    def test_hit_testing_uses_the_letterbox_offset(self):
        view = Viewport()
        view.set_view_size(500, 400)
        view.reset((200, 100))
        boxes = [(10, 10, 50, 50)]
        self.assertEqual(view.hit_index(160, 160, boxes), 0)
        self.assertIsNone(view.hit_index(210, 210, boxes))

    def test_pan_only_starts_when_zoomed_and_ends_once(self):
        view = Viewport()
        view.set_view_size(400, 400)
        view.reset((1000, 1000))
        self.assertFalse(view.pan_begin(200, 200))
        view.zoom_at(200, 200, 1)
        self.assertTrue(view.pan_begin(200, 200))
        self.assertTrue(view.pan_move(180, 190))
        self.assertTrue(view.pan_end())
        self.assertFalse(view.pan_end())

    def test_tiny_drag_adds_no_box_and_click_toggles_only_inside(self):
        review = Review()
        review.load(Image.new('RGB', (200, 200)), Path('tiny.png'))
        review.set_view_size(200, 200)
        self.assertEqual(review.release(10, 10), 'none')
        self.assertTrue(review.press(10, 10))
        self.assertEqual(review.release(13, 13), 'none')
        self.assertEqual(review.boxes, [])


class ExportPipelineTests(unittest.TestCase):
    def make_source(self, folder):
        path = Path(folder) / 'source.png'
        image = Image.new('RGB', (120, 80), 'white')
        for x in range(10, 60):
            for y in range(10, 40):
                image.putpixel((x, y), (x * 3 % 256, y * 2 % 256, 90))
        image.save(path)
        return path

    def test_both_export_paths_write_the_same_log_shape(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            with Image.open(source) as handle:
                image = handle.convert('RGB')
            boxes = [(10, 10, 40, 30)]
            file_target = Path(folder) / 'folder.png'
            memory_target = Path(folder) / 'memory.png'
            export.write_copy(export.snapshot(source, file_target, boxes, {0}, 'Pixelate'))
            export.write_copy(export.snapshot(source, memory_target, boxes, {0}, 'Solid black',
                                              image=image))
            file_log = json.loads(file_target.with_suffix('.redactions.json')
                                  .read_text(encoding='utf-8'))
            memory_log = json.loads(memory_target.with_suffix('.redactions.json')
                                    .read_text(encoding='utf-8'))
        self.assertEqual(set(file_log), set(memory_log))
        self.assertEqual(set(file_log), {
            'source_filename', 'output_filename', 'image_dimensions',
            'redaction_rectangles_xyxy', 'created_local_time', 'method', 'note',
        })
        self.assertEqual(file_log['source_filename'], 'source.png')
        self.assertEqual(file_log['output_filename'], 'folder.png')
        self.assertEqual(file_log['redaction_rectangles_xyxy'], [[10, 10, 40, 30]])
        self.assertEqual(memory_log['method'], 'Solid black')
        self.assertEqual(memory_log['note'], export.NOTE)

    def test_pasted_source_adds_the_clipboard_sentence(self):
        log = export.coordinate_log(Path('pasted-image.png'), Path('out.png'), (10, 10),
                                    [], 'Pixelate', pasted=True)
        self.assertTrue(log['note'].endswith(
            'Pasted from the clipboard; no source file exists.'))

    def test_export_refuses_to_overwrite_and_rolls_back_the_sidecar(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            target.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                export.write_copy(export.snapshot(source, target, [], set(), 'Pixelate'))
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(target.with_suffix('.redactions.json').exists())
            self.assertEqual(sorted(path.name for path in Path(folder).iterdir()),
                             ['copy.png', 'source.png'])

    def test_include_log_false_writes_no_sidecar(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            export.write_copy(export.snapshot(source, target, [(10, 10, 40, 30)], {0},
                                              'Solid black'), include_log=False)
            self.assertTrue(target.is_file())
            self.assertFalse(target.with_suffix('.redactions.json').exists())

    def test_export_preserves_pixels_outside_selected_boxes_and_audits(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            export.write_copy(export.snapshot(source, target, [(10, 10, 40, 30)], {0},
                                              'Solid black'))
            with Image.open(source) as handle:
                original = handle.convert('RGB')
            with Image.open(target) as handle:
                exported = handle.convert('RGB')
        exact, _ = audit_exports.audit_export(original, exported, [(10, 10, 40, 30)])
        self.assertTrue(exact)
        self.assertEqual(original.getpixel((70, 60)), exported.getpixel((70, 60)))
        self.assertEqual(exported.getpixel((20, 20)), (0, 0, 0))

    def test_snapshot_freezes_the_entry_state(self):
        job = export.snapshot(Path('source.png'), Path('out.png'), [(1, 1, 5, 5)], {0},
                              'Pixelate')
        self.assertEqual(job.boxes, ((1, 1, 5, 5),))
        self.assertEqual(job.selected, frozenset({0}))
        self.assertEqual(job.selected_boxes, [(1, 1, 5, 5)])

    def test_output_path_names_and_rejects_unsafe_templates(self):
        self.assertEqual(export.output_path(Path('out'), '{stem}-{index}', Path('shot.PNG'), 2),
                         Path('out') / 'shot-2.png')
        with self.assertRaises(ValueError):
            export.output_path(Path('out'), 'bad/name', Path('a.png'), 1)


class PreferencesTests(unittest.TestCase):
    def form(self, **overrides):
        values = {
            'sensitivity': 'Focused',
            'confidence': 50,
            'all_text': False,
            'enhanced_ocr': False,
            'color_ocr': False,
            'ocr_engine': 'Tesseract',
            'categories': list(preferences.defaults().categories),
            'method': 'Pixelate',
            'output_directory': '',
            'filename_template': preferences.DEFAULT_TEMPLATE,
            'include_log': True,
            'parallel_images': 1,
            'theme': themes.DEFAULT_ID,
        }
        values.update(overrides)
        return values

    def test_defaults_match_the_shipped_detection_preset(self):
        defaults = preferences.defaults()
        self.assertEqual(defaults.sensitivity, 'Focused')
        self.assertEqual(defaults.confidence, 50)
        self.assertEqual(set(defaults.categories), PRESETS['Focused'])
        self.assertEqual(defaults.method, 'Pixelate')
        self.assertEqual(defaults.parallel_images, 1)
        self.assertEqual(defaults.blocked_patterns, [])

    def test_document_round_trip_preserves_settings(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            stored = Preferences(
                sensitivity='Balanced', confidence=77, all_text=True, enhanced_ocr=True,
                color_ocr=True, show_rules=True, ocr_engine='RapidOCR',
                method='Solid black', output_directory=folder,
                filename_template='shot-{index}', include_log=False, parallel_images=3,
                categories=('Emails', 'Secrets'),
                blocked_patterns=[{'text': 'Token', 'pattern': r'\btoken-\d+\b',
                                   'enabled': False}],
            )
            preferences.write_preferences(path, stored)
            loaded = preferences.load(path, parallel_limit=8)
        self.assertEqual(loaded.document(), stored.document())

    def test_invalid_settings_are_rejected_before_writing(self):
        current = preferences.defaults()
        for override in ({'confidence': 101}, {'confidence': -1},
                         {'parallel_images': 0}, {'parallel_images': 9},
                         {'output_directory': 'relative/folder'},
                         {'filename_template': '   '}, {'filename_template': 'bad/name'},
                         {'ocr_engine': 'Other'}, {'method': 'Blur'},
                         {'sensitivity': 'Nope'}, {'theme': 'gone'}):
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    preferences.apply_form(current, self.form(**override), 8)

    def test_theme_round_trips_and_unknown_falls_back(self):
        stored = preferences.defaults()
        stored.theme = 'midnight-transit-diagram'
        self.assertEqual(stored.document()['theme'], 'midnight-transit-diagram')
        self.assertEqual(preferences.from_document(stored.document()).theme,
                         'midnight-transit-diagram')
        self.assertEqual(preferences.from_document({}).theme, themes.DEFAULT_ID)
        self.assertEqual(preferences.from_document({'theme': 'gone'}).theme,
                         themes.DEFAULT_ID)

    def test_load_clamps_and_ignores_invalid_saved_values(self):
        loaded = preferences.from_document(
            {'parallel_images': 99, 'confidence': 250, 'redaction_method': 'Blur',
             'ocr_engine': 'Other', 'filename_template': 'bad/name'}, 8)
        self.assertEqual(loaded.parallel_images, 8)
        self.assertEqual(loaded.confidence, 50)
        self.assertEqual(loaded.method, 'Pixelate')
        self.assertEqual(loaded.ocr_engine, 'Tesseract')
        self.assertEqual(loaded.filename_template, preferences.DEFAULT_TEMPLATE)

    def test_legacy_custom_pattern_migrates_once(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({'custom_pattern': r'\bsecret-\d+\b'}),
                            encoding='utf-8')
            first = preferences.load(path)
            preferences.write_preferences(path, first)
            second = preferences.load(path)
        self.assertEqual(first.blocked_patterns,
                         [{'text': 'Imported custom pattern',
                           'pattern': r'\bsecret-\d+\b', 'enabled': True}])
        self.assertEqual(second.blocked_patterns, first.blocked_patterns)

    def test_blocked_patterns_flow_into_scan_configuration_by_enabled_flag(self):
        stored = preferences.defaults()
        stored.blocked_patterns = [
            {'text': 'Token', 'pattern': r'\btoken-\d+\b', 'enabled': True},
            {'text': '', 'pattern': r'\bother\b', 'enabled': False},
        ]
        all_text, categories, confidence, custom, learned = preferences.scan_settings(stored)
        self.assertFalse(all_text)
        self.assertEqual(categories, set(stored.categories))
        self.assertEqual(confidence, 50)
        self.assertEqual(custom, '')
        self.assertEqual(learned, (('Blocked pattern: Token', r'\btoken-\d+\b'),))
        metrics = preferences.scan_metrics(stored)
        self.assertEqual(metrics['blocked_patterns'], 1)
        self.assertEqual(metrics['builtin_category_count'], len(stored.categories))
        self.assertEqual(metrics['engine'], 'Tesseract')

    def test_apply_form_keeps_show_rules_and_blocked_patterns(self):
        current = preferences.defaults()
        current.show_rules = True
        current.blocked_patterns = [{'text': 'X', 'pattern': 'x+', 'enabled': True}]
        updated = preferences.apply_form(current, self.form(), 8)
        self.assertTrue(updated.show_rules)
        self.assertEqual(updated.blocked_patterns, current.blocked_patterns)
        self.assertEqual(updated.categories, preferences.defaults().categories)

    def test_corrupt_settings_raise_and_missing_settings_use_defaults(self):
        with TemporaryDirectory() as folder:
            broken = Path(folder) / 'settings.json'
            broken.write_text('{not json', encoding='utf-8')
            with self.assertRaises(PreferencesError):
                preferences.load(broken)
            missing = preferences.load(Path(folder) / 'missing.json')
        self.assertEqual(missing.document(), preferences.defaults().document())

    def test_enabled_blocked_patterns_are_the_audit_view(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            stored = Preferences(blocked_patterns=[
                {'text': 'A', 'pattern': 'a+', 'enabled': True},
                {'text': 'B', 'pattern': 'b+', 'enabled': False},
                {'text': 'C', 'pattern': 'a+', 'enabled': True},
            ])
            preferences.write_preferences(path, stored)
            self.assertEqual(preferences.enabled_blocked_patterns(path), ('a+',))


class OcrAdapterTests(unittest.TestCase):
    def test_fake_adapter_drives_the_whole_pass_pipeline(self):
        image = Image.new('RGB', (1200, 800), 'white')
        settings = (False, {'Emails'}, 40, '')
        engine = FakeEngine(outcomes=['', ''])
        with patch('ocr_preprocess.strike_reduced_variant', return_value=None), \
             patch('ocr_preprocess.small_text_tiles', return_value=[]), \
             patch('ocr_preprocess.color_ocr_variants', return_value=[]):
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
        with patch('rapidocr_backend.recognize_words', return_value=tsv):
            rapid = recognize_regions(image, RapidEngine(), settings)
        self.assertEqual(tesseract, rapid)
        self.assertEqual(tesseract, [(6, 16, 114, 44)])

    def test_make_engine_validates_the_requested_backend(self):
        self.assertIsInstance(make_engine('Tesseract', executable='ocr'), TesseractEngine)
        with patch('rapidocr_backend.model_files', return_value={}):
            engine = make_engine('RapidOCR')
        self.assertIsInstance(engine, RapidEngine)
        self.assertTrue(engine.single_label)
        with patch('rapidocr_backend.model_files', side_effect=OSError('missing models')):
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


class ReviewSessionTests(unittest.TestCase):
    def test_folder_image_and_review_share_one_box_state(self):
        entry = FolderImage(Path('shared.png'))
        review = Review()
        review.load(Image.new('RGB', (200, 200)), Path('shared.png'))
        review.boxset = entry.boxset
        box = (10, 10, 50, 50)
        review.add_suggestions(BoxList([box], {box: ('Emails',)}))
        self.assertEqual(entry.boxes, [box])
        self.assertEqual(entry.rules[box], ('Emails',))
        self.assertEqual(entry.selected, {0})
        review.selected = set()
        self.assertEqual(entry.selected, set())
        entry.add_shared_boxes([(60, 60, 90, 90)], source='Copied box')
        self.assertEqual(review.boxes[-1], (60, 60, 90, 90))
        self.assertEqual(review.rules[(60, 60, 90, 90)], ('Copied box',))

    def test_toggle_box_updates_selection_and_clears_confirmation(self):
        review = Review()
        review.load(Image.new('RGB', (100, 100)), Path('toggle.png'))
        review.boxes = [(1, 1, 10, 10), (20, 20, 30, 30)]
        review.selected = {0, 1}
        review.confirmed = True
        self.assertTrue(review.toggle_box(0))
        self.assertEqual(review.selected, {1})
        self.assertFalse(review.confirmed)
        self.assertFalse(review.toggle_box(9))

    def test_select_all_and_none_clear_confirmation(self):
        review = Review()
        review.load(Image.new('RGB', (100, 100)), Path('select.png'))
        review.boxes = [(1, 1, 10, 10), (20, 20, 30, 30)]
        review.selected = {0}
        review.confirmed = False
        self.assertTrue(review.select_all())
        self.assertEqual(review.selected, {0, 1})
        self.assertFalse(review.confirmed)
        self.assertFalse(review.select_all())
        review.confirmed = True
        self.assertFalse(review.select_all())
        self.assertEqual(review.selected, {0, 1})
        review.confirmed = False
        self.assertTrue(review.select_none())
        self.assertEqual(review.selected, set())
        self.assertFalse(review.select_none())

    def test_state_survives_switching_between_folder_images(self):
        first = FolderImage(Path('one.png'))
        second = FolderImage(Path('two.png'))
        review = Review()
        review.load(Image.new('RGB', (100, 100)), first.path)
        review.boxset = first.boxset
        review.add_suggestions([(1, 1, 10, 10)])
        review.boxset = second.boxset
        review.add_suggestions([(20, 20, 30, 30)])
        review.boxset = first.boxset
        self.assertEqual(review.boxes, [(1, 1, 10, 10)])
        self.assertEqual(review.selected, {0})
        self.assertEqual(second.boxes, [(20, 20, 30, 30)])
        self.assertEqual(second.selected, {0})

    def test_status_transitions_follow_scan_review_and_save(self):
        entry = FolderImage(Path('status.png'))
        self.assertEqual(entry.status, 'Not scanned')
        entry.add_suggestions([])
        self.assertEqual(entry.status, 'Scanned · review needed')
        entry.add_suggestions([(1, 1, 5, 5)], ['enhanced OCR timed out'])
        self.assertEqual(entry.status, 'Partial scan · review needed')
        entry.reviewed = True
        self.assertEqual(entry.status, 'Reviewed')
        entry.saved = True
        self.assertEqual(entry.status, 'Saved')
        entry.error = 'Open failed'
        self.assertEqual(entry.status, 'Open failed')
        self.assertEqual(image_status(boxes=[(0, 0, 1, 1)]), 'Boxes added · review needed')

    def test_both_merge_paths_prune_nested_boxes_with_one_rule_source(self):
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        entry = FolderImage(Path('nested.png'))
        entry.add_shared_boxes([inner, outer], source='Anchor match')
        self.assertEqual(entry.boxes, [outer])
        self.assertEqual(entry.selected, {0})
        self.assertEqual(entry.rules, {outer: ('Anchor match',)})

        review = Review()
        review.load(Image.new('RGB', (400, 300)), Path('nested.png'))
        review.add_suggestions(BoxList([inner, outer], {inner: ('Secrets',),
                                                         outer: ('Secrets',)}))
        self.assertEqual(review.boxes, [outer])
        self.assertEqual(review.selected, {0})
        self.assertEqual(review.rules, {outer: ('Secrets',)})

    def test_absorbed_box_reports_unchanged_in_both_paths(self):
        outer = (10, 10, 120, 60)
        inner = (20, 20, 60, 40)
        entry = FolderImage(Path('absorbed.png'), boxes=[outer], selected={0})
        self.assertFalse(entry.add_shared_boxes([inner]))
        self.assertEqual(entry.boxes, [outer])

        review = Review()
        review.load(Image.new('RGB', (400, 300)), Path('absorbed.png'))
        review.boxes = [outer]
        review.selected = {0}
        review.confirmed = True
        self.assertEqual(review.add_suggestions([inner]), 0)
        self.assertTrue(review.confirmed)
        self.assertEqual(review.boxes, [outer])

    def test_new_boxes_clear_review_and_save_flags(self):
        entry = FolderImage(Path('flags.png'))
        entry.add_suggestions([(1, 1, 9, 9)])
        entry.reviewed = entry.saved = True
        entry.add_shared_boxes([(20, 20, 30, 30)], source='Anchor match')
        self.assertFalse(entry.reviewed)
        self.assertFalse(entry.saved)
        entry.reviewed = entry.saved = True
        entry.add_suggestions([(40, 40, 50, 50)])
        self.assertFalse(entry.reviewed)
        self.assertFalse(entry.saved)
        self.assertEqual(entry.rules[(20, 20, 30, 30)], ('Anchor match',))

    def test_boxset_remove_and_undo_keep_selection_indices(self):
        state = BoxSet(boxes=[(0, 0, 5, 5), (10, 10, 20, 20), (30, 30, 40, 40)],
                       selected={0, 1, 2})
        self.assertTrue(state.remove(1))
        self.assertEqual(state.selected, {0, 1})
        self.assertEqual(state.selected_boxes(), [(0, 0, 5, 5), (30, 30, 40, 40)])
        self.assertTrue(state.undo())
        self.assertEqual(state.boxes, [(0, 0, 5, 5)])
        self.assertEqual(state.selected, {0})
        self.assertTrue(state.clear())
        self.assertEqual(state.boxes, [])


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


class ThemeTests(unittest.TestCase):
    def test_theme_ids_are_the_six_curated_worlds(self):
        self.assertEqual(themes.THEME_IDS, (
            'split-flap-concourse', 'timetable-slide-rack', 'jet-age-ticket-wallet',
            'centre-rail-reference', 'crouwel-grid-specimen', 'midnight-transit-diagram',
        ))
        self.assertEqual(themes.DEFAULT_ID, 'split-flap-concourse')

    def test_every_theme_resolves_every_required_token(self):
        for theme_id in themes.THEME_IDS:
            tokens = themes.resolve(theme_id)
            self.assertEqual(set(tokens), set(themes.REQUIRED_TOKENS), theme_id)
            for key in ('bg', 'panel', 'amber', 'red', 'dangerText', 'shadow'):
                self.assertRegex(tokens[key], r'^#[0-9a-fA-F]{6,8}$', f'{theme_id}.{key}')
            self.assertTrue(tokens['displayFont'])
            self.assertTrue(tokens['bodyFont'])
            self.assertTrue(tokens['selectedSignalName'])
            self.assertTrue(tokens['excludedSignalName'])

    def test_unknown_theme_falls_back_to_default(self):
        self.assertEqual(themes.resolve('nope'), themes.resolve(themes.DEFAULT_ID))
        self.assertFalse(themes.is_known('nope'))

    def test_contrast_report_is_empty_for_every_theme(self):
        for theme_id in themes.THEME_IDS:
            self.assertEqual(themes.contrast_report(theme_id), [], theme_id)

    def test_signals_are_distinct_for_every_theme(self):
        for theme_id in themes.THEME_IDS:
            tokens = themes.resolve(theme_id)
            selected = themes.relative_luminance(tokens['amber'])
            excluded = themes.relative_luminance(tokens['red'])
            self.assertGreaterEqual(abs(selected - excluded), 0.08, theme_id)

    def test_resolution_is_deterministic(self):
        self.assertEqual(themes.resolve('midnight-transit-diagram'),
                         themes.resolve('midnight-transit-diagram'))


class ThemePaletteTests(unittest.TestCase):
    def test_pick_font_uses_the_first_available_family(self):
        self.assertEqual(
            themes.pick_font(['Missing', 'Second'], 'Fallback', {'Second', 'Fallback'}),
            'Second')
        self.assertEqual(themes.pick_font(['Missing'], 'Fallback', {'Fallback'}), 'Fallback')


if __name__ == '__main__': unittest.main()
