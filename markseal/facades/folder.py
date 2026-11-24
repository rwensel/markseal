"""The image folder: entries, row selection, model, and row switching."""
from __future__ import annotations

from PIL import Image
from PySide6.QtCore import Property, QObject, Signal, Slot

from .. import boxset, images
from ..ui.models import FolderModel


class FolderFacade(QObject):
    folderChanged = Signal()
    selectionChanged = Signal()
    scrollRequested = Signal(int)

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self._folder_model = FolderModel()

    @Property(bool, notify=folderChanged)
    def folderMode(self):
        return bool(self.session.entries) and self.session.active is not None

    @Property(str, notify=folderChanged)
    def folderName(self):
        return self.session.folder.name if self.session.folder else ''

    @Property(str, notify=folderChanged)
    def folderCounts(self):
        if not self.session.entries:
            return ''
        scanned = sum(entry.scanned for entry in self.session.entries)
        reviewed = sum(entry.reviewed for entry in self.session.entries)
        saved = sum(entry.saved for entry in self.session.entries)
        return (f'{len(self.session.entries)} images · {scanned} scanned · '
                f'{reviewed} reviewed · {saved} saved')

    @Property(int, notify=folderChanged)
    def reviewedCount(self):
        return sum(1 for entry in self.session.entries if entry.reviewed and not entry.saved)

    @Property(int, notify=folderChanged)
    def savedCount(self):
        return sum(1 for entry in self.session.entries if entry.saved)

    @Property(int, notify=folderChanged)
    def folderImageCount(self):
        return len(self.session.entries)

    @Property(QObject, constant=True)
    def folderModel(self):
        return self._folder_model

    def has_entries(self):
        return bool(self.session.entries)

    def rows(self):
        return {entry.path: index for index, entry in enumerate(self.session.entries)}

    def refresh_and_emit(self):
        self._folder_model.refresh()
        self.folderChanged.emit()

    def set_job_states(self, states):
        self._folder_model.set_job_states(states)

    def set_job_state(self, row, state):
        self._folder_model.set_job_state(row, state)

    def clear_job_states(self):
        self._folder_model.clear_job_states()

    def can_leave(self):
        self.session.store_active()
        if not self.session.entries:
            return True
        pending = any(
            not entry.saved and (entry.boxes or entry.reviewed)
            for entry in self.session.entries
        )
        return not pending or self.alerts.ask(
            'Leave folder?', 'Some images have unsaved review work. Leave this folder?'
        )

    def clear(self):
        self.session.entries = []
        self.session.active = None
        self.session.row_selection = set()
        self.session.row_anchor = None
        self._folder_model.set_entries([])
        self.folderChanged.emit()

    def open_path(self, chosen):
        if self.session.jobs.busy or not self.can_leave():
            return
        try:
            paths = sorted(
                (path for path in chosen.iterdir()
                 if path.suffix.lower() in images.IMAGE_SUFFIXES and path.is_file()),
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as error:
            self.alerts.error('Cannot open folder', str(error))
            return
        if not paths:
            self.alerts.info('No images',
                             'Choose a folder containing PNG, JPEG, BMP or TIFF images. '
                             'PDFs open one file at a time.')
            return
        if not self.session.entries and self.session.review.boxes and not self.alerts.ask(
                'Open folder?', 'Discard the current image markings?'):
            return
        self.session.facades.review.cancel_capture()
        self.session.folder = chosen
        self.session.output_directory = (
            self.session.output_directory_override or chosen / 'redacted'
        )
        self.session.entries = [
            boxset.FolderImage(path, method=self.session.preferences.method)
            for path in paths
        ]
        self.session.active = None
        self.session.row_selection = {0}
        self.session.row_anchor = 0
        self._folder_model.set_entries(self.session.entries)
        self._folder_model.set_selection(self.session.row_selection)
        self._folder_model.set_active(0)
        self.session.jobs.reset_progress('Select images to scan, then review each image.')
        self.activate_entry(0)

    def activate_entry(self, index):
        if not 0 <= index < len(self.session.entries) or self.session.active == index:
            return
        review = self.session.facades.review
        review.cancel_capture()
        self.session.store_active()
        self.session.active = index
        entry = self.session.entries[index]
        review.adopt_entry(entry)
        try:
            image, entry.stamp = images.read_folder_image(entry.path, entry.stamp)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            review.set_entry_image(None)
            entry.error = 'Open failed'
            self.alerts.set_status(f'{entry.path.name} · {error}')
        else:
            review.set_entry_image(image)
            self.alerts.set_status(
                f'{entry.path.name} · {entry.status} · {len(entry.selected)} boxes selected'
            )
        self._folder_model.set_active(index)
        self._folder_model.set_selection(self.session.row_selection)
        review.imageChanged.emit()
        review.emit_review()
        review.emit_view()
        self.scrollRequested.emit(index)

    @Slot(int, bool, bool)
    def selectRow(self, index, control, shift):
        if not 0 <= index < len(self.session.entries):
            return
        previous = set(self.session.row_selection)
        if shift and self.session.row_anchor is not None:
            low, high = sorted((self.session.row_anchor, index))
            self.session.row_selection = set(range(low, high + 1))
        elif control:
            if index in self.session.row_selection:
                self.session.row_selection.discard(index)
            else:
                self.session.row_selection.add(index)
            self.session.row_anchor = index
        else:
            self.session.row_selection = {index}
            self.session.row_anchor = index
        self._folder_model.set_selection(self.session.row_selection)
        if self.session.row_selection != previous:
            self.selectionChanged.emit()
        if not self.session.row_selection:
            return
        target = (index if index in self.session.row_selection
                  else min(self.session.row_selection))
        if target != self.session.active:
            self.activate_entry(target)
