"""One owner for the selectable visual themes and their resolved tokens.

The six themes are the curated worlds from ``world-picker.html``. A theme is
seven base values, two font stacks, and the authored signal names; every
other token is derived here so the QML shell has one palette to read.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QFontDatabase

DEFAULT_ID = 'split-flap-concourse'


@dataclass(frozen=True)
class ThemeSpec:
    id: str
    name: str
    tagline: str
    bg: str
    surface: str
    ink: str
    muted: str
    accent: str
    stop: str
    display: str
    body: str
    selected_name: str
    excluded_name: str
    label_tracking: float = 1.1
    label_scale: float = 1.0


_SPECS = {
    'split-flap-concourse': ThemeSpec(
        id='split-flap-concourse',
        name='Split-flap Concourse',
        tagline='Amber signals on a charcoal departure board.',
        bg='#0B0B0D', surface='#141518', ink='#F2F2F2', muted='#585E63',
        accent='#FFB000', stop='#B00020',
        display='Bahnschrift Condensed, Bahnschrift SemiCondensed, Avenir Next Condensed, '
                'Roboto Condensed, DejaVu Sans Condensed, Noto Sans, Segoe UI',
        body='Inter, Segoe UI Variable Text, Segoe UI, Helvetica Neue, Noto Sans, Sans Serif',
        selected_name='amber', excluded_name='red',
        label_tracking=1.1,
    ),
    'timetable-slide-rack': ThemeSpec(
        id='timetable-slide-rack',
        name='Railway Timetable Rack',
        tagline='Goldenrod board with red-pencil marks.',
        bg='#E8AD17', surface='#F6E7B8', ink='#1E1E1E', muted='#6B6B6B',
        accent='#C23A2A', stop='#1E1E1E',
        display='Arial Narrow, Liberation Sans Narrow, Segoe UI',
        body='Segoe UI, Helvetica Neue, Noto Sans, sans-serif',
        selected_name='red', excluded_name='black',
        label_tracking=0.9,
    ),
    'jet-age-ticket-wallet': ThemeSpec(
        id='jet-age-ticket-wallet',
        name='Jet-age Ticket Wallet',
        tagline='Ink-blue itinerary with carbon-red accents.',
        bg='#EAE6DF', surface='#FFFFFF', ink='#0D1B3D', muted='#6B7280',
        accent='#D7263D', stop='#4B2E83',
        display='Arial Narrow, Liberation Sans Narrow, Segoe UI',
        body='Segoe UI, Helvetica Neue, Noto Sans, sans-serif',
        selected_name='red', excluded_name='violet',
        label_tracking=0.9,
    ),
    'centre-rail-reference': ThemeSpec(
        id='centre-rail-reference',
        name='Centre-rail Reference',
        tagline='Ruled paper, serif labels, crimson marks.',
        bg='#EFE8DA', surface='#FAF6EE', ink='#1A1A1A', muted='#6B6B6B',
        accent='#C23A2A', stop='#1A1A1A',
        display='Georgia, Times New Roman, serif',
        body='Georgia, Times New Roman, serif',
        selected_name='crimson', excluded_name='black',
        label_tracking=0.9,
    ),
    'crouwel-grid-specimen': ThemeSpec(
        id='crouwel-grid-specimen',
        name='Crouwel Grid Specimen',
        tagline='Cool grid, blue accent, monospaced labels.',
        bg='#F5F7FA', surface='#FFFFFF', ink='#111111', muted='#8A97A8',
        accent='#0057FF', stop='#111111',
        display='Courier New, Liberation Mono, monospace',
        body='Courier New, Liberation Mono, monospace',
        selected_name='blue', excluded_name='black',
        label_tracking=0.4,
    ),
    'midnight-transit-diagram': ThemeSpec(
        id='midnight-transit-diagram',
        name='Midnight Transit Diagram',
        tagline='Dark network with red and blue signals.',
        bg='#0A0F1E', surface='#0B1230', ink='#FFFFFF', muted='#8A93B0',
        accent='#E21D2D', stop='#5B8CFF',
        display='Segoe UI, Inter, Noto Sans, sans-serif',
        body='Segoe UI, Inter, Noto Sans, sans-serif',
        selected_name='red', excluded_name='blue',
        label_tracking=0.8,
    ),
}

THEME_IDS = tuple(_SPECS)


def is_known(theme_id: str) -> bool:
    return theme_id in _SPECS


def spec(theme_id: str) -> ThemeSpec:
    return _SPECS[theme_id]


def _rgb(color: str) -> tuple[int, int, int]:
    value = color.lstrip('#')
    if len(value) == 8:
        value = value[2:]
    if len(value) != 6:
        raise ValueError(f'Unsupported color: {color}')
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _hex(red: int, green: int, blue: int) -> str:
    return f'#{red:02x}{green:02x}{blue:02x}'


def mix(first: str, second: str, amount: float) -> str:
    a = _rgb(first)
    b = _rgb(second)
    return _hex(*(round(x + (y - x) * amount) for x, y in zip(a, b)))


def with_alpha(color: str, alpha: float) -> str:
    red, green, blue = _rgb(color)
    return f'#{round(alpha * 255):02x}{red:02x}{green:02x}{blue:02x}'


def relative_luminance(color: str) -> float:
    channels = []
    for value in _rgb(color):
        s = value / 255
        channels.append(s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    one = relative_luminance(first)
    two = relative_luminance(second)
    high, low = max(one, two), min(one, two)
    return (high + 0.05) / (low + 0.05)


def _toward_contrast(color: str, background: str) -> str:
    return '#ffffff' if relative_luminance(background) < 0.5 else '#000000'


def _ensure_contrast(color: str, first: str, second: str, target: float) -> str:
    direction = _toward_contrast(color, first)
    for step in range(21):
        candidate = mix(color, direction, step / 20)
        if (contrast_ratio(candidate, first) >= target
                and contrast_ratio(candidate, second) >= target):
            return candidate
    return direction


def _on_accent(accent: str) -> str:
    dark, light = '#0A0A0B', '#FFFFFF'
    if contrast_ratio(dark, accent) >= contrast_ratio(light, accent):
        return dark
    return light


def _shift(color: str, amount: float) -> str:
    return mix(color, _toward_contrast(color, '#000000'), amount)


def _tokens(spec: ThemeSpec) -> dict[str, object]:
    bg, surface, ink = spec.bg, spec.surface, spec.ink
    accent, stop = spec.accent, spec.stop
    panel = surface
    panel_raised = mix(surface, bg, 0.32)
    inset = mix(bg, surface, 0.22)
    steel = mix(spec.muted, bg, 0.55)
    steel_mid = spec.muted
    steel_light = mix(ink, spec.muted, 0.42)
    muted_text = mix(ink, spec.muted, 0.60)
    hairline = mix(spec.muted, bg, 0.35)
    light_surface = relative_luminance(bg) > 0.5
    shadow = mix(ink, bg, 0.5) if light_surface else '#000000'
    highlight = ink if light_surface else '#FFFFFF'
    button_border = mix(spec.muted, bg, 0.50)
    danger_text = _ensure_contrast(stop, panel, bg, 4.5)
    return {
        'bg': bg,
        'panel': panel,
        'panelRaised': panel_raised,
        'inset': inset,
        'steel': steel,
        'steelMid': steel_mid,
        'steelLight': steel_light,
        'hairline': hairline,
        'amber': accent,
        'amberHover': _shift(accent, 0.12),
        'amberPressed': _shift(accent, 0.20),
        'amberBorder': _shift(accent, 0.30),
        'amberFill': with_alpha(accent, 0.05),
        'accentGlow': with_alpha(accent, 0.35),
        'accentSoft': with_alpha(accent, 0.18),
        'red': stop,
        'redFill': with_alpha(stop, 0.08),
        'redBorder': stop,
        'dangerText': danger_text,
        'dangerFace': mix(panel, danger_text, 0.08),
        'dangerBorder': danger_text,
        'white': ink,
        'ink': _on_accent(accent),
        'mutedText': muted_text,
        'tile': mix(panel, ink, 0.05),
        'tileTop': mix(mix(panel, ink, 0.05), ink, 0.06),
        'tileHingeDark': with_alpha('#000000', 0.55),
        'tileHingeLight': with_alpha(ink if light_surface else '#ffffff',
                                     0.08 if light_surface else 0.14),
        'shellTop': mix(bg, ink, 0.04),
        'shellBottom': bg,
        'toolbarTop': mix(panel, ink, 0.06),
        'toolbarBottom': mix(bg, panel, 0.20),
        'sidebarTop': mix(panel, ink, 0.03),
        'sidebarBottom': mix(panel, bg, 0.15),
        'settingsTop': mix(bg, panel, 0.10),
        'settingsBottom': bg,
        'toolbarDivider': mix(button_border, bg, 0.20),
        'toolbarEdge': mix(panel, ink, 0.35),
        'insetBorder': mix(surface, ink, 0.30),
        'boardTop': mix(bg, panel, 0.10),
        'boardBottom': mix(bg, ink, 0.04),
        'rowActive': mix(surface, accent, 0.18),
        'rowSelected': mix(surface, bg, 0.12),
        'rowHover': mix(surface, ink, 0.05),
        'buttonFace': surface,
        'buttonFaceHover': mix(surface, ink, 0.08),
        'buttonFacePressed': mix(surface, bg, 0.15),
        'buttonBorder': button_border,
        'buttonBorderHover': mix(spec.muted, ink, 0.15),
        'ghostHover': mix(surface, ink, 0.06),
        'disabledFace': mix(surface, bg, 0.35),
        'disabledText': muted_text,
        'focusRing': accent,
        'fieldFace': mix(surface, bg, 0.08),
        'fieldBorder': mix(spec.muted, bg, 0.45),
        'fieldHover': mix(surface, ink, 0.10),
        'placeholder': mix(spec.muted, bg, 0.20),
        'tabFace': surface,
        'tabHover': mix(surface, ink, 0.06),
        'tabActiveFace': panel_raised,
        'tabBorder': button_border,
        'bannerFace': mix(bg, stop, 0.08),
        'bannerBorder': mix(stop, bg, 0.25),
        'scrim': with_alpha(bg, 0.85),
        'dropBorder': accent,
        'shadow': shadow,
        'highlight': highlight,
        'viewerTop': mix(panel, bg, 0.25),
        'viewerBottom': mix(bg, surface, 0.05),
        'displayFont': spec.display,
        'bodyFont': spec.body,
        'labelTracking': spec.label_tracking,
        'labelScale': spec.label_scale,
        'selectedSignalName': spec.selected_name,
        'excludedSignalName': spec.excluded_name,
    }


_DEFAULT_OVERRIDES = {
    'bg': '#0B0B0D',
    'panel': '#15171A',
    'panelRaised': '#1D2024',
    'inset': '#101215',
    'steel': '#2A2D31',
    'steelMid': '#585E63',
    'steelLight': '#A7AAAF',
    'hairline': '#3A3E43',
    'amber': '#FFB000',
    'amberHover': '#FFC24D',
    'amberPressed': '#E6A000',
    'amberBorder': '#FFD37A',
    'amberFill': '#1AFFB000',
    'red': '#B00020',
    'redFill': '#14B00020',
    'redBorder': '#B00020',
    'dangerFace': '#171214',
    'dangerBorder': '#B00020',
    'dangerText': '#cd5b70',
    'white': '#F2F2F2',
    'ink': '#0A0A0B',
    'mutedText': '#8A9096',
    'tile': '#232629',
    'tileTop': '#2C3034',
    'tileHingeDark': '#8C000000',
    'tileHingeLight': '#0FFFFFFF',
    'shellTop': '#101215',
    'shellBottom': '#0B0B0D',
    'toolbarTop': '#1C1F23',
    'toolbarBottom': '#121417',
    'sidebarTop': '#191C20',
    'sidebarBottom': '#131518',
    'settingsTop': '#121417',
    'settingsBottom': '#0B0B0D',
    'toolbarDivider': '#34393F',
    'toolbarEdge': '#464B51',
    'insetBorder': '#050506',
    'boardTop': '#15181B',
    'boardBottom': '#0E1012',
    'viewerTop': '#14171A',
    'viewerBottom': '#0B0C0E',
    'rowActive': '#25292E',
    'rowSelected': '#1D2024',
    'rowHover': '#1A1D21',
    'buttonFace': '#15181B',
    'buttonFaceHover': '#2A2E33',
    'buttonFacePressed': '#15181B',
    'buttonBorder': '#3B4046',
    'buttonBorderHover': '#3B4046',
    'ghostHover': '#22262A',
    'disabledFace': '#191C1F',
    'disabledText': '#8A9096',
    'focusRing': '#FFB000',
    'fieldFace': '#0F1114',
    'fieldBorder': '#2A2D31',
    'fieldHover': '#1A1D21',
    'placeholder': '#666C72',
    'tabFace': '#101214',
    'tabHover': '#1A1D21',
    'tabActiveFace': '#262A2F',
    'tabBorder': '#3B4046',
    'bannerFace': '#1A1418',
    'bannerBorder': '#8C1A2E',
    'scrim': '#B0000000',
    'dropBorder': '#FFB000',
    'shadow': '#000000',
    'highlight': '#FFFFFF',
}


REQUIRED_TOKENS = frozenset({
    'bg', 'panel', 'panelRaised', 'inset', 'steel', 'steelMid', 'steelLight', 'hairline',
    'amber', 'amberHover', 'amberPressed', 'amberBorder', 'amberFill', 'accentGlow', 'accentSoft',
    'red', 'redFill', 'redBorder', 'dangerText', 'dangerFace', 'dangerBorder',
    'white', 'ink', 'mutedText', 'tile', 'tileTop', 'tileHingeDark', 'tileHingeLight',
    'shellTop', 'shellBottom', 'toolbarTop', 'toolbarBottom', 'sidebarTop', 'sidebarBottom',
    'settingsTop', 'settingsBottom', 'boardTop', 'boardBottom',
    'rowActive', 'rowSelected', 'rowHover',
    'buttonFace', 'buttonFaceHover', 'buttonFacePressed', 'buttonBorder', 'buttonBorderHover',
    'ghostHover', 'disabledFace', 'disabledText', 'focusRing',
    'fieldFace', 'fieldBorder', 'fieldHover', 'placeholder',
    'tabFace', 'tabHover', 'tabActiveFace', 'tabBorder',
    'bannerFace', 'bannerBorder', 'scrim', 'dropBorder',
    'shadow', 'highlight', 'viewerTop', 'viewerBottom',
    'toolbarDivider', 'toolbarEdge', 'insetBorder',
    'displayFont', 'bodyFont', 'labelTracking', 'labelScale',
    'selectedSignalName', 'excludedSignalName',
})


def resolve(theme_id: str) -> dict[str, object]:
    spec = _SPECS.get(theme_id) or _SPECS[DEFAULT_ID]
    tokens = _tokens(spec)
    if spec.id == DEFAULT_ID:
        tokens.update(_DEFAULT_OVERRIDES)
    if set(tokens) != set(REQUIRED_TOKENS):
        missing = sorted(set(REQUIRED_TOKENS) - set(tokens))
        extra = sorted(set(tokens) - set(REQUIRED_TOKENS))
        raise AssertionError(f'{spec.id}: missing {missing}, extra {extra}')
    return tokens


def contrast_report(theme_id: str) -> list[str]:
    tokens = resolve(theme_id)
    checks = (
        ('white on bg', 'white', 'bg', 4.5),
        ('white on panel', 'white', 'panel', 4.5),
        ('white on panelRaised', 'white', 'panelRaised', 4.5),
        ('mutedText on panel', 'mutedText', 'panel', 3.0),
        ('ink on amber', 'ink', 'amber', 4.5),
        ('dangerText on bg', 'dangerText', 'bg', 4.5),
        ('dangerText on panel', 'dangerText', 'panel', 4.5),
        ('red on white', 'red', '#FFFFFF', 3.0),
        ('red on bg', 'red', 'bg', 2.4),
        ('red on panel', 'red', 'panel', 2.4),
    )
    problems = []
    for label, first, second, target in checks:
        first_value = tokens[first] if first in tokens else first
        second_value = tokens[second] if second in tokens else second
        ratio = contrast_ratio(first_value, second_value)
        if ratio < target:
            problems.append(f'{label}: {ratio:.2f} < {target}')
    delta = abs(relative_luminance(tokens['amber']) - relative_luminance(tokens['red']))
    if delta < 0.08:
        problems.append(f'signal luminance delta: {delta:.3f} < 0.08')
    return problems


def pick_font(candidates, fallback, available):
    for name in candidates:
        if name in available:
            return name
    return fallback


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
