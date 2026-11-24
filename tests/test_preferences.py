"""Settings defaults, persistence, and validation."""
import os
import unittest
from unittest.mock import patch

from tests.support import (
    PRESETS,
    Path,
    Preferences,
    PreferencesError,
    TemporaryDirectory,
    json,
    preferences,
    themes,
)


class PreferencesTests(unittest.TestCase):
    def form(self, **overrides):
        values = {
            'sensitivity': 'Share a screenshot',
            'confidence': 50,
            'all_text': False,
            'enhanced_ocr': False,
            'color_ocr': False,
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
        self.assertEqual(defaults.sensitivity, 'Share a screenshot')
        self.assertEqual(defaults.confidence, 50)
        self.assertEqual(set(defaults.categories), PRESETS['Share a screenshot'])
        self.assertEqual(defaults.method, 'Pixelate')
        self.assertEqual(defaults.parallel_images, 1)
        self.assertEqual(defaults.blocked_patterns, [])
        self.assertFalse(defaults.beta_channel)

    def test_document_round_trip_preserves_settings(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'settings.json'
            stored = Preferences(
                sensitivity='Everything', confidence=77, all_text=True, enhanced_ocr=True,
                color_ocr=True, show_rules=True,
                method='Solid black', output_directory=folder,
                filename_template='shot-{index}', include_log=False, parallel_images=3,
                beta_channel=True,
                categories=('Emails', 'Secrets'),
                blocked_patterns=[{'text': 'Token', 'pattern': r'\btoken-\d+\b',
                                   'enabled': False}],
            )
            preferences.write_preferences(path, stored)
            loaded = preferences.load(path, parallel_limit=8)
        self.assertEqual(loaded.document(), stored.document())

    def test_blur_and_erase_are_valid_methods(self):
        for method in ('Blur', 'Erase'):
            loaded = preferences.from_document({'redaction_method': method})
            self.assertEqual(loaded.method, method)

    def test_apply_form_preserves_update_preferences(self):
        current = preferences.defaults()
        current.check_for_updates = True
        current.download_updates_automatically = True
        current.beta_channel = True
        updated = preferences.apply_form(current, self.form(), 16)
        self.assertTrue(updated.check_for_updates)
        self.assertTrue(updated.download_updates_automatically)
        self.assertTrue(updated.beta_channel)

    def test_legacy_preset_names_load_as_the_new_presets(self):
        for old, new in (('Focused', 'Share a screenshot'),
                         ('Balanced', 'Everything'),
                         ('Broad', 'Everything')):
            with self.subTest(old=old):
                loaded = preferences.from_document({'sensitivity': old})
                self.assertEqual(loaded.sensitivity, new)
                self.assertEqual(set(loaded.categories), PRESETS[new])

    def test_invalid_settings_are_rejected_before_writing(self):
        current = preferences.defaults()
        for override in ({'confidence': 101}, {'confidence': -1},
                         {'parallel_images': 0}, {'parallel_images': 9},
                         {'output_directory': 'relative/folder'},
                         {'filename_template': '   '}, {'filename_template': 'bad/name'},
                         {'method': 'Nope'},
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
            {'parallel_images': 99, 'confidence': 250, 'redaction_method': 'Mosaic',
             'filename_template': 'bad/name'}, 8)
        self.assertEqual(loaded.parallel_images, 8)
        self.assertEqual(loaded.confidence, 50)
        self.assertEqual(loaded.method, 'Pixelate')
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
        self.assertEqual(metrics['engine'], 'RapidOCR')

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

    def test_migrates_legacy_settings_directory(self):
        with TemporaryDirectory() as folder:
            legacy = Path(folder) / 'OfflineScreenshotRedactor' / 'settings.json'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({'confidence': 71}), encoding='utf-8')
            current = Path(folder) / 'Markseal' / 'settings.json'
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                preferences.migrate_legacy_settings()
            self.assertTrue(current.is_file())
            self.assertEqual(json.loads(current.read_text(encoding='utf-8')),
                             {'confidence': 71})
            current.write_text(json.dumps({'confidence': 12}), encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                preferences.migrate_legacy_settings()
            self.assertEqual(json.loads(current.read_text(encoding='utf-8')),
                             {'confidence': 12})

    def test_load_migrates_legacy_settings_at_startup(self):
        with TemporaryDirectory() as folder:
            legacy = Path(folder) / 'OfflineScreenshotRedactor' / 'settings.json'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({'confidence': 71}), encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': folder}):
                loaded = preferences.load(preferences.preferences_path())
            self.assertEqual(loaded.confidence, 71)
