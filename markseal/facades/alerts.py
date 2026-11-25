"""Status line, error banner, and native prompts shared by the facades."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox


class Alerts(QObject):
    statusChanged = Signal()
    errorChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status_text = ''
        self.error_text = ''
        self.error_detail = ''
        self.error_action_text = ''
        self.error_action = None

    def set_status(self, text):
        self.status_text = text
        self.statusChanged.emit()

    def ask(self, title, text):
        answer = QMessageBox.question(
            None, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def info(self, title, text):
        QMessageBox.information(None, title, text)

    def error(self, title, text, action_text='', action=None):
        self.error_text = title
        self.error_detail = text
        self.error_action_text = action_text
        self.error_action = action
        self.errorChanged.emit()

    def dismiss(self):
        if not self.error_text and not self.error_detail:
            return
        self.error_text = ''
        self.error_detail = ''
        self.error_action_text = ''
        self.error_action = None
        self.errorChanged.emit()

    def run_action(self):
        action = self.error_action
        self.dismiss()
        if callable(action):
            action()
