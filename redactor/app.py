"""PySide6 entry point for the Offline Screenshot Redactor."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterSingletonInstance
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .controller import Controller, DisplayImageProvider


def main():
    QQuickStyle.setStyle('Basic')
    app = QApplication(sys.argv)
    app.setApplicationName('Offline Screenshot Redactor')
    app.setOrganizationName('OfflineScreenshotRedactor')
    app.setApplicationDisplayName('Offline Screenshot Redactor')
    controller = Controller()
    qmlRegisterSingletonInstance(Controller, 'Redactor', 1, 0, 'Backend', controller)
    engine = QQmlApplicationEngine()
    engine.addImageProvider('redactor', DisplayImageProvider(controller))
    qml = Path(__file__).resolve().parent / 'qml' / 'Main.qml'
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
