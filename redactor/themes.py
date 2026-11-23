"""Qt adapter exposing the resolved palette and theme registry to QML."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QFontDatabase

from .theme_tokens import (
    DEFAULT_ID,
    REQUIRED_TOKENS,
    THEME_IDS,
    ThemeSpec,
    contrast_ratio,
    contrast_report,
    is_known,
    mix,
    pick_font,
    relative_luminance,
    resolve,
    spec,
    with_alpha,
)

__all__ = [
    'DEFAULT_ID', 'REQUIRED_TOKENS', 'THEME_IDS', 'ThemeSpec', 'Palette',
    'contrast_ratio', 'contrast_report', 'is_known', 'mix', 'pick_font',
    'relative_luminance', 'resolve', 'spec', 'with_alpha',
]


class Palette(QObject):
    tokensChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_id = DEFAULT_ID
        self._tokens = resolve(DEFAULT_ID)

    def _resolve_fonts(self, tokens):
        available = set(QFontDatabase.families())
        for key, fallback in (('displayFont', 'Segoe UI'), ('bodyFont', 'Sans Serif')):
            stack = [name.strip() for name in str(tokens[key]).split(',')]
            tokens[key] = pick_font(stack, fallback, available)
        return tokens

    @Property('QVariantMap', notify=tokensChanged)
    def tokens(self):
        return self._tokens

    @Property(str, notify=tokensChanged)
    def themeId(self):
        return self._theme_id

    @Slot(str)
    def set_theme(self, theme_id):
        resolved = theme_id if is_known(theme_id) else DEFAULT_ID
        self._theme_id = resolved
        self._tokens = self._resolve_fonts(resolve(resolved))
        self.tokensChanged.emit()
