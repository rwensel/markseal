"""Native dialogs for blocked patterns; validation lives in patterns.py."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QVBoxLayout,
)

from . import patterns
from .detection import (
    PATTERN_TYPE_LABELS, value_pattern_expression, value_pattern_types,
)


def _buttons(dialog):
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def prompt_blocked_pattern(text):
    kinds = [('fixed', 'Fixed text (exact)')]
    kinds.extend((kind, PATTERN_TYPE_LABELS[kind]) for kind in value_pattern_types(text))
    selected_kind = 'fixed'
    suggested = value_pattern_expression(text, selected_kind)
    while True:
        dialog = QDialog()
        dialog.setWindowTitle('Block this text')
        dialog.setMinimumWidth(580)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Recognized text'))
        recognized = QPlainTextEdit(text)
        recognized.setReadOnly(True)
        recognized.setMaximumHeight(110)
        layout.addWidget(recognized)
        type_box = None
        if len(kinds) > 1:
            layout.addWidget(QLabel('Match type'))
            type_box = QComboBox()
            for kind, label in kinds:
                type_box.addItem(label, kind)
            type_box.setCurrentIndex(max(0, type_box.findData(selected_kind)))
            layout.addWidget(type_box)
        layout.addWidget(QLabel('Regex pattern (case-insensitive)'))
        field = QLineEdit(suggested)
        field.setSelection(0, len(suggested))
        layout.addWidget(field)
        if type_box is not None:
            def update_type(index):
                nonlocal selected_kind
                selected_kind = type_box.itemData(index) or 'fixed'
                field.setText(value_pattern_expression(text, selected_kind))
            type_box.currentIndexChanged.connect(update_type)
        note_text = 'Enabled patterns are matched locally on future scans. '
        if len(kinds) > 1:
            note_text = ('Fixed text matches only the recognized value; a match type matches any value of that kind. '
                         'Enabled patterns are matched locally on future scans. '
                         'Edit the expression for a narrower range.')
        else:
            note_text += 'Edit the expression if the text varies.'
        note = QLabel(note_text)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(_buttons(dialog))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        pattern = field.text().strip()
        error = patterns.pattern_error(pattern)
        if error is not None:
            QMessageBox.warning(None, 'Empty pattern' if not pattern else 'Invalid pattern',
                                error)
            suggested = pattern
            continue
        return pattern


def prompt_new_pattern():
    label_value = ''
    pattern_value = ''
    while True:
        dialog = QDialog()
        dialog.setWindowTitle('Add blocked pattern')
        dialog.setMinimumWidth(580)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Label (optional)'))
        label_field = QLineEdit(label_value)
        label_field.setPlaceholderText('Manual pattern')
        layout.addWidget(label_field)
        layout.addWidget(QLabel('Regex pattern (case-insensitive)'))
        pattern_field = QLineEdit(pattern_value)
        pattern_field.setPlaceholderText(r'Example: \bsecret-\d+\b')
        pattern_field.setFocus()
        layout.addWidget(pattern_field)
        note = QLabel('Enabled patterns are matched locally on future scans.')
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addWidget(_buttons(dialog))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        label_value = label_field.text().strip()
        pattern_value = pattern_field.text().strip()
        error = patterns.pattern_error(pattern_value)
        if error is not None:
            QMessageBox.warning(None, 'Empty pattern' if not pattern_value else 'Invalid pattern',
                                error)
            continue
        return label_value, pattern_value


def prompt_rename(name):
    dialog = QDialog()
    dialog.setWindowTitle('Rename blocked pattern')
    dialog.setMinimumWidth(520)
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel('Pattern name'))
    field = QLineEdit(name)
    field.setPlaceholderText('Manual pattern')
    field.selectAll()
    field.setFocus()
    layout.addWidget(field)
    note = QLabel('Used in the rule tag for future scans. Leave blank for "Manual pattern".')
    note.setWordWrap(True)
    layout.addWidget(note)
    layout.addWidget(_buttons(dialog))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return field.text().strip()
