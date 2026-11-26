"""Theme registry, token resolution, and font selection."""
import unittest

from tests.support import (
    themes,
)


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

    def test_hidden_high_contrast_palette_is_valid(self):
        tokens = themes.resolve('high-contrast')
        self.assertEqual(set(tokens), set(themes.REQUIRED_TOKENS))
        self.assertEqual(themes.contrast_report('high-contrast'), [])
        self.assertEqual(tokens['selectedSignalName'], 'yellow')
        self.assertEqual(tokens['excludedSignalName'], 'red')

    def test_contrast_report_is_empty_for_every_theme(self):
        for theme_id in themes.THEME_IDS:
            self.assertEqual(themes.contrast_report(theme_id), [], theme_id)

    def test_signals_are_distinct_for_every_theme(self):
        for theme_id in themes.THEME_IDS:
            tokens = themes.resolve(theme_id)
            selected = themes.relative_luminance(tokens['amber'])
            excluded = themes.relative_luminance(tokens['red'])
            self.assertGreaterEqual(abs(selected - excluded), 0.08, theme_id)

    def test_default_theme_preserves_incumbent_values(self):
        tokens = themes.resolve(themes.DEFAULT_ID)
        expected = {
            'panel': '#15171A', 'panelRaised': '#1D2024', 'inset': '#101215',
            'steelLight': '#A7AAAF', 'mutedText': '#8A9096', 'tile': '#232629',
            'amberFill': '#1AFFB000', 'amberHover': '#FFC24D', 'amberPressed': '#E6A000',
            'toolbarTop': '#1C1F23', 'toolbarBottom': '#121417',
            'sidebarTop': '#191C20', 'sidebarBottom': '#131518',
            'boardTop': '#15181B', 'boardBottom': '#0E1012',
            'viewerTop': '#14171A', 'viewerBottom': '#0B0C0E',
            'rowActive': '#25292E', 'buttonFace': '#15181B',
            'fieldFace': '#0F1114', 'bannerFace': '#1A1418',
            'toolbarDivider': '#34393F', 'toolbarEdge': '#464B51', 'insetBorder': '#050506',
            'shadow': '#000000', 'highlight': '#FFFFFF',
        }
        for key, value in expected.items():
            self.assertEqual(tokens[key], value, key)

    def test_resolution_is_deterministic(self):
        self.assertEqual(themes.resolve('midnight-transit-diagram'),
                         themes.resolve('midnight-transit-diagram'))


class ThemePaletteTests(unittest.TestCase):
    def test_pick_font_uses_the_first_available_family(self):
        self.assertEqual(
            themes.pick_font(['Missing', 'Second'], 'Fallback', {'Second', 'Fallback'}),
            'Second')
        self.assertEqual(themes.pick_font(['Missing'], 'Fallback', {'Fallback'}), 'Fallback')
