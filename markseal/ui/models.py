"""Qt item and image models used by the QML shell."""
from __future__ import annotations

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, Qt
from PySide6.QtQuick import QQuickImageProvider


class DisplayImageProvider(QQuickImageProvider):
    def __init__(self, controller):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._controller = controller

    def requestImage(self, identifier, size, requested_size):
        image = self._controller.display_qimage()
        if size is not None:
            size.setWidth(max(1, image.width()))
            size.setHeight(max(1, image.height()))
        return image

class FolderModel(QAbstractListModel):
    NameRole = Qt.ItemDataRole.UserRole + 1
    StatusRole = NameRole + 1
    ActiveRole = NameRole + 2
    SelectedRole = NameRole + 3
    ReviewedRole = NameRole + 4
    SavedRole = NameRole + 5
    ErrorRole = NameRole + 6
    ScannedRole = NameRole + 7
    PartialRole = NameRole + 8
    JobStateRole = NameRole + 9

    def __init__(self):
        super().__init__()
        self.entries = []
        self.active = None
        self.selection = set()
        self.job_states = {}

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = entries
        self.active = 0 if entries else None
        self.selection = {0} if entries else set()
        self.job_states = {}
        self.endResetModel()

    def rows_inserted(self, count):
        if count > 0:
            start = len(self.entries) - count
            self.beginInsertRows(QModelIndex(), start, start + count - 1)
            self.endInsertRows()

    def set_job_states(self, states):
        if not self.entries:
            return
        self.job_states = {row: state for row, state in states.items() if state}
        self.refresh()

    def set_job_state(self, row, state):
        if row is None:
            return
        if state:
            self.job_states[row] = state
        else:
            self.job_states.pop(row, None)
        if 0 <= row < len(self.entries):
            self.dataChanged.emit(self.index(row), self.index(row))

    def clear_job_states(self):
        if not self.job_states:
            return
        self.job_states = {}
        self.refresh()

    def set_active(self, index):
        self.active = index
        self.refresh()

    def set_selection(self, selection):
        self.selection = set(selection)
        self.refresh()

    def refresh(self):
        if not self.entries:
            return
        self.dataChanged.emit(self.index(0), self.index(len(self.entries) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.entries):
            return None
        row = index.row()
        entry = self.entries[row]
        values = {
            self.NameRole: entry.path.name,
            self.StatusRole: entry.status,
            self.ActiveRole: row == self.active,
            self.SelectedRole: row in self.selection,
            self.ReviewedRole: entry.reviewed,
            self.SavedRole: entry.saved,
            self.ErrorRole: bool(entry.error),
            self.ScannedRole: entry.scanned,
            self.PartialRole: bool(entry.incomplete_ocr),
            self.JobStateRole: self.job_states.get(row, ''),
        }
        return values.get(role)

    def roleNames(self):
        return {
            self.NameRole: b'name',
            self.StatusRole: b'status',
            self.ActiveRole: b'active',
            self.SelectedRole: b'selected',
            self.ReviewedRole: b'reviewed',
            self.SavedRole: b'saved',
            self.ErrorRole: b'hasError',
            self.ScannedRole: b'scanned',
            self.PartialRole: b'partial',
            self.JobStateRole: b'jobState',
        }

def preference_property(name, kind, notify):
    def getter(self):
        return getattr(self.session.preferences, name)

    def setter(self, value):
        if getattr(self.session.preferences, name) != value:
            setattr(self.session.preferences, name, value)
            self.settingsChanged.emit()

    return Property(kind, getter, setter, notify=notify)
