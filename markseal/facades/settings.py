"""Preferences, chooser catalogs, palette, and blocked-pattern workflows."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from .. import detection, dialogs, ocr, patterns, preferences, themes
from ..performance_log import log_directory
from ..themes import Palette
from ..ui.models import preference_property

NOTICES_FILENAME = 'THIRD_PARTY_NOTICES.txt'


def third_party_notices_path():
    roots = [Path(__file__).resolve().parents[2],
             Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2])),
             Path(sys.executable).resolve().parent]
    for root in roots:
        candidate = root / NOTICES_FILENAME
        if candidate.is_file():
            return candidate
    return roots[0] / NOTICES_FILENAME


class SettingsFacade(QObject):
    settingsChanged = Signal()
    blockedPatternsChanged = Signal()
    themeChanged = Signal()
    settingsRequested = Signal()

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self._preview_theme = session.preferences.theme
        self._palette = Palette(self)
        self.on_method_changed = None
        self.retry_learn = None

    @Property(str, notify=themeChanged)
    def themeName(self):
        return self.session.preferences.theme

    @Property(str, notify=themeChanged)
    def previewTheme(self):
        return self._preview_theme

    @Property('QVariantList', constant=True)
    def themeChoices(self):
        choices = []
        for theme_id in themes.THEME_IDS:
            entry = themes.spec(theme_id)
            tokens = themes.resolve(theme_id)
            choices.append({
                'id': theme_id,
                'name': entry.name,
                'tagline': entry.tagline,
                'swatches': {
                    'bg': tokens['bg'],
                    'surface': tokens['panel'],
                    'accent': tokens['amber'],
                    'white': tokens['white'],
                    'muted': tokens['mutedText'],
                },
            })
        return choices

    @Property(QObject, constant=True)
    def palette(self):
        return self._palette

    @Property(list, constant=True)
    def categoryNames(self):
        return list(detection.CATEGORIES)

    @Property(list, constant=True)
    def presetNames(self):
        return [*detection.PRESETS, 'Custom']

    @Property(list, constant=True)
    def methodNames(self):
        return list(preferences.METHOD_NAMES)

    @Property(dict, constant=True)
    def presetCategories(self):
        return {name: [category for category in detection.CATEGORIES if category in values]
                for name, values in detection.PRESETS.items()}

    @Property(dict, constant=True)
    def presetDescriptions(self):
        return dict(detection.PRESET_DESCRIPTIONS)

    @Property(list, notify=settingsChanged)
    def categories(self):
        return list(self.session.preferences.categories)

    sensitivity = preference_property('sensitivity', str, settingsChanged)
    confidence = preference_property('confidence', int, settingsChanged)
    allText = preference_property('all_text', bool, settingsChanged)
    enhancedOcr = preference_property('enhanced_ocr', bool, settingsChanged)
    colorOcr = preference_property('color_ocr', bool, settingsChanged)
    showRules = preference_property('show_rules', bool, settingsChanged)

    @Property(str, notify=settingsChanged)
    def redactionMethod(self):
        return self.session.preferences.method

    outputDirectory = preference_property('output_directory', str, settingsChanged)
    filenameTemplate = preference_property('filename_template', str, settingsChanged)
    includeLog = preference_property('include_log', bool, settingsChanged)
    parallelImages = preference_property('parallel_images', int, settingsChanged)

    @Property(int, constant=True)
    def parallelLimit(self):
        return self.session.parallel_limit

    @Property(list, notify=blockedPatternsChanged)
    def blockedPatterns(self):
        return [dict(entry) for entry in self.session.preferences.blocked_patterns]

    def load_preferences(self):
        try:
            self.session.preferences = preferences.load(
                self.session.preference_file, self.session.parallel_limit
            )
        except preferences.PreferencesError as error:
            self.session.preferences = preferences.defaults()
            self.alerts.set_status(str(error))
            return
        self.apply_loaded_preferences()

    def apply_loaded_preferences(self):
        directory = self.session.preferences.output_directory
        path = Path(directory) if directory else None
        self.session.output_directory_override = path
        self.session.output_directory = self.session.output_directory_for(
            self.session.folder)
        self._preview_theme = self.session.preferences.theme
        self._palette.set_theme(self.session.preferences.theme)
        self.themeChanged.emit()

    @Slot(bool)
    def setShowRules(self, enabled):
        enabled = bool(enabled)
        if self.session.preferences.show_rules == enabled:
            return
        self.session.preferences.show_rules = enabled
        self.settingsChanged.emit()
        try:
            preferences.write_preferences(self.session.preference_file, self.session.preferences)
        except OSError as error:
            self.alerts.set_status(
                self.alerts.status_text + f' Settings could not be saved: {error}'
            )
            return
        self.alerts.set_status(
            'Rule tags on. Hover a box or select one to see its tag.'
            if enabled else 'Rule tags off.'
        )

    @Property(bool, notify=settingsChanged)
    def checkForUpdates(self):
        return self.session.preferences.check_for_updates

    @Property(bool, notify=settingsChanged)
    def downloadAutomatically(self):
        return self.session.preferences.download_updates_automatically

    @Slot(bool)
    def setCheckForUpdates(self, enabled):
        self.session.preferences.check_for_updates = bool(enabled)
        self.settingsChanged.emit()
        self._persist_settings()

    @Slot(bool)
    def setDownloadAutomatically(self, enabled):
        self.session.preferences.download_updates_automatically = bool(enabled)
        self.settingsChanged.emit()
        self._persist_settings()

    @Property(bool, notify=settingsChanged)
    def betaChannel(self):
        return self.session.preferences.beta_channel

    @Property(str, constant=True)
    def thirdPartyNotices(self):
        try:
            text = third_party_notices_path().read_text(encoding='utf-8')
        except OSError:
            return 'Third-party notices could not be read.'
        return text.split('\nLICENSE TEXTS\n', 1)[0].strip()

    @Slot()
    def openThirdPartyNotices(self):
        path = third_party_notices_path()
        if not path.is_file():
            self.alerts.set_status('Third-party notices file is missing.')
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @Slot(bool)
    def setBetaChannel(self, enabled):
        enabled = bool(enabled)
        if self.session.preferences.beta_channel == enabled:
            return
        self.session.preferences.beta_channel = enabled
        self.settingsChanged.emit()
        self._persist_settings()
        self.alerts.set_status(
            'Beta channel on. Update checks will offer pre-release builds.'
            if enabled else 'Beta channel off. Update checks use stable releases.')

    def _persist_settings(self):
        try:
            preferences.write_preferences(self.session.preference_file, self.session.preferences)
        except OSError as error:
            self.alerts.set_status(
                self.alerts.status_text + f' Settings could not be saved: {error}'
            )

    @Slot(str)
    def setRedactionMethod(self, method):
        if self.session.jobs.busy or method not in preferences.METHOD_NAMES \
                or method == self.session.preferences.method:
            return
        self.session.preferences.method = method
        self.settingsChanged.emit()
        if self.on_method_changed is not None:
            self.on_method_changed()
        if not self.session.entries:
            updated = ' Preview updated.' if self.session.review.confirmed else ''
            self.alerts.set_status(f'Redaction method set to {method}.{updated}')
        try:
            preferences.write_preferences(self.session.preference_file, self.session.preferences)
        except OSError as error:
            self.alerts.set_status(
                self.alerts.status_text + f' Settings could not be saved: {error}'
            )

    @Slot(str, int, bool, bool, bool, 'QVariantList', str, str, str, bool, int, str, result=str)
    def applySettings(self, sensitivity, confidence, all_text, enhanced, color,
                      categories, method, output_directory, template, include_log,
                      parallel_images, theme):
        try:
            updated = preferences.apply_form(
                self.session.preferences,
                {
                    'sensitivity': sensitivity,
                    'confidence': confidence,
                    'all_text': all_text,
                    'enhanced_ocr': enhanced,
                    'color_ocr': color,
                    'categories': categories,
                    'method': method,
                    'output_directory': output_directory,
                    'filename_template': template,
                    'include_log': include_log,
                    'parallel_images': parallel_images,
                    'theme': theme,
                },
                self.session.parallel_limit,
                source=self.session.entries[0].path if self.session.entries
                else Path('example.png'),
            )
            preferences.write_preferences(self.session.preference_file, updated)
        except (ValueError, re.error, KeyError, IndexError, AttributeError) as error:
            return str(error)
        except OSError as error:
            return f'Could not save settings: {error}'

        method_changed = updated.method != self.session.preferences.method
        self.session.preferences = updated
        self.apply_loaded_preferences()
        self.settingsChanged.emit()
        if method_changed and self.on_method_changed is not None:
            self.on_method_changed()
        return ''

    @Slot()
    def requestSettings(self):
        self._preview_theme = self.session.preferences.theme
        self._palette.set_theme(self.session.preferences.theme)
        self.themeChanged.emit()
        self.settingsRequested.emit()

    @Slot(str)
    def previewThemeById(self, theme_id):
        if not themes.is_known(theme_id) or theme_id == self._preview_theme:
            return
        self._preview_theme = theme_id
        self._palette.set_theme(theme_id)
        self.themeChanged.emit()

    @Slot()
    def clearThemePreview(self):
        saved = self.session.preferences.theme
        if self._preview_theme == saved:
            return
        self._preview_theme = saved
        self._palette.set_theme(saved)
        self.themeChanged.emit()

    @Slot(result=str)
    def chooseOutputFolder(self):
        path = QFileDialog.getExistingDirectory(None, 'Choose output folder')
        return path or ''

    @Slot(result=str)
    def performanceLogsDirectory(self):
        return str(log_directory())

    @Slot()
    def openPerformanceLogs(self):
        directory = log_directory()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                os.startfile(directory)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
        except (AttributeError, OSError):
            self.alerts.info('Performance logs', str(directory))

    @Slot()
    def addBlockedPatternManually(self):
        result = dialogs.prompt_new_pattern()
        if result is None:
            return
        self.addBlockedPattern(*result)

    @Slot(int)
    def renameBlockedPattern(self, index):
        if not 0 <= index < len(self.session.preferences.blocked_patterns):
            return
        entry = self.session.preferences.blocked_patterns[index]
        name = dialogs.prompt_rename(entry.get('text', ''))
        if name is None or not patterns.rename_entry(entry, name):
            return
        self.persist_blocked_patterns()
        self.blockedPatternsChanged.emit()
        self.alerts.set_status('Blocked pattern renamed.')

    def persist_blocked_patterns(self):
        try:
            preferences.write_preferences(
                self.session.preference_file, self.session.preferences
            )
        except OSError as error:
            self.alerts.error('Could not save blocked patterns', str(error))

    def addBlockedPattern(self, text, pattern):
        pattern = pattern.strip()
        if not pattern:
            return False
        error = patterns.compile_error(pattern)
        if error is not None:
            self.alerts.error('Invalid pattern', error)
            return False
        if patterns.duplicate_pattern(self.session.preferences.blocked_patterns, pattern):
            self.alerts.set_status('That pattern is already in the blocked list.')
            return False
        self.session.preferences.blocked_patterns.append(
            patterns.blocked_entry(text, pattern)
        )
        self.persist_blocked_patterns()
        self.blockedPatternsChanged.emit()
        self.alerts.set_status('Blocked pattern added. It applies to the next scan.')
        return True

    @Slot(int)
    def removeBlockedPattern(self, index):
        if 0 <= index < len(self.session.preferences.blocked_patterns):
            del self.session.preferences.blocked_patterns[index]
            self.persist_blocked_patterns()
            self.blockedPatternsChanged.emit()
            self.alerts.set_status('Blocked pattern removed.')

    @Slot(int, bool)
    def setBlockedPatternEnabled(self, index, enabled):
        if 0 <= index < len(self.session.preferences.blocked_patterns):
            self.session.preferences.blocked_patterns[index]['enabled'] = bool(enabled)
            self.persist_blocked_patterns()
            self.blockedPatternsChanged.emit()
            self.alerts.set_status(
                'Blocked pattern enabled.' if enabled else 'Blocked pattern disabled.'
            )

    def learn_pattern(self, area):
        if self.session.review.image is None:
            return
        try:
            engine = self.session.scan_engine()
        except OSError as error:
            self.alerts.error('OCR unavailable', str(error), 'OPEN SETTINGS',
                              self.requestSettings)
            return
        info = {'text': '', 'error': None}

        def operation(job):
            return ocr.read_area_text(self.session.review.image, engine, area)

        def accept(index, result, error):
            if error is not None:
                info['error'] = error
            else:
                info['text'] = result

        def finish():
            if info['error'] is not None:
                return 'Could not read the area'
            return f'{len(info["text"].split())} words read'

        def complete():
            if info['error'] is not None:
                self.alerts.error('Could not read area',
                                  f'Text recognition failed: {info["error"]}',
                                  'TRY AGAIN', self.retry_learn)
                return
            text = info['text'].strip()
            if not text:
                self.alerts.info('No text recognized',
                                 'Draw a tighter box around the text and try again.')
                return
            pattern = dialogs.prompt_blocked_pattern(text)
            if pattern is not None:
                self.addBlockedPattern(text, pattern)

        self.alerts.set_status('Reading the selected text...')
        self.session.jobs.run(
            'Learning pattern', [self.session.review.path], operation, accept, finish,
            complete=complete, report_failures=False,
        )
