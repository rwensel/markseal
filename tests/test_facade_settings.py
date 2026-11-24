"""Settings facade: persistence, theme preview, and method resets."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtWidgets import QApplication

from markseal import themes
from markseal.boxset import FolderImage
from markseal.controller import Controller


class SettingsFacadeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.preferences_file = Path(self.temporary.name) / 'settings.json'
        self.controller = Controller(preferences_file=self.preferences_file)
        self.addCleanup(self.controller.deleteLater)
        self.settings = self.controller.settings

    def apply(self, **overrides):
        self.settings.settingsChanged.connect(lambda: None)
        values = {
            'sensitivity': 'Share a screenshot',
            'confidence': 55,
            'all_text': False,
            'enhanced': False,
            'color': False,
            'categories': ['Emails'],
            'method': 'Pixelate',
            'output_directory': '',
            'template': '{stem}_redacted',
            'include_log': True,
            'parallel_images': 1,
            'theme': themes.DEFAULT_ID,
        }
        values.update(overrides)
        return self.settings.applySettings(
            values['sensitivity'], values['confidence'], values['all_text'],
            values['enhanced'], values['color'],
            values['categories'], values['method'], values['output_directory'],
            values['template'], values['include_log'], values['parallel_images'],
            values['theme'],
        )

    def test_facade_exposes_the_settings_surface(self):
        for name in ('categories', 'sensitivity', 'confidence', 'allText',
                     'enhancedOcr', 'colorOcr', 'showRules',
                     'redactionMethod', 'outputDirectory', 'filenameTemplate',
                     'includeLog', 'parallelImages', 'parallelLimit', 'blockedPatterns',
                     'palette', 'themeChoices', 'methodNames',
                     'presetNames', 'presetCategories', 'presetDescriptions', 'categoryNames',
                     'betaChannel'):
            self.assertTrue(hasattr(self.settings, name), name)
        for name in ('applySettings', 'setRedactionMethod', 'requestSettings',
                     'previewThemeById', 'clearThemePreview', 'chooseOutputFolder',
                     'performanceLogsDirectory', 'openPerformanceLogs',
                     'addBlockedPatternManually', 'renameBlockedPattern',
                     'removeBlockedPattern', 'setBlockedPatternEnabled', 'setBetaChannel'):
            self.assertTrue(hasattr(self.settings, name), name)
        self.assertFalse(hasattr(self.controller, 'applySettings'))

    def test_apply_settings_persists_and_validates(self):
        self.assertEqual(self.apply(), '')
        document = json.loads(self.preferences_file.read_text(encoding='utf-8'))
        self.assertEqual(document['confidence'], 55)
        self.assertEqual(document['categories'], ['Emails'])
        self.assertEqual(self.settings.confidence, 55)

        error = self.apply(confidence=500)
        self.assertIn('confidence', error.lower())
        self.assertEqual(self.settings.confidence, 55)

    def test_beta_channel_saves_immediately(self):
        self.settings.setBetaChannel(True)
        self.assertTrue(self.settings.betaChannel)
        document = json.loads(self.preferences_file.read_text(encoding='utf-8'))
        self.assertTrue(document['beta_channel'])
        self.settings.setBetaChannel(False)
        self.assertFalse(self.settings.betaChannel)

    def test_blocked_pattern_saves_immediately(self):
        self.assertTrue(self.settings.addBlockedPattern('Account', r'\bACCT-\d+\b'))
        document = json.loads(self.preferences_file.read_text(encoding='utf-8'))
        self.assertEqual(document['blocked_patterns'][0]['pattern'], r'\bACCT-\d+\b')
        self.assertEqual(len(self.settings.blockedPatterns), 1)
        self.assertFalse(self.settings.addBlockedPattern('Account', r'\bACCT-\d+\b'))

    def test_theme_preview_restores_the_saved_theme(self):
        saved = self.settings.previewTheme
        other = next(theme for theme in themes.THEME_IDS if theme != saved)
        self.settings.previewThemeById(other)
        self.assertEqual(self.settings.previewTheme, other)
        self.assertEqual(self.settings.palette.themeId, other)
        self.settings.clearThemePreview()
        self.assertEqual(self.settings.previewTheme, saved)
        self.assertEqual(self.settings.palette.themeId, saved)

    def test_redaction_method_resets_folder_review_flags(self):
        entries = [FolderImage(Path('one.png')), FolderImage(Path('two.png'))]
        for entry in entries:
            entry.reviewed = True
            entry.saved = True
        self.controller.session.entries = entries
        self.controller.session.active = 0
        self.controller.session.review.confirmed = True

        self.settings.setRedactionMethod('Solid black')

        self.assertEqual(self.settings.redactionMethod, 'Solid black')
        self.assertTrue(all(entry.method == 'Solid black' for entry in entries))
        self.assertTrue(all(not entry.reviewed and not entry.saved for entry in entries))
        self.assertFalse(self.controller.session.review.confirmed)


if __name__ == '__main__':
    unittest.main()
