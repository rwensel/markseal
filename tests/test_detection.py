"""Pattern detection and provenance rules."""
import unittest

from markseal.detection import CATEGORIES, PRESET_DESCRIPTIONS
from tests.support import (
    BoxList,
    FolderImage,
    Image,
    PRESETS,
    Path,
    Review,
    SimpleNamespace,
    detect_regions,
    pattern_from_text,
    re,
    result_to_tsv,
    value_pattern_expression,
    value_pattern_types,
)


class DetectionTests(unittest.TestCase):
    def test_confidence_patterns_and_word_boundaries(self):
        tsv = ('level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
               '5\t1\t1\t1\t1\t1\t10\t20\t30\t10\t95\tContact\n'
               '5\t1\t1\t1\t1\t2\t50\t20\t100\t10\t92\ta@example.com\n'
               '5\t1\t1\t1\t1\t3\t180\t20\t40\t10\t10\tnoise\n')
        self.assertEqual(detect_regions(tsv, (300,100), categories={'Emails'}, min_confidence=50), [(46,16,154,34)])
        self.assertEqual(detect_regions(tsv, (300,100), categories={'URLs'}, min_confidence=50), [])
        self.assertEqual(len(detect_regions(tsv, (300,100), all_text=True, min_confidence=50)), 2)
        self.assertEqual(detect_regions(tsv, (300,100), categories=set(), custom_pattern='Contact', min_confidence=50), [(6,16,44,34)])

    def test_checksum_validators(self):
        from markseal.detection import iban_ok, luhn_ok
        self.assertTrue(luhn_ok('4111 1111 1111 1111'))
        self.assertFalse(luhn_ok('1234 5678 9012 3456'))
        self.assertTrue(iban_ok('GB82 WEST 1234 5698 7654 32'))
        self.assertFalse(iban_ok('GB82 WEST 1234 5698 7654 31'))

    def test_card_iban_and_ssn_validators_gate_the_boxes(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'

        def found(text, category):
            tsv = header + f'1\t1\t1\t1\t10\t20\t180\t20\t95\t{text}\n'
            return bool(detect_regions(tsv, (400, 100), categories={category}))

        self.assertTrue(found('4111 1111 1111 1111', 'Card numbers'))
        self.assertFalse(found('1234 5678 9012 3456', 'Card numbers'))
        self.assertTrue(found('GB82WEST12345698765432', 'IBANs'))
        self.assertFalse(found('GB82WEST12345698765431', 'IBANs'))
        self.assertTrue(found('123-45-6789', 'SSNs'))

    def test_phone_numbers_require_enough_digits_and_separators(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'

        def found(text):
            tsv = header + f'1\t1\t1\t1\t10\t20\t260\t20\t95\t{text}\n'
            return bool(detect_regions(tsv, (500, 100), categories={'Phone numbers'}))

        for text in ('+1 (415) 555-2671', '415-555-2671', '+44 20 7946 0958'):
            with self.subTest(text=text):
                self.assertTrue(found(text))
        for text in ('2024-01-01', '2024.11.24.10', '123-45-6789', '4111 1111 1111 1111',
                     '192.168.0.1', '1234567890', '000-000-0000'):
            with self.subTest(text=text):
                self.assertFalse(found(text))

    def test_share_preset_leads_with_pii_and_qr(self):
        self.assertIn('Card numbers', PRESETS['Share a screenshot'])
        self.assertIn('Phone numbers', PRESETS['Share a screenshot'])
        self.assertIn('Faces', PRESETS['Share a screenshot'])
        self.assertIn('QR codes', PRESETS['Share a screenshot'])
        self.assertNotIn('Infrastructure', PRESETS['Share a screenshot'])
        self.assertIn('Infrastructure', PRESETS['Work logs & configs'])

    def test_share_preset_includes_personal_fields(self):
        personal = {'Personal names', 'Postal addresses', 'Dates of birth', 'License & ID numbers'}
        self.assertEqual(personal - PRESETS['Share a screenshot'], set())
        self.assertIn('Personal names', PRESETS['Financial details'])
        self.assertIn('Dates of birth', PRESETS['Financial details'])
        self.assertNotIn('License & ID numbers', PRESETS['Financial details'])
        self.assertNotIn('Personal names', PRESETS['Work logs & configs'])
        self.assertNotIn('Personal names', PRESETS['Faces & codes'])
        self.assertEqual(PRESETS['Everything'], set(CATEGORIES))

    def test_personal_detection_runs_only_when_enabled(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv = header + (
            '1\t1\t1\t1\t10\t20\t60\t20\t99\tName:\n'
            '1\t1\t1\t1\t80\t20\t60\t20\t99\tKatie\n'
            '1\t1\t1\t1\t150\t20\t60\t20\t99\tMiller\n')
        self.assertEqual(detect_regions(tsv, (400, 200), categories={'Personal names'},
                                        personal=False), [])
        boxes = detect_regions(tsv, (400, 200), categories={'Personal names'},
                               personal=True)
        self.assertTrue(boxes)

    def test_all_text_skips_personal_detection(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv = header + '1\t1\t1\t1\t10\t20\t60\t20\t99\tKatie\n'
        self.assertEqual(len(detect_regions(tsv, (400, 200), all_text=True, personal=True)), 1)

    def test_preset_sets_and_descriptions_stay_complete(self):
        self.assertEqual(PRESETS['Everything'], set(CATEGORIES))
        self.assertEqual(set(PRESET_DESCRIPTIONS), set(PRESETS))

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

    def test_balanced_detects_infrastructure_and_credentials(self):
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
        found = detect_regions(tsv, (700, 500), categories=PRESETS['Work logs & configs'], min_confidence=50)
        self.assertEqual({(box[1]+4)//30 for box in found}, set(range(1, 7)))
        self.assertIn((396, 176, 554, 204), found)

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

    def test_paths_cover_common_unix_and_windows_roots(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'

        def found(text):
            tsv = header + f'1\t1\t1\t1\t10\t20\t420\t20\t95\t{text}\n'
            return bool(detect_regions(tsv, (500, 100), categories={'Paths'}))

        cases = {
            '/etc/passwd': True, '/etc/nginx': True, '/usr/local/nginx/conf': True,
            '/var/lib/mysql': True, '/opt/app/config.yaml': True, '/srv/app/config.yaml': True,
            '/tmp/upload.bin': True, '/root/.bashrc': True, '/home/alice/.ssh/id_rsa': True,
            '/Users/alice/file': True, 'C:\\path\\file': True, '\\\\server\\share\\file': True,
            'https://example.com/usr/guide': False, 'and/or': False, '2024/10/12': False,
            'see /etc': False,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(found(text), expected)

    def test_unlabeled_street_address_is_matched(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'

        def found(text):
            tsv = header + f'1\t1\t1\t1\t10\t20\t500\t20\t95\t{text}\n'
            return detect_regions(tsv, (600, 100), categories={'Postal addresses'})

        address = found('30 Commercial Road')
        self.assertEqual(len(address), 1)
        self.assertEqual(address[0][0], 6)
        self.assertFalse(found('the 1920 novel Main Street'))
        self.assertFalse(found('2024 was a good year'))
        self.assertTrue(found('Address: 123 Main St'))
        self.assertTrue(found('123 Main Street, Springfield, IL 62704'))

    def test_identifier_wrapped_across_lines_is_matched(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'

        def wrapped(first, second, categories):
            tsv = (header
                   + f'1\t1\t1\t1\t10\t20\t60\t20\t95\t{first}\n'
                   + f'1\t1\t1\t2\t10\t42\t40\t20\t95\t{second}\n')
            return detect_regions(tsv, (300, 120), categories=categories)

        ssn = wrapped('001-01-', '0001', {'SSNs'})
        self.assertEqual(len(ssn), 1)
        self.assertLessEqual(ssn[0][1], 20)
        self.assertGreaterEqual(ssn[0][3], 62)
        self.assertFalse(wrapped('Total', '1234', {'SSNs'}))
        self.assertTrue(wrapped('/etc/', 'passwd', {'Paths'}))

    def test_ticket_id_glued_to_a_lowercase_word_is_matched(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'

        def found(text):
            tsv = header + f'1\t1\t1\t1\t10\t20\t260\t20\t95\t{text}\n'
            return bool(detect_regions(tsv, (400, 100), categories={'Ticket IDs'}))

        self.assertTrue(found("proj-123won't"))
        self.assertTrue(found('PROJ-123'))
        self.assertFalse(found('PROJ-123ABC'))
        self.assertFalse(found('PROJ-1234ABC'))

    def test_wrapped_identifier_skips_a_side_column(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv = (header
               + '1\t1\t1\t1\t10\t20\t50\t20\t95\t001-01-\n'
               + '1\t1\t1\t2\t120\t22\t200\t20\t95\tInvalid area number\n'
               + '1\t1\t1\t3\t10\t42\t40\t20\t95\t0001\n')
        found = detect_regions(tsv, (400, 120), categories={'SSNs'})
        self.assertEqual(len(found), 1)
        self.assertLessEqual(found[0][1], 20)
        self.assertGreaterEqual(found[0][3], 62)

    def test_contained_same_category_boxes_are_merged(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        tsv = (header
               + '1\t1\t1\t1\t10\t20\t80\t20\t95\tAddress:\n'
               + '1\t1\t1\t1\t100\t20\t30\t20\t95\t30\n'
               + '1\t1\t1\t1\t140\t20\t100\t20\t95\tCommercial\n'
               + '1\t1\t1\t1\t250\t20\t50\t20\t95\tRoad\n')
        found = detect_regions(tsv, (400, 100), categories={'Postal addresses'},
                               min_confidence=40, personal=True)
        self.assertEqual(len(found), 1)
        self.assertLessEqual(found[0][0], 96)
        self.assertGreaterEqual(found[0][2], 304)

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

    def test_comma_delimited_runs_keep_regex_matches_tight(self):
        def polygon(left, right):
            return [(left, 12), (right, 12), (right, 27), (left, 27)]

        text = 'Alex Johnson,EID4824,alex@example.com,Exceeds'
        fragments = tuple((character, .99, polygon(left, left + 10))
                          for character, left in zip(text, range(10, 10 + 10 * len(text), 10)))
        result = SimpleNamespace(
            boxes=[polygon(10, 10 + 10 * len(text))], txts=(text,), scores=(.98,),
            word_results=(fragments,),
        )
        start = text.index('alex@example.com')
        end = start + len('alex@example.com')
        rows = result_to_tsv(result, (1000, 120))
        self.assertEqual(
            detect_regions(rows, (1000, 120), False, {'Emails'}, 40),
            [(10 + 10 * start - 4, 8, 10 + 10 * (end + 1) + 5, 32)],
        )

    def test_markdown_emphasis_does_not_hide_the_password_value(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        rows = (('**Temporary', 30, 128), ('Password:**', 166, 124),
                ('Gr33n$prout!2024', 310, 180))
        tsv = header + ''.join(
            f'1\t1\t1\t1\t{left}\t20\t{width}\t24\t95\t{text}\n'
            for text, left, width in rows)
        self.assertEqual(detect_regions(tsv, (600, 100), False, {'Secrets'}, 40),
                         [(306, 16, 494, 48)])

    def test_credential_values_on_the_next_line_are_detected(self):
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        for label, value in (('Wi-Fi Password:', 'WiFiPass2024'),
                             ('Access Code:', 'AC1234'), ('Gate Code:', 'GC5678')):
            with self.subTest(label=label):
                tsv = header + (
                    f'1\t1\t1\t1\t10\t20\t170\t24\t95\t{label}\n'
                    f'1\t1\t1\t2\t12\t48\t120\t24\t95\t{value}\n')
                self.assertEqual(detect_regions(tsv, (400, 100), False, {'Secrets'}, 40),
                                 [(8, 44, 136, 76)])

    def test_detects_sensitive_line_but_not_generic_text(self):
        rows = 'level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t1\t1\t1\t1\t10\t20\t90\t10\t95\tuser@example.com\n5\t1\t1\t1\t2\t1\t10\t50\t50\t10\t95\tDashboard\n'
        self.assertEqual(detect_regions(rows, (200, 100)), [(6, 16, 104, 34)])
        self.assertEqual(len(detect_regions(rows, (200, 100), all_text=True)), 2)
