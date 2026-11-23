from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from queue import Queue
from threading import Event

from PIL import Image
from PySide6.QtCore import (
    Property, QAbstractListModel, QBuffer, QIODevice, QModelIndex, QObject, Qt, QTimer, QUrl,
    Signal, Slot,
)
from PySide6.QtGui import QDesktopServices, QFontDatabase, QGuiApplication, QImage
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QVBoxLayout,
)

from performance_log import PerformanceRun, log_directory

from . import core
from .jobs import JobRunner, progress_line
from .review import Review


INITIAL_STATUS = (
    'Click boxes to select or deselect; drag to add. Amber = selected; red = excluded. '
    'Confirm to apply.'
)


def _pick_font(candidates, fallback):
    available = set(QFontDatabase.families())
    for name in candidates:
        if name in available:
            return name
    return fallback


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


def _setting_property(name, kind, notify):
    def getter(self):
        return self._settings[name]

    def setter(self, value):
        if self._settings[name] != value:
            self._settings[name] = value
            self.settingsChanged.emit()

    return Property(kind, getter, setter, notify=notify)


class Controller(QObject):
    statusChanged = Signal()
    imageChanged = Signal()
    imageRevisionChanged = Signal()
    reviewChanged = Signal()
    viewChanged = Signal()
    folderChanged = Signal()
    busyChanged = Signal()
    progressChanged = Signal()
    scanStageChanged = Signal()
    settingsChanged = Signal()
    blockedPatternsChanged = Signal()
    captureChanged = Signal()
    scrollRequested = Signal(int)
    settingsRequested = Signal()

    def __init__(self, preferences_file=None, parent=None):
        super().__init__(parent)
        self.review = Review()
        self.entries = []
        self.active = None
        self.row_selection = set()
        self.row_anchor = None
        self.folder = None
        self.output_directory = None
        self.output_directory_override = None
        self.preferences_file = Path(preferences_file) if preferences_file else core.preferences_path()
        self.parallel_limit = max(1, min(16, os.cpu_count() or 4))
        self._pasted_image = False
        self.filename_template = '{stem}_redacted'
        self.include_log = True
        self.default_method = 'Pixelate'
        self._busy = False
        self.busy_label = ''
        self.capture = 'none'
        self.drag = None
        self._panning = False
        self.status_text = INITIAL_STATUS
        self.progress_text = 'Ready'
        self.progress_value = 0
        self.progress_max = 1
        self.progress_detail = ''
        self.progress_current = ''
        self.scan_stage = ''
        self.image_revision = 0
        self._display_qimage = QImage()
        self._runner = JobRunner(self.parallel_limit)
        self._blocked_patterns = []
        self._folder_model = FolderModel()
        self._settings = {
            'sensitivity': 'Focused',
            'confidence': 50,
            'allText': False,
            'enhancedOcr': False,
            'colorOcr': False,
            'showRules': False,
            'ocrEngine': 'Tesseract',
            'method': 'Pixelate',
            'outputDirectory': '',
            'filenameTemplate': '{stem}_redacted',
            'includeLog': True,
            'parallelImages': 1,
        }
        self._categories = set(core.PRESETS['Focused'])
        self.display_font = _pick_font(
            ['Bahnschrift Condensed', 'Bahnschrift SemiCondensed', 'Avenir Next Condensed',
             'Roboto Condensed', 'DejaVu Sans Condensed', 'Noto Sans'],
            'Segoe UI',
        )
        self.body_font = _pick_font(
            ['Inter', 'Segoe UI Variable Text', 'Segoe UI', 'Helvetica Neue', 'Noto Sans'],
            'Sans Serif',
        )
        self._job_timer = QTimer(self)
        self._job_timer.setInterval(100)
        self._job_timer.timeout.connect(self._poll_jobs)
        self.load_preferences()

    def display_qimage(self):
        return self._display_qimage

    def _set_status(self, text):
        self.status_text = text
        self.statusChanged.emit()

    def _pil_to_qimage(self, image):
        if image.mode != 'RGB':
            image = image.convert('RGB')
        raw = image.tobytes('raw', 'RGB')
        return QImage(
            raw, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
        ).copy()

    def _refresh_display(self):
        image = self.review.image
        if image is not None and self.review.confirmed:
            image = core.apply_redactions(image, self.review.selected_boxes(), self._settings['method'])
        if image is None:
            self._display_qimage = QImage()
        else:
            self._display_qimage = self._pil_to_qimage(image)
        self.image_revision += 1
        self.imageRevisionChanged.emit()

    def _emit_review(self):
        self.reviewChanged.emit()
        self._folder_model.refresh()
        self.folderChanged.emit()

    def _emit_view(self):
        self.viewChanged.emit()

    def _review_status(self):
        name = self.review.path.name if self.review.path else ''
        return (f'{name}: {len(self.review.selected)} selected of '
                f'{len(self.review.boxes)}. Confirm to apply.')

    def _load_image(self, image, path, pasted=False):
        self._pasted_image = pasted
        self.review.load(image, path)
        self._refresh_display()
        self.imageChanged.emit()
        self._emit_review()
        self._emit_view()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self.status_text

    @Property(bool, notify=imageChanged)
    def hasImage(self):
        return self.review.image is not None

    @Property(str, notify=imageChanged)
    def imageName(self):
        if self._pasted_image:
            return 'Pasted image'
        return self.review.path.name if self.review.path else ''

    @Property(str, notify=imageChanged)
    def imageSizeText(self):
        if self.review.image is None:
            return ''
        width, height = self.review.image.size
        return f'{width} × {height}'

    @Property(int, notify=imageRevisionChanged)
    def imageRevision(self):
        return self.image_revision

    @Property(int, notify=imageChanged)
    def imageWidth(self):
        return self.review.image.width if self.review.image else 0

    @Property(int, notify=imageChanged)
    def imageHeight(self):
        return self.review.image.height if self.review.image else 0

    @Property(list, notify=reviewChanged)
    def boxes(self):
        boxes = []
        for index, box in enumerate(self.review.boxes):
            labels = tuple(self.review.rules.get(box, ())) or ('Manual box',)
            label = labels[0] if len(labels) == 1 else f'{labels[0]} +{len(labels) - 1}'
            boxes.append({
                'x1': box[0], 'y1': box[1], 'x2': box[2], 'y2': box[3],
                'selected': index in self.review.selected,
                'rules': list(labels), 'ruleLabel': label,
            })
        return boxes

    @Property(int, notify=reviewChanged)
    def selectedCount(self):
        return len(self.review.selected)

    @Property(int, notify=reviewChanged)
    def excludedCount(self):
        return len(self.review.boxes) - len(self.review.selected)

    @Property(int, notify=reviewChanged)
    def totalBoxes(self):
        return len(self.review.boxes)

    @Property(bool, notify=reviewChanged)
    def confirmed(self):
        return self.review.confirmed

    @Property(float, notify=viewChanged)
    def viewScale(self):
        return self.review.scale

    @Property(float, notify=viewChanged)
    def viewOffsetX(self):
        return self.review.offset_x

    @Property(float, notify=viewChanged)
    def viewOffsetY(self):
        return self.review.offset_y

    @Property(int, notify=viewChanged)
    def zoomPercent(self):
        return round(self.review.zoom * 100)

    @Property(bool, notify=viewChanged)
    def panning(self):
        return self._panning

    @Property(bool, notify=viewChanged)
    def dragActive(self):
        return self.drag is not None

    @Property(float, notify=viewChanged)
    def dragX(self):
        return self.drag[0] if self.drag else 0

    @Property(float, notify=viewChanged)
    def dragY(self):
        return self.drag[1] if self.drag else 0

    @Property(float, notify=viewChanged)
    def dragWidth(self):
        return self.drag[2] if self.drag else 0

    @Property(float, notify=viewChanged)
    def dragHeight(self):
        return self.drag[3] if self.drag else 0

    @Property(str, notify=captureChanged)
    def captureMode(self):
        return self.capture

    @Property(bool, notify=folderChanged)
    def folderMode(self):
        return bool(self.entries) and self.active is not None

    @Property(str, notify=folderChanged)
    def folderName(self):
        return self.folder.name if self.folder else ''

    @Property(str, notify=folderChanged)
    def folderCounts(self):
        if not self.entries:
            return ''
        scanned = sum(entry.scanned for entry in self.entries)
        reviewed = sum(entry.reviewed for entry in self.entries)
        saved = sum(entry.saved for entry in self.entries)
        return (f'{len(self.entries)} images · {scanned} scanned · '
                f'{reviewed} reviewed · {saved} saved')

    @Property(QObject, constant=True)
    def folderModel(self):
        return self._folder_model

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self._busy

    @Property(str, notify=busyChanged)
    def busyLabel(self):
        return self.busy_label

    @Property(bool, notify=busyChanged)
    def canCancel(self):
        return self._runner.can_cancel

    @Property(str, notify=progressChanged)
    def progressText(self):
        return self.progress_text

    @Property(int, notify=progressChanged)
    def progressValue(self):
        return self.progress_value

    @Property(int, notify=progressChanged)
    def progressMax(self):
        return self.progress_max

    @Property(str, notify=progressChanged)
    def progressDetail(self):
        return self.progress_detail

    @Property(str, notify=progressChanged)
    def progressCurrent(self):
        return self.progress_current

    @Property(str, notify=scanStageChanged)
    def scanStage(self):
        return self.scan_stage

    def _set_scan_stage(self, text):
        if self.scan_stage != text:
            self.scan_stage = text
            self.scanStageChanged.emit()

    @Property(str, constant=True)
    def displayFont(self):
        return self.display_font

    @Property(str, constant=True)
    def bodyFont(self):
        return self.body_font

    @Property(list, constant=True)
    def categoryNames(self):
        return list(core.PATTERNS)

    @Property(list, constant=True)
    def presetNames(self):
        return [*core.PRESETS, 'Custom']

    @Property(list, constant=True)
    def engineNames(self):
        return ['Tesseract', 'RapidOCR']

    @Property(list, constant=True)
    def methodNames(self):
        return ['Pixelate', 'Solid black']

    @Property(dict, constant=True)
    def presetCategories(self):
        return {name: [category for category in core.PATTERNS if category in values]
                for name, values in core.PRESETS.items()}

    @Property(list, notify=settingsChanged)
    def categories(self):
        return [name for name in core.PATTERNS if name in self._categories]

    sensitivity = _setting_property('sensitivity', str, settingsChanged)
    confidence = _setting_property('confidence', int, settingsChanged)
    allText = _setting_property('allText', bool, settingsChanged)
    enhancedOcr = _setting_property('enhancedOcr', bool, settingsChanged)
    colorOcr = _setting_property('colorOcr', bool, settingsChanged)
    showRules = _setting_property('showRules', bool, settingsChanged)
    ocrEngine = _setting_property('ocrEngine', str, settingsChanged)

    @Property(str, notify=settingsChanged)
    def redactionMethod(self):
        return self._settings['method']

    outputDirectory = _setting_property('outputDirectory', str, settingsChanged)
    filenameTemplate = _setting_property('filenameTemplate', str, settingsChanged)
    includeLog = _setting_property('includeLog', bool, settingsChanged)
    parallelImages = _setting_property('parallelImages', int, settingsChanged)

    @Property(int, constant=True)
    def parallelLimit(self):
        return self.parallel_limit

    @Property(list, notify=blockedPatternsChanged)
    def blockedPatterns(self):
        return [dict(entry) for entry in self._blocked_patterns]

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            None, 'Open image', '',
            'Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*.*)',
        )
        return Path(path) if path else None

    def _choose_folder(self, title):
        path = QFileDialog.getExistingDirectory(None, title)
        return Path(path) if path else None

    def _ask(self, title, text):
        answer = QMessageBox.question(
            None, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _info(self, title, text):
        QMessageBox.information(None, title, text)

    def _error(self, title, text):
        QMessageBox.critical(None, title, text)

    def _can_leave(self):
        self._store_active()
        if not self.entries:
            return True
        pending = any(not entry.saved and (entry.boxes or entry.reviewed) for entry in self.entries)
        return not pending or self._ask(
            'Leave folder?', 'Some images have unsaved review work. Leave this folder?'
        )

    def _clear_folder(self):
        self.entries = []
        self.active = None
        self.row_selection = set()
        self.row_anchor = None
        self._folder_model.set_entries([])
        self.folderChanged.emit()

    def _prepare_image_open(self):
        if self._busy:
            return False
        if not self._can_leave():
            return False
        if not self.entries and self.review.boxes:
            if not self._ask('Open another image', 'Discard the current unsaved markings?'):
                return False
        return True

    def _present_image(self, image, path, pasted=False):
        self._cancel_capture()
        if self.entries:
            self._clear_folder()
        self._load_image(image, path, pasted=pasted)
        self._set_status(f'{self.imageName}: find suggestions or drag to add a box, then confirm.')

    @Slot()
    def openImage(self):
        if not self._prepare_image_open():
            return
        chosen = self._choose_image()
        if chosen is None:
            return
        try:
            with Image.open(chosen) as source:
                image = source.convert('RGB')
        except Exception as error:
            self._error('Cannot open image', str(error))
            return
        self._present_image(image, chosen)

    @Slot()
    def openFolder(self):
        if self._busy:
            return
        chosen = self._choose_folder('Open image folder')
        if chosen is None:
            return
        self._open_folder_path(chosen)

    def _open_folder_path(self, chosen):
        if self._busy or not self._can_leave():
            return
        try:
            paths = sorted(
                (path for path in chosen.iterdir()
                 if path.suffix.lower() in core.IMAGE_SUFFIXES and path.is_file()),
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as error:
            self._error('Cannot open folder', str(error))
            return
        if not paths:
            self._info('No images', 'Choose a folder containing PNG, JPEG, BMP or TIFF images.')
            return
        if not self.entries and self.review.boxes and not self._ask(
                'Open folder?', 'Discard the current image markings?'):
            return
        self._cancel_capture()
        self.folder = chosen
        self.output_directory = self.output_directory_override or chosen / 'redacted'
        self.entries = [core.FolderImage(path, method=self.default_method) for path in paths]
        self.active = None
        self.row_selection = {0}
        self.row_anchor = 0
        self._folder_model.set_entries(self.entries)
        self._folder_model.set_selection(self.row_selection)
        self._folder_model.set_active(0)
        self.progress_text = 'Ready'
        self.progress_value = 0
        self.progress_max = 1
        self.progress_detail = 'Select images to scan, then review each image.'
        self.progress_current = ''
        self.progressChanged.emit()
        self._show_folder_image(0)

    @Slot('QVariantList')
    def openDropped(self, urls):
        if self._busy:
            return
        paths = []
        for value in urls or []:
            url = value if isinstance(value, QUrl) else QUrl(str(value))
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        images = [path for path in paths
                  if path.is_file() and path.suffix.lower() in core.IMAGE_SUFFIXES]
        if images:
            if not self._prepare_image_open():
                return
            try:
                with Image.open(images[0]) as source:
                    image = source.convert('RGB')
            except Exception as error:
                self._error('Cannot open image', str(error))
                return
            self._present_image(image, images[0])
            return
        folders = [path for path in paths if path.is_dir()]
        if folders:
            self._open_folder_path(folders[0])
            return
        self._info('Drop an image', 'Drop a PNG, JPEG, BMP, TIFF image, or an image folder.')

    def _clipboard_image(self):
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        if data.hasUrls():
            for url in data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_file() and path.suffix.lower() in core.IMAGE_SUFFIXES:
                        with Image.open(path) as source:
                            return source.convert('RGB'), path, False
        if data.hasImage():
            image = clipboard.image()
            if not image.isNull():
                buffer = QBuffer()
                buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                image.save(buffer, 'PNG')
                raw = bytes(buffer.data())
                buffer.close()
                with Image.open(io.BytesIO(raw)) as source:
                    return source.convert('RGB'), Path('pasted-image.png'), True
        return None

    @Slot()
    def pasteImage(self):
        if self._busy:
            return
        try:
            loaded = self._clipboard_image()
        except Exception as error:
            self._error('Cannot paste image', str(error))
            return
        if loaded is None:
            self._info('Paste image', 'The clipboard does not contain an image.')
            return
        if not self._prepare_image_open():
            return
        image, path, pasted = loaded
        self._present_image(image, path, pasted=pasted)

    def _store_active(self):
        if self.active is None or self.review.image is None:
            return
        if not 0 <= self.active < len(self.entries):
            return
        entry = self.entries[self.active]
        if entry.reviewed and not self.review.confirmed:
            entry.saved = False
        entry.reviewed = self.review.confirmed

    def _show_folder_image(self, index):
        if not 0 <= index < len(self.entries) or self.active == index:
            return
        self._cancel_capture()
        self._store_active()
        self.active = index
        entry = self.entries[index]
        self._pasted_image = False
        self.review.path = entry.path
        self.review.boxset = entry.boxset
        self.review.confirmed = entry.reviewed
        self.review.zoom = 1.0
        self.review.offset_x = self.review.offset_y = 0.0
        self.review.start = self.review.pan_start = None
        try:
            image, entry.stamp = core.read_folder_image(entry.path, entry.stamp)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            self.review.image = None
            entry.error = 'Open failed'
            self._set_status(f'{entry.path.name} · {error}')
        else:
            self.review.image = image
            self.review.refit()
            self._refresh_display()
            self._set_status(
                f'{entry.path.name} · {entry.status} · {len(entry.selected)} boxes selected'
            )
        self._folder_model.set_active(index)
        self._folder_model.set_selection(self.row_selection)
        self.imageChanged.emit()
        self._emit_review()
        self._emit_view()
        self.scrollRequested.emit(index)

    @Slot(int, bool, bool)
    def selectRow(self, index, control, shift):
        if not 0 <= index < len(self.entries):
            return
        if shift and self.row_anchor is not None:
            low, high = sorted((self.row_anchor, index))
            self.row_selection = set(range(low, high + 1))
        elif control:
            if index in self.row_selection:
                self.row_selection.discard(index)
            else:
                self.row_selection.add(index)
            self.row_anchor = index
        else:
            self.row_selection = {index}
            self.row_anchor = index
        self._folder_model.set_selection(self.row_selection)
        if not self.row_selection:
            return
        target = index if index in self.row_selection else min(self.row_selection)
        if target != self.active:
            self._show_folder_image(target)

    @Slot(int, int)
    def setViewSize(self, width, height):
        self.review.set_view_size(width, height)
        self._emit_view()

    @Slot(int, int)
    def press(self, x, y):
        if self.capture != 'none' and self.review.image is not None:
            self.review.start = (x, y)
            self.drag = (x, y, 0, 0)
            self._emit_view()
            return
        self.review.press(x, y)

    @Slot(int, int)
    def move(self, x, y):
        if self.review.pan_start is not None:
            if self.review.pan_move(x, y):
                self._emit_view()
            return
        if self.review.start is not None:
            start_x, start_y = self.review.start
            x1, x2 = sorted((start_x, x))
            y1, y2 = sorted((start_y, y))
            self.drag = (x1, y1, x2 - x1, y2 - y1)
            self._emit_view()

    @Slot(int, int)
    def release(self, x, y):
        if self._panning:
            if self.review.pan_end():
                self._panning = False
                self.viewChanged.emit()
            return
        if self.capture != 'none' and self.review.start is not None and self.review.image is not None:
            start_x, start_y = self.review.start
            capture = self.capture
            self._cancel_capture()
            width, height = self.review.image.size
            left, right = sorted((start_x, x))
            top, bottom = sorted((start_y, y))
            anchor = (
                max(0, int((left - self.review.offset_x) / self.review.scale)),
                max(0, int((top - self.review.offset_y) / self.review.scale)),
                min(width, int((right - self.review.offset_x) / self.review.scale)),
                min(height, int((bottom - self.review.offset_y) / self.review.scale)),
            )
            if capture == 'area':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    self._set_status('Area too small. Click Scan area and draw around the text again.')
                elif self.active is None:
                    self._start_single_scan(area=anchor)
                else:
                    self._start_scan([self.entries[self.active]], rescan=True, area=anchor)
            elif capture == 'learn':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    self._set_status('Area too small. Draw a tight box around the text you want to block.')
                else:
                    self._learn_pattern(anchor)
            else:
                self._match_boxes_to_folder(anchor)
            return
        self.drag = None
        action = self.review.release(x, y)
        if action != 'none':
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._set_status(self._review_status())
        self._emit_view()

    @Slot(int, int, int)
    def zoomAt(self, x, y, delta):
        if self.review.zoom_at(x, y, 1 if delta > 0 else -1):
            self._emit_view()

    @Slot(int, int)
    def beginPan(self, x, y):
        if self.review.pan_begin(x, y):
            self._panning = True
            self.viewChanged.emit()

    @Slot(int, int)
    def movePan(self, x, y):
        if self.review.pan_move(x, y):
            self.viewChanged.emit()

    @Slot()
    def endPan(self):
        if self.review.pan_end():
            self._panning = False
            self.viewChanged.emit()

    @Slot(int)
    def removeBox(self, index):
        if self.review.confirmed:
            return
        if self.review.remove_box(index):
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._emit_view()
            self._set_status(
                f'{self.review.path.name}: box removed. '
                f'{len(self.review.selected)} selected of {len(self.review.boxes)}.'
            )

    @Slot()
    def undo(self):
        if self.review.undo():
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._emit_view()
        if self.review.image is not None:
            self._set_status(self._review_status())

    @Slot()
    def editBoxes(self):
        if self.review.image is None or not self.review.confirmed:
            return
        self.review.confirmed = False
        self._refresh_display()
        self._store_active()
        self._emit_review()
        self._set_status('Click an X to remove a box. Confirm selection when ready.')

    @Slot()
    def clearBoxes(self):
        if not self.review.boxes:
            return
        if not self._ask('Clear boxes', 'Remove all suggested and manually drawn boxes?'):
            return
        self.review.clear()
        self._refresh_display()
        self._store_active()
        self._emit_review()
        self._emit_view()
        self._set_status('Boxes cleared. Scan again or drag to add an area.')

    @Slot()
    def confirmSelection(self):
        if self._busy or self.review.image is None:
            return
        selected = sorted(self.row_selection) if self.entries else ()
        if len(selected) > 1:
            self._confirm_entries([self.entries[index] for index in selected], 'Confirm selected images')
        else:
            self.review.confirmed = True
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._set_status(
                f'{len(self.review.selected)} areas applied in preview. '
                'Save, or click to change your selection.'
            )

    @Slot()
    def cancelCapture(self):
        if self.capture != 'none':
            self._cancel_capture()
            self._set_status('Area selection canceled.')

    def _cancel_capture(self):
        if self.capture != 'none' or self.drag is not None:
            self.capture = 'none'
            self.drag = None
            self.review.start = None
            self.captureChanged.emit()
            self._emit_view()

    def _scan_engine(self):
        return core.make_engine(self._settings['ocrEngine'])

    def _scan_settings(self):
        confidence = self._settings['confidence']
        if not 0 <= confidence <= 100:
            raise ValueError('OCR confidence must be between 0 and 100.')
        learned = tuple(
            (f'Blocked pattern: {entry["text"]}' if entry['text'] else 'Blocked pattern',
             entry['pattern'])
            for entry in self._blocked_patterns if entry['enabled']
        )
        return self._settings['allText'], set(self._categories), confidence, '', learned

    def _scan_metrics(self):
        return {
            'engine': self._settings['ocrEngine'],
            'confidence': self._settings['confidence'],
            'enhanced': self._settings['enhancedOcr'],
            'color_assisted': self._settings['colorOcr'],
            'sensitivity': self._settings['sensitivity'],
            'builtin_category_count': len(self._categories),
            'blocked_patterns': sum(1 for entry in self._blocked_patterns if entry['enabled']),
            'all_text': self._settings['allText'],
        }

    @Slot()
    def find(self):
        if self._busy or self.review.image is None:
            return
        if self.active is not None:
            self._start_scan([self.entries[self.active]], rescan=True)
            return
        self._start_single_scan()

    def _start_single_scan(self, area=None):
        if self.review.image is None or self._busy:
            return
        try:
            engine = self._scan_engine()
            settings = self._scan_settings()
        except OSError as error:
            self._error('OCR unavailable', str(error))
            return
        except (ValueError, re.error) as error:
            self._error('Invalid detection settings', str(error))
            return
        stages = Queue()
        info = {'added': None, 'incomplete': [], 'error': None}
        label = 'Scanning area' if area is not None else 'Scanning image'

        def operation(job):
            incomplete = []
            found = core.recognize_regions(
                self.review.image, engine, settings, self._settings['enhancedOcr'],
                color_assisted=self._settings['colorOcr'], incomplete=incomplete,
                area=area, progress=stages.put,
            )
            return None, found, incomplete

        def accept(index, result, error):
            if error is not None:
                info['error'] = error
                self._set_status(f'Scan failed: {error}')
                return
            _, found, incomplete = result
            added = self.review.add_suggestions(found)
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._emit_view()
            info['added'] = added
            info['incomplete'] = incomplete
            detail = f' Incomplete OCR passes: {", ".join(incomplete)}.' if incomplete else ''
            self._set_status(
                f'{added} selected suggestions added.{detail} Review the entire image.'
            )

        def finish():
            if info['error'] is not None:
                return 'Scan failed'
            return f'{info["added"] or 0} new OCR suggestions'

        def complete():
            if info['error'] is not None:
                self._error('Local OCR failed', f'Text recognition failed: {info["error"]}')
                return
            if info['added'] is None:
                return
            detail = (f' Incomplete OCR passes: {", ".join(info["incomplete"])}.'
                      if info['incomplete'] else '')
            self._info(
                'Review required',
                f'Added {info["added"]} selected boxes.{detail} Review the image before confirming.',
            )

        self._set_status(
            'Scanning the selected area. Progress is shown above the screenshot.' if area is not None
            else 'Scanning image. Progress is shown above the screenshot.'
        )
        self._run_jobs(
            label, [self.review.path], operation, accept, finish,
            metrics_settings=self._scan_metrics(), stage_queue=stages,
            complete=complete, report_failures=False,
        )

    @Slot()
    def beginScanArea(self):
        if self._busy or self.review.image is None:
            return
        self._cancel_capture()
        self.capture = 'area'
        self.captureChanged.emit()
        self._set_status(
            'Drag around the text to scan. For small labels, draw a tight box around a single row. Esc cancels.'
        )

    @Slot()
    def beginAnchorCapture(self):
        if self._busy or self.active is None or self.review.image is None:
            return
        if not self.review.selected or len(self.entries) < 2:
            self._info(
                'Match by visual anchor',
                'Select redaction boxes on one image in a folder with at least two images.',
            )
            return
        self._cancel_capture()
        self.editBoxes()
        self.capture = 'anchor'
        self.captureChanged.emit()
        self._set_status('Drag around a distinctive logo or label near the boxes. Esc cancels.')

    @Slot()
    def beginLearnPattern(self):
        if self._busy or self.review.image is None:
            return
        self._cancel_capture()
        self.capture = 'learn'
        self.captureChanged.emit()
        self._set_status(
            'Drag around the text to block. The area is read locally and turned into a pattern. Esc cancels.'
        )

    def _learn_pattern(self, area):
        if self.review.image is None:
            return
        try:
            engine = self._scan_engine()
        except OSError as error:
            self._error('OCR unavailable', str(error))
            return
        info = {'text': '', 'error': None}

        def operation(job):
            return core.read_area_text(self.review.image, engine, area)

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
                self._error('Could not read area', f'Text recognition failed: {info["error"]}')
                return
            text = info['text'].strip()
            if not text:
                self._info('No text recognized', 'Draw a tighter box around the text and try again.')
                return
            pattern = self._prompt_blocked_pattern(text)
            if pattern is not None:
                self.addBlockedPattern(text, pattern)

        self._set_status('Reading the selected text...')
        self._run_jobs('Learning pattern', [self.review.path], operation, accept, finish,
                       complete=complete, report_failures=False)

    def _prompt_blocked_pattern(self, text):
        kinds = [('fixed', 'Fixed text (exact)')]
        kinds.extend((kind, core.PATTERN_TYPE_LABELS[kind])
                     for kind in core.value_pattern_types(text))
        selected_kind = 'fixed'
        suggested = core.value_pattern_expression(text, selected_kind)
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
                    field.setText(core.value_pattern_expression(text, selected_kind))
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
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            pattern = field.text().strip()
            if not pattern:
                QMessageBox.warning(None, 'Empty pattern', 'Enter a pattern or cancel.')
                suggested = pattern
                continue
            try:
                re.compile(pattern)
            except re.error as error:
                QMessageBox.warning(None, 'Invalid pattern', str(error))
                suggested = pattern
                continue
            return pattern

    @Slot()
    def addBlockedPatternManually(self):
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
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            label_value = label_field.text().strip()
            pattern_value = pattern_field.text().strip()
            if not pattern_value:
                QMessageBox.warning(None, 'Empty pattern', 'Enter a pattern or cancel.')
                continue
            try:
                re.compile(pattern_value)
            except re.error as error:
                QMessageBox.warning(None, 'Invalid pattern', str(error))
                continue
            self.addBlockedPattern(label_value, pattern_value)
            return

    @Slot(int)
    def renameBlockedPattern(self, index):
        if not 0 <= index < len(self._blocked_patterns):
            return
        entry = self._blocked_patterns[index]
        dialog = QDialog()
        dialog.setWindowTitle('Rename blocked pattern')
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('Pattern name'))
        field = QLineEdit(entry.get('text', ''))
        field.setPlaceholderText('Manual pattern')
        field.selectAll()
        field.setFocus()
        layout.addWidget(field)
        note = QLabel('Used in the rule label for future scans. Leave blank for "Manual pattern".')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = field.text().strip()
        if name == entry.get('text', ''):
            return
        entry['text'] = name
        self._persist_blocked_patterns()
        self.blockedPatternsChanged.emit()
        self._set_status('Blocked pattern renamed.')

    def _persist_blocked_patterns(self):
        try:
            core.write_preferences(self.preferences_file, self._preference_document())
        except OSError as error:
            self._error('Could not save blocked patterns', str(error))

    def addBlockedPattern(self, text, pattern):
        pattern = pattern.strip()
        if not pattern:
            return False
        try:
            re.compile(pattern)
        except re.error as error:
            self._error('Invalid pattern', str(error))
            return False
        if any(entry['pattern'].casefold() == pattern.casefold()
               for entry in self._blocked_patterns):
            self._set_status('That pattern is already in the blocked list.')
            return False
        self._blocked_patterns.append({'text': text.strip(), 'pattern': pattern, 'enabled': True})
        self._persist_blocked_patterns()
        self.blockedPatternsChanged.emit()
        self._set_status('Blocked pattern added. It applies to the next scan.')
        return True

    @Slot(int)
    def removeBlockedPattern(self, index):
        if 0 <= index < len(self._blocked_patterns):
            del self._blocked_patterns[index]
            self._persist_blocked_patterns()
            self.blockedPatternsChanged.emit()
            self._set_status('Blocked pattern removed.')

    @Slot(int, bool)
    def setBlockedPatternEnabled(self, index, enabled):
        if 0 <= index < len(self._blocked_patterns):
            self._blocked_patterns[index]['enabled'] = bool(enabled)
            self._persist_blocked_patterns()
            self.blockedPatternsChanged.emit()
            self._set_status('Blocked pattern enabled.' if enabled else 'Blocked pattern disabled.')

    @Slot()
    def scanAll(self):
        self._start_scan(self.entries, follow=True)

    @Slot()
    def scanSelected(self):
        if self._busy:
            return
        selected = sorted(self.row_selection)
        if not selected:
            self._info('Scan selected', 'Select one or more images in the folder list first.')
            return
        self._start_scan([self.entries[index] for index in selected], rescan=True, follow=True)

    @Slot()
    def rescanAll(self):
        if not self._busy and self.entries and self._ask(
                'Rescan all images?',
                'Keep existing boxes and add new suggestions. All rescanned images will need review again.'):
            self._start_scan(self.entries, rescan=True, follow=True)

    def _start_scan(self, entries, rescan=False, *, follow=False, area=None):
        if self._busy:
            return
        self._store_active()
        pending = [entry for entry in entries if rescan or not (entry.scanned or entry.reviewed)]
        if not pending:
            self._info(
                'Folder scan',
                'Every image has been scanned or manually reviewed. '
                'Use Find likely identifiers to rescan an image.',
            )
            return
        try:
            engine = self._scan_engine()
            settings = self._scan_settings()
        except OSError as error:
            self._error('OCR unavailable', str(error))
            return
        except (ValueError, re.error) as error:
            self._error('Invalid detection settings', str(error))
            return
        cancel = Event()
        rows = {entry.path: index for index, entry in enumerate(self.entries)}
        enhanced = self._settings['enhancedOcr']
        color_assisted = self._settings['colorOcr']
        processed = []
        area_completed = False

        def show_image(index):
            row = rows[pending[index].path]
            self._show_folder_image(int(row))

        def operation(job):
            path, stamp = job
            return core.scan_folder_image(
                path, stamp, engine, settings, enhanced, cancel,
                color_assisted=color_assisted, area=area,
            )

        def accept(index, result, error):
            nonlocal area_completed
            entry = pending[index]
            if error:
                if area is None:
                    entry.error = 'Scan failed'
                self._set_status(f'{entry.path.name} · {error}')
                return
            stamp, found, incomplete = result
            if entry.stamp is not None and entry.stamp != stamp:
                entry.error = 'Source changed'
                return
            area_completed = area is not None
            entry.stamp = stamp
            if area is None:
                count = entry.add_suggestions(found, incomplete)
                changed = True
            else:
                added = core.new_ocr_boxes(found, entry.boxes)
                count = len(added)
                changed = entry.add_shared_boxes(added, found.rules, source='Area OCR')
            if self.active is not None and entry is self.entries[self.active] and self.review.image is not None:
                if changed:
                    self.review.confirmed = False
                    self._refresh_display()
                    self._emit_review()
                    self._emit_view()
                detail = f' Partial scan: {", ".join(incomplete)}.' if incomplete else ''
                self._set_status(
                    f'{entry.path.name} · {count} new OCR suggestions.{detail} Review before confirming.'
                )

        def track_result(index, result, error):
            accept(index, result, error)
            processed.append(pending[index])

        def finish():
            if area is not None:
                return ('Area scan finished · review suggested boxes'
                        if processed and area_completed else 'No area results')
            complete = sum(entry.scanned and not entry.incomplete_ocr and not entry.error
                           for entry in processed)
            partial = sum(bool(entry.incomplete_ocr) and not entry.error for entry in processed)
            return f'{complete} succeeded' + (f' · {partial} partial' if partial else '')

        self._run_jobs(
            'Scanning area' if area is not None else 'Scanning',
            [(entry.path, entry.stamp) for entry in pending],
            operation, track_result, finish,
            cancel=cancel, show_image=show_image if follow else None,
            metrics_settings=self._scan_metrics(), rows=self._folder_rows(),
        )

    @Slot()
    def cancelScan(self):
        if self._runner.cancel():
            self.progress_text = 'Canceling scan…'
            self.progressChanged.emit()

    def _show_progress(self, label, completed, total, jobs, workers=1):
        text, current = progress_line(label, completed, total, jobs, workers)
        self.progress_max = total
        self.progress_value = completed
        self.progress_text = text
        if current:
            self.progress_current = current
        self.progressChanged.emit()

    def _folder_rows(self):
        return {entry.path: index for index, entry in enumerate(self.entries)}

    def _run_jobs(self, label, jobs, operation, accept, finish=None, *, cancel=None,
                  show_image=None, metrics_settings=None, rows=None, workers=None,
                  stage_queue=None, complete=None, report_failures=True):
        if not jobs or self._busy:
            return
        self._cancel_capture()
        requested = self._settings['parallelImages'] if workers is None else workers
        if not self._runner.start(
                label, jobs, operation, accept, finish,
                cancel=cancel, show_image=show_image, metrics_settings=metrics_settings,
                rows=rows, workers=requested, stage_queue=stage_queue,
                complete=complete, report_failures=report_failures):
            return
        runner = self._runner
        self._busy = True
        self.busy_label = label
        self.progress_max = runner.total
        self.progress_value = 0
        self.progress_detail = ''
        self.progress_current = ''
        self._set_scan_stage('')
        self._folder_model.set_job_states(
            {row: 'queued' for row in runner.job_rows if row is not None}
        )
        self.busyChanged.emit()
        self.progressChanged.emit()
        if not runner.paced:
            self._show_progress(label, 0, runner.total, runner.jobs, runner.workers)
        self._job_timer.start()
        if runner.paced:
            self._show_next_if_current(runner.generation)

    def _show_next_if_current(self, generation):
        runner = self._runner
        if runner.next_paced(generation) is None:
            return
        self._show_progress(runner.label, runner.completed, runner.total,
                            runner.jobs, runner.workers)
        runner.release_paced(generation)

    def _poll_jobs(self):
        events = self._runner.poll()
        if events is None:
            self._job_timer.stop()
            return
        for text in events.stages:
            self._set_scan_stage(text)
        for row in events.started:
            self._folder_model.set_job_state(row, 'running')
        for row in events.result_rows:
            self._folder_model.set_job_state(row, '')
        if events.finished:
            self._finish_job(events.summary)
            return
        if events.progress_changed:
            self._folder_model.refresh()
            self.folderChanged.emit()
            runner = self._runner
            if runner.completed < runner.total and not runner.cancel_pending:
                if not runner.paced:
                    self._show_progress(runner.label, runner.completed, runner.total,
                                        runner.jobs, runner.workers)
                else:
                    percent = runner.completed * 100 // runner.total
                    self.progress_value = runner.completed
                    self.progress_text = (f'{runner.label} · {runner.completed}/{runner.total} '
                                          f'processed ({percent}%)')
                    self.progressChanged.emit()
                    generation = runner.generation
                    QTimer.singleShot(
                        250, lambda: self._show_next_if_current(generation)
                    )

    def _finish_job(self, summary):
        self._job_timer.stop()
        self._folder_model.clear_job_states()
        self._busy = False
        self.busy_label = ''
        self._folder_model.refresh()
        self.folderChanged.emit()
        self.progress_max = summary.total
        self.progress_value = summary.completed
        self.progress_current = ''
        self._set_scan_stage('')
        self.progress_text, self.progress_detail = summary.lines()
        self.busyChanged.emit()
        self.progressChanged.emit()
        if summary.failures and summary.report_failures:
            QMessageBox.warning(
                None, summary.label,
                f'{len(summary.failures)} of {summary.total} failed. '
                f'First error:\n{summary.failures[0]}',
            )
        if summary.complete is not None:
            summary.complete()

    @Slot()
    def copyBoxesToFolder(self):
        if self._busy or self.active is None or self.review.image is None:
            return
        boxes = self.review.selected_boxes()
        if not boxes:
            self._info('Copy selected boxes', 'Select or draw the boxes you want to copy first.')
            return
        targets = [entry for index, entry in enumerate(self.entries) if index != self.active]
        if not targets:
            self._info('Copy selected boxes', 'Open a folder with at least two images.')
            return
        if not self._ask(
                'Copy selected boxes?',
                f'Copy {len(boxes)} selected box(es) to the same positions on other images of the same size? '
                'Check that the content lines up before confirming and saving.'):
            return
        size = self.review.image.size
        applied = skipped = unchanged = 0

        def operation(job):
            path, expected = job
            stamp = core.file_stamp(path)
            if expected is not None and stamp != expected:
                raise ValueError(f'{path.name} changed. Reopen the folder before copying boxes.')
            with Image.open(path) as image:
                matches = image.size == size
            if core.file_stamp(path) != stamp:
                raise ValueError(f'{path.name} changed while reading.')
            return stamp, matches

        def accept(index, result, error):
            nonlocal applied, skipped, unchanged
            if error:
                return
            entry = targets[index]
            stamp, matches = result
            if not matches or (entry.stamp is not None and entry.stamp != stamp):
                skipped += 1
                return
            entry.stamp = stamp
            if not entry.add_shared_boxes(boxes, source='Copied box'):
                unchanged += 1
                return
            applied += 1
            if self.active is not None and self.entries[self.active] is entry and self.review.image is not None:
                self.review.confirmed = False
                self._refresh_display()
                self._emit_review()

        def finish():
            return (f'{applied} updated · {skipped} skipped (size or source changed) · '
                    f'{unchanged} already selected')

        self._run_jobs(
            'Copying boxes',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self._folder_rows(),
        )

    def _match_boxes_to_folder(self, anchor):
        try:
            from visual_anchor import locate_anchor, prepare_anchor, relocate_boxes
        except ImportError:
            self._error(
                'Visual matching unavailable',
                'Install the project dependencies from requirements.txt and restart.',
            )
            return
        boxes = self.review.selected_boxes()
        if not boxes:
            self._set_status('Select boxes to match across the folder.')
            return
        left, top, right, bottom = anchor
        if right - left < 20 or bottom - top < 20:
            self._set_status(
                'Anchor too small. Click Match boxes by visual anchor and drag around a larger area.'
            )
            return
        try:
            patch = prepare_anchor(self.review.image, anchor)
        except ValueError as error:
            self._set_status(str(error))
            return
        targets = [entry for index, entry in enumerate(self.entries) if index != self.active]
        matched = skipped = 0

        def operation(job):
            path, expected = job
            image, stamp = core.read_folder_image(path, expected)
            match = locate_anchor(image, patch)
            placed = relocate_boxes(boxes, anchor, match, image.size) if match else []
            return stamp, placed

        def accept(index, result, error):
            nonlocal matched, skipped
            entry = targets[index]
            if error:
                return
            stamp, placed = result
            if not placed or (entry.stamp is not None and entry.stamp != stamp):
                skipped += 1
                return
            entry.stamp = stamp
            matched += 1
            if entry.add_shared_boxes(placed, source='Anchor match') and self.active is not None and self.entries[self.active] is entry:
                self.review.confirmed = False
                self._refresh_display()
                self._emit_review()

        def finish():
            return f'{matched} matched · {skipped} skipped (no reliable placement)'

        self._run_jobs(
            'Matching visual anchor',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self._folder_rows(),
        )

    @Slot()
    def confirmAll(self):
        if not self._busy and self.entries:
            self._confirm_entries(self.entries, 'Confirm all')

    def _confirm_entries(self, entries, title):
        self._store_active()
        pending = [entry for entry in entries
                   if entry.selected and not entry.error and not entry.reviewed]
        if not pending:
            self._info(
                title,
                'No eligible images are awaiting confirmation. Check whether they are already '
                'reviewed, have no selected boxes, or have a scan error.',
            )
            return
        partial_count = sum(bool(entry.incomplete_ocr) for entry in pending)
        prompt = (f'Apply {self._settings["method"]} to the selected boxes on '
                  f'{len(pending)} image(s)?')
        if partial_count:
            prompt += (f'\n\n{partial_count} image(s) have partial scans. '
                       'Confirm only if you have checked those images for missed sensitive text.')
        if not self._ask(title, prompt):
            return
        for entry in pending:
            entry.reviewed = True
        if self.active is not None and self.review.image is not None:
            self.review.confirmed = self.entries[self.active].reviewed
            self._refresh_display()
            self._emit_review()
        self._folder_model.refresh()
        self.folderChanged.emit()
        self._set_status(
            f'Confirmed {len(pending)} image(s). Use Save reviewed images to export them.'
        )

    @Slot()
    def saveReviewed(self):
        if self._busy:
            return
        self._store_active()
        pending = [(index, entry) for index, entry in enumerate(self.entries)
                   if entry.reviewed and not entry.saved]
        if not pending:
            self._info('Save reviewed images', 'Confirm the selection on each image you want to save.')
            return
        self._export_entries(pending)

    @Slot()
    def copyRedacted(self):
        if self.review.image is None:
            return
        if not self.review.confirmed:
            self._set_status('Confirm selection to copy the redacted image.')
            return
        if not self.review.selected and not self._ask(
                'No redactions', 'No areas are selected. Copy the unredacted image?'):
            return
        if self._display_qimage.isNull():
            self._error('Copy failed', 'The preview is not available.')
            return
        QGuiApplication.clipboard().setImage(self._display_qimage.copy())
        if self.review.selected:
            self._set_status(
                f'Copied the redacted image with {len(self.review.selected)} area(s) to the clipboard.'
            )
        else:
            self._set_status('Copied the unredacted image to the clipboard.')

    @Slot()
    def save(self):
        if self._busy or self.review.image is None:
            return
        if self.active is None:
            self._save_single()
            return
        self._store_active()
        entry = self.entries[self.active]
        if self.review.image is None or not entry.reviewed:
            self._info('Review image', 'Review this image and confirm the selection before saving.')
            return
        self._export_entries([(self.active, entry)], individual=True)

    def _save_single(self):
        if self.review.image is None:
            return
        if not self.review.confirmed:
            self._info(
                'Confirm selection',
                'Select the areas to redact and click Confirm selection before saving.',
            )
            return
        if not self.review.selected and not self._ask(
                'No redactions', 'No areas are selected. Save an unredacted copy?'):
            return
        initial = self.review.path.stem + '_redacted.png'
        chosen, _ = QFileDialog.getSaveFileName(
            None, 'Save redacted copy', initial, 'PNG image (*.png)'
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.resolve() == self.review.path.resolve():
            self._error('Choose a different file', 'The original image cannot be overwritten.')
            return
        trace = PerformanceRun('Saving image', 1, {
            'method': self._settings['method'], 'coordinate_logs': True,
        })
        try:
            with trace.image(0):
                out = core.apply_redactions(self.review.image, self.review.selected_boxes(),
                                            self._settings['method'])
                out.info.clear()
                log = {
                    'source_filename': self.review.path.name,
                    'output_filename': target.name,
                    'image_dimensions': list(self.review.image.size),
                    'redaction_rectangles_xyxy': self.review.selected_boxes(),
                    'created_local_time': datetime.now().isoformat(timespec='seconds'),
                    'method': self._settings['method'],
                    'note': ('Automated suggestions can miss identifiers; manual review required. '
                             'Pixelation may not fully conceal sensitive content.'
                             + (' Pasted from the clipboard; no source file exists.'
                                if self._pasted_image else '')),
                }
                core.save_export(out, target, log, overwrite=True)
            self._info(
                'Saved',
                'Saved the redacted PNG and coordinate log. Review before sharing; '
                'pixelated text can sometimes be recovered.',
            )
        except Exception as error:
            self._error('Save failed', str(error))
        finally:
            trace.finish()

    def _export_entries(self, pending, individual=False):
        jobs = []
        targets = set()
        try:
            for index, entry in pending:
                target = core.output_path(
                    self.output_directory, self.filename_template, entry.path, index + 1
                )
                if individual:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    chosen, _ = QFileDialog.getSaveFileName(
                        None, 'Save redacted copy', str(target), 'PNG image (*.png)'
                    )
                    if not chosen:
                        return
                    target = Path(chosen)
                    if target.suffix.lower() != '.png':
                        raise ValueError('Choose a filename ending in .png.')
                outputs = [target]
                if self.include_log:
                    outputs.append(target.with_suffix('.redactions.json'))
                for path in outputs:
                    key = str(path.resolve()).casefold()
                    if key in targets or path.exists():
                        raise ValueError(
                            f'{path.name} already exists or would be written twice. '
                            'Choose another name or folder.'
                        )
                    targets.add(key)
                jobs.append((entry, target))
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            self._error('Cannot save images', str(error))
            return

        unredacted = sum(not entry.selected for _, entry in pending)
        if unredacted and not self._ask(
                'Save unredacted copies?',
                f'{unredacted} reviewed image(s) have no selected boxes. '
                'Save them as unredacted PNG copies?'):
            return

        include_log = self.include_log
        snapshots = [
            (core.FolderImage(
                entry.path, boxes=entry.boxes.copy(), selected=entry.selected.copy(),
                stamp=entry.stamp, method=entry.method,
            ), target)
            for entry, target in jobs
        ]

        def operation(job):
            snapshot, target = job
            target.parent.mkdir(parents=True, exist_ok=True)
            core.write_folder_copy(snapshot, target, include_log)

        def accept(index, result, error):
            entry, target = jobs[index]
            snapshot, _ = snapshots[index]
            if error:
                self._set_status(f'{entry.path.name} · {error}')
            elif entry.reviewed and (entry.boxes, entry.selected, entry.method) == (
                    snapshot.boxes, snapshot.selected, snapshot.method):
                entry.saved = True
                entry.error = ''
                self._set_status(f'Saved {target.name} to {target.parent}')

        self._run_jobs(
            'Saving', snapshots, operation, accept,
            metrics_settings={'method': self._settings['method'], 'coordinate_logs': include_log},
            rows=self._folder_rows(),
        )

    def load_preferences(self):
        try:
            saved = json.loads(self.preferences_file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self._set_status('Saved settings could not be loaded. Using defaults.')
            return
        if not isinstance(saved, dict):
            return
        preset = saved.get('sensitivity')
        if isinstance(preset, str) and preset in {*core.PRESETS, 'Custom'}:
            self._settings['sensitivity'] = preset
        categories = saved.get('categories')
        if isinstance(categories, list):
            self._categories = {name for name in core.PATTERNS if name in categories}
        threshold = saved.get('confidence')
        if type(threshold) is int and 0 <= threshold <= 100:
            self._settings['confidence'] = threshold
        for key, name in (('all_text', 'allText'), ('enhanced_ocr', 'enhancedOcr'),
                          ('color_ocr', 'colorOcr'), ('show_rules', 'showRules')):
            if isinstance(saved.get(key), bool):
                self._settings[name] = saved[key]
        engine = saved.get('ocr_engine')
        if engine in ('Tesseract', 'RapidOCR'):
            self._settings['ocrEngine'] = engine
        method = saved.get('redaction_method')
        if method in ('Pixelate', 'Solid black'):
            self.default_method = method
            self._settings['method'] = method
        workers = saved.get('parallel_images')
        if type(workers) is int:
            self._settings['parallelImages'] = max(1, min(self.parallel_limit, workers))
        blocked = saved.get('blocked_patterns')
        if isinstance(blocked, list):
            loaded = []
            for entry in blocked:
                if not isinstance(entry, dict):
                    continue
                text = entry.get('text')
                pattern = entry.get('pattern')
                if not isinstance(text, str) or not isinstance(pattern, str) or not pattern.strip():
                    continue
                try:
                    re.compile(pattern)
                except re.error:
                    continue
                enabled = entry.get('enabled', True)
                loaded.append({'text': text.strip(), 'pattern': pattern.strip(),
                               'enabled': enabled if isinstance(enabled, bool) else True})
            self._blocked_patterns = loaded
        legacy = saved.get('custom_pattern')
        if isinstance(legacy, str) and legacy.strip():
            legacy = legacy.strip()
            try:
                re.compile(legacy)
            except re.error:
                pass
            else:
                if not any(entry['pattern'].casefold() == legacy.casefold()
                           for entry in self._blocked_patterns):
                    self._blocked_patterns.append({
                        'text': 'Imported custom pattern', 'pattern': legacy, 'enabled': True,
                    })
        self._restore_output_preferences(saved)

    def _restore_output_preferences(self, saved):
        directory = saved.get('output_directory')
        if isinstance(directory, str):
            path = Path(directory) if directory else None
            if path is None or path.is_absolute():
                self.output_directory_override = path
                self.output_directory = path or (
                    self.folder / 'redacted' if self.folder else None
                )
                self._settings['outputDirectory'] = str(path) if path else ''
        template = saved.get('filename_template')
        if isinstance(template, str) and template.strip():
            try:
                core.output_path(Path('.'), template, Path('example.png'), 1)
            except (ValueError, KeyError, IndexError, AttributeError):
                pass
            else:
                self.filename_template = template
                self._settings['filenameTemplate'] = template
        if isinstance(saved.get('include_log'), bool):
            self.include_log = saved['include_log']
            self._settings['includeLog'] = saved['include_log']

    def _preference_document(self, method=None):
        return {
            'sensitivity': self._settings['sensitivity'],
            'confidence': self._settings['confidence'],
            'all_text': self._settings['allText'],
            'enhanced_ocr': self._settings['enhancedOcr'],
            'color_ocr': self._settings['colorOcr'],
            'ocr_engine': self._settings['ocrEngine'],
            'categories': [name for name in core.PATTERNS if name in self._categories],
            'redaction_method': method or self._settings['method'],
            'output_directory': self._settings['outputDirectory'],
            'filename_template': self._settings['filenameTemplate'],
            'include_log': self._settings['includeLog'],
            'parallel_images': self._settings['parallelImages'],
            'show_rules': self._settings['showRules'],
            'blocked_patterns': [dict(entry) for entry in self._blocked_patterns],
        }

    @Slot(bool)
    def setShowRules(self, enabled):
        enabled = bool(enabled)
        if self._settings['showRules'] == enabled:
            return
        self._settings['showRules'] = enabled
        self.settingsChanged.emit()
        try:
            core.write_preferences(self.preferences_file, self._preference_document())
        except OSError as error:
            self._set_status(self.status_text + f' Settings could not be saved: {error}')
            return
        self._set_status('Rule labels on. Hover a box or select one to inspect its rule.'
                         if enabled else 'Rule labels hidden.')

    @Slot(str)
    def setRedactionMethod(self, method):
        if self._busy or method not in ('Pixelate', 'Solid black') \
                or method == self._settings['method']:
            return
        self._settings['method'] = method
        self.default_method = method
        self.settingsChanged.emit()
        self._method_changed()
        if not self.entries:
            updated = ' Preview updated.' if self.review.confirmed else ''
            self._set_status(f'Redaction method set to {method}.{updated}')
        try:
            core.write_preferences(self.preferences_file, self._preference_document())
        except OSError as error:
            self._set_status(self.status_text + f' Settings could not be saved: {error}')

    @Slot(str, int, bool, bool, bool, str, 'QVariantList', str, str, str, bool, int, result=str)
    def applySettings(self, sensitivity, confidence, all_text, enhanced, color, engine,
                      categories, method, output_directory, template, include_log,
                      parallel_images):
        try:
            threshold = int(confidence)
            if not 0 <= threshold <= 100:
                raise ValueError('OCR confidence must be between 0 and 100.')
            workers = int(parallel_images)
            if not 1 <= workers <= self.parallel_limit:
                raise ValueError(f'Parallel image jobs must be between 1 and {self.parallel_limit}.')
            chosen = Path(output_directory.strip()) if output_directory.strip() else None
            if chosen is not None and not chosen.is_absolute():
                raise ValueError('Choose an absolute output folder.')
            name = template.strip()
            if not name:
                raise ValueError('Enter a filename template.')
            source = self.entries[0].path if self.entries else Path('example.png')
            core.output_path(chosen or Path('.'), name, source, 1)
            selected = [category for category in core.PATTERNS if category in categories]
            method_changed = method != self._settings['method']
            preferences = {
                'sensitivity': sensitivity,
                'confidence': threshold,
                'all_text': all_text,
                'enhanced_ocr': enhanced,
                'color_ocr': color,
                'ocr_engine': engine,
                'categories': selected,
                'redaction_method': method if method_changed else self.default_method,
                'output_directory': str(chosen) if chosen is not None else '',
                'filename_template': name,
                'include_log': include_log,
                'parallel_images': workers,
                'show_rules': self._settings['showRules'],
                'blocked_patterns': [dict(entry) for entry in self._blocked_patterns],
            }
            core.write_preferences(self.preferences_file, preferences)
        except (ValueError, re.error, KeyError, IndexError, AttributeError) as error:
            return str(error)
        except OSError as error:
            return f'Could not save settings: {error}'

        self._settings.update({
            'sensitivity': sensitivity,
            'confidence': threshold,
            'allText': all_text,
            'enhancedOcr': enhanced,
            'colorOcr': color,
            'ocrEngine': engine,
            'parallelImages': workers,
        })
        self._categories = set(selected)
        self._restore_output_preferences(preferences)
        self.default_method = preferences['redaction_method']
        self.settingsChanged.emit()
        if method_changed:
            self._settings['method'] = method
            self.settingsChanged.emit()
            self._method_changed()
        return ''

    def _method_changed(self):
        if not self.entries:
            if self.review.confirmed:
                self._refresh_display()
            return
        method = self._settings['method']
        for entry in self.entries:
            if entry.method != method:
                entry.method = method
                entry.reviewed = entry.saved = False
        self.review.confirmed = False
        self._refresh_display()
        self._emit_review()
        self._folder_model.refresh()
        self.folderChanged.emit()
        self._set_status(
            f'{method} will be used across the folder. '
            'Confirm the updated redactions before saving.'
        )

    @Slot()
    def requestSettings(self):
        self.settingsRequested.emit()

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
            self._info('Performance logs', str(directory))
