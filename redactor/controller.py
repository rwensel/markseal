from __future__ import annotations

import io
import re
from pathlib import Path
from queue import Queue
from threading import Event

from PIL import Image
from PySide6.QtCore import Property, QBuffer, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QFileDialog

from .performance_log import PerformanceRun

from . import boxset
from . import export
from . import images
from . import ocr
from . import redaction
from .facades import Alerts, JobCenter, SessionState, SettingsFacade
from .facades.alerts import box_hint
from .ui.models import DisplayImageProvider, FolderModel
from . import workflows









class Controller(QObject):
    statusChanged = Signal()
    errorChanged = Signal()
    imageChanged = Signal()
    imageRevisionChanged = Signal()
    reviewChanged = Signal()
    viewChanged = Signal()
    folderChanged = Signal()
    busyChanged = Signal()
    progressChanged = Signal()
    scanStageChanged = Signal()
    captureChanged = Signal()
    scrollRequested = Signal(int)

    def __init__(self, preferences_file=None, parent=None):
        super().__init__(parent)
        self.session = SessionState(preferences_file)
        self.alerts = Alerts(self)
        self.jobs = JobCenter(self.session, self)
        self._settings = SettingsFacade(self.session, self.alerts, self)
        self.session.alerts = self.alerts
        self.session.jobs = self.jobs
        self.session.facades.settings = self._settings
        self._settings.on_method_changed = self._method_changed
        self._settings.retry_learn = self.beginLearnPattern
        self.alerts.statusChanged.connect(self.statusChanged)
        self.alerts.errorChanged.connect(self.errorChanged)
        self.jobs.busyChanged.connect(self.busyChanged)
        self.jobs.progressChanged.connect(self.progressChanged)
        self.jobs.scanStageChanged.connect(self.scanStageChanged)
        self.capture = 'none'
        self.drag = None
        self._panning = False
        self.image_revision = 0
        self._display_qimage = QImage()
        self._folder_model = FolderModel()
        self.jobs.jobStatesQueued.connect(
            lambda states: self._folder_model.set_job_states(states))
        self.jobs.jobStarted.connect(
            lambda row: self._folder_model.set_job_state(row, 'running'))
        self.jobs.jobCleared.connect(
            lambda row: self._folder_model.set_job_state(row, ''))
        self.jobs.jobStatesCleared.connect(self._folder_model.clear_job_states)
        self.jobs.rowsChanged.connect(self._refresh_folder_rows)
        self.jobs.before_start = self._cancel_capture
        self._settings.load_preferences()
        if not self.alerts.status_text:
            self.alerts.set_status(box_hint(self.session.preferences.theme))

    @Property(QObject, constant=True)
    def settings(self):
        return self._settings

    def display_qimage(self):
        return self._display_qimage

    def _refresh_folder_rows(self):
        self._folder_model.refresh()
        self.folderChanged.emit()

    def _pil_to_qimage(self, image):
        if image.mode != 'RGB':
            image = image.convert('RGB')
        raw = image.tobytes('raw', 'RGB')
        return QImage(
            raw, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
        ).copy()

    def _refresh_display(self):
        image = self.session.review.image
        if image is not None and self.session.review.confirmed:
            image = redaction.apply_redactions(image, self.session.review.selected_boxes(), self.session.preferences.method)
        if image is None:
            self._display_qimage = QImage()
        else:
            self._display_qimage = self._pil_to_qimage(image)
        self.image_revision += 1
        self.imageRevisionChanged.emit()

    def _emit_review(self):
        self.reviewChanged.emit()
        self._refresh_folder_rows()

    def _emit_view(self):
        self.viewChanged.emit()

    def _review_status(self):
        name = self.session.review.path.name if self.session.review.path else ''
        return (f'{name}: {len(self.session.review.selected)} selected of '
                f'{len(self.session.review.boxes)}. Confirm to apply.')

    def _load_image(self, image, path, pasted=False):
        self.session.pasted_image = pasted
        self.session.review.load(image, path)
        self._refresh_display()
        self.imageChanged.emit()
        self._emit_review()
        self._emit_view()

    @Property(str, notify=statusChanged)
    def statusText(self):
        return self.alerts.status_text

    @Property(bool, notify=imageChanged)
    def hasImage(self):
        return self.session.review.image is not None

    @Property(str, notify=imageChanged)
    def imageName(self):
        if self.session.pasted_image:
            return 'Pasted image'
        return self.session.review.path.name if self.session.review.path else ''

    @Property(str, notify=imageChanged)
    def imageSizeText(self):
        if self.session.review.image is None:
            return ''
        width, height = self.session.review.image.size
        return f'{width} × {height}'

    @Property(int, notify=imageRevisionChanged)
    def imageRevision(self):
        return self.image_revision

    @Property(int, notify=imageChanged)
    def imageWidth(self):
        return self.session.review.image.width if self.session.review.image else 0

    @Property(int, notify=imageChanged)
    def imageHeight(self):
        return self.session.review.image.height if self.session.review.image else 0

    @Property(list, notify=reviewChanged)
    def boxes(self):
        boxes = []
        for index, box in enumerate(self.session.review.boxes):
            labels = tuple(self.session.review.rules.get(box, ())) or ('Manual box',)
            label = labels[0] if len(labels) == 1 else f'{labels[0]} +{len(labels) - 1}'
            boxes.append({
                'x1': box[0], 'y1': box[1], 'x2': box[2], 'y2': box[3],
                'selected': index in self.session.review.selected,
                'rules': list(labels), 'ruleLabel': label,
            })
        return boxes

    @Property(int, notify=reviewChanged)
    def selectedCount(self):
        return len(self.session.review.selected)

    @Property(int, notify=reviewChanged)
    def excludedCount(self):
        return len(self.session.review.boxes) - len(self.session.review.selected)

    @Property(int, notify=reviewChanged)
    def totalBoxes(self):
        return len(self.session.review.boxes)

    @Property(bool, notify=reviewChanged)
    def confirmed(self):
        return self.session.review.confirmed

    @Property(str, notify=folderChanged)
    def confirmLabel(self):
        count = len(self.session.row_selection) if self.session.entries else 0
        return f'CONFIRM {count}' if count > 1 else 'CONFIRM'

    @Property(float, notify=viewChanged)
    def viewScale(self):
        return self.session.review.scale

    @Property(float, notify=viewChanged)
    def viewOffsetX(self):
        return self.session.review.offset_x

    @Property(float, notify=viewChanged)
    def viewOffsetY(self):
        return self.session.review.offset_y

    @Property(int, notify=viewChanged)
    def zoomPercent(self):
        return round(self.session.review.zoom * 100)

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
    def folderImageCount(self):
        return len(self.session.entries)

    @Property(QObject, constant=True)
    def folderModel(self):
        return self._folder_model

    @Property(bool, notify=busyChanged)
    def busy(self):
        return self.jobs.busy

    @Property(str, notify=busyChanged)
    def busyLabel(self):
        return self.jobs.busyLabel

    @Property(str, notify=errorChanged)
    def errorText(self):
        return self.alerts.error_text

    @Property(str, notify=errorChanged)
    def errorDetail(self):
        return self.alerts.error_detail

    @Property(str, notify=errorChanged)
    def errorActionText(self):
        return self.alerts.error_action_text

    @Slot()
    def dismissError(self):
        self.alerts.dismiss()

    @Slot()
    def runErrorAction(self):
        self.alerts.run_action()

    @Property(bool, notify=busyChanged)
    def canCancel(self):
        return self.jobs.canCancel

    @Property(str, notify=progressChanged)
    def progressText(self):
        return self.jobs.progressText

    @Property(int, notify=progressChanged)
    def progressValue(self):
        return self.jobs.progressValue

    @Property(int, notify=progressChanged)
    def progressMax(self):
        return self.jobs.progressMax

    @Property(str, notify=progressChanged)
    def progressDetail(self):
        return self.jobs.progressDetail

    @Property(str, notify=progressChanged)
    def progressCurrent(self):
        return self.jobs.progressCurrent

    @Property(str, notify=scanStageChanged)
    def scanStage(self):
        return self.jobs.scanStage

    def _choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            None, 'Open image', '',
            'Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff);;All files (*.*)',
        )
        return Path(path) if path else None

    def _choose_folder(self, title):
        path = QFileDialog.getExistingDirectory(None, title)
        return Path(path) if path else None

    def _can_leave(self):
        self._store_active()
        if not self.session.entries:
            return True
        pending = any(not entry.saved and (entry.boxes or entry.reviewed) for entry in self.session.entries)
        return not pending or self.alerts.ask(
            'Leave folder?', 'Some images have unsaved review work. Leave this folder?'
        )

    def _clear_folder(self):
        self.session.entries = []
        self.session.active = None
        self.session.row_selection = set()
        self.session.row_anchor = None
        self._folder_model.set_entries([])
        self.folderChanged.emit()

    def _prepare_image_open(self):
        if self.jobs.busy:
            return False
        if not self._can_leave():
            return False
        if not self.session.entries and self.session.review.boxes:
            if not self.alerts.ask('Open another image', 'Discard the current unsaved markings?'):
                return False
        return True

    def _present_image(self, image, path, pasted=False):
        self._cancel_capture()
        if self.session.entries:
            self._clear_folder()
        self._load_image(image, path, pasted=pasted)
        self.alerts.set_status(f'{self.imageName}: find suggestions or drag to add a box, then confirm.')

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
            self.alerts.error('Cannot open image', str(error))
            return
        self._present_image(image, chosen)

    @Slot()
    def openFolder(self):
        if self.jobs.busy:
            return
        chosen = self._choose_folder('Open image folder')
        if chosen is None:
            return
        self._open_folder_path(chosen)

    def _open_folder_path(self, chosen):
        if self.jobs.busy or not self._can_leave():
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
            self.alerts.info('No images', 'Choose a folder containing PNG, JPEG, BMP or TIFF images.')
            return
        if not self.session.entries and self.session.review.boxes and not self.alerts.ask(
                'Open folder?', 'Discard the current image markings?'):
            return
        self._cancel_capture()
        self.session.folder = chosen
        self.session.output_directory = self.session.output_directory_override or chosen / 'redacted'
        self.session.entries = [boxset.FolderImage(path, method=self.session.preferences.method) for path in paths]
        self.session.active = None
        self.session.row_selection = {0}
        self.session.row_anchor = 0
        self._folder_model.set_entries(self.session.entries)
        self._folder_model.set_selection(self.session.row_selection)
        self._folder_model.set_active(0)
        self.jobs.progressText = 'Ready'
        self.jobs.progressValue = 0
        self.jobs.progressMax = 1
        self.jobs.progressDetail = 'Select images to scan, then review each image.'
        self.jobs.progressCurrent = ''
        self.progressChanged.emit()
        self._show_folder_image(0)

    @Slot('QVariantList')
    def openDropped(self, urls):
        if self.jobs.busy:
            return
        paths = []
        for value in urls or []:
            url = value if isinstance(value, QUrl) else QUrl(str(value))
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        images = [path for path in paths
                  if path.is_file() and path.suffix.lower() in images.IMAGE_SUFFIXES]
        if images:
            if not self._prepare_image_open():
                return
            try:
                with Image.open(images[0]) as source:
                    image = source.convert('RGB')
            except Exception as error:
                self.alerts.error('Cannot open image', str(error))
                return
            self._present_image(image, images[0])
            return
        folders = [path for path in paths if path.is_dir()]
        if folders:
            self._open_folder_path(folders[0])
            return
        self.alerts.info('Drop an image', 'Drop a PNG, JPEG, BMP, TIFF image, or an image folder.')

    def _clipboard_image(self):
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        if data.hasUrls():
            for url in data.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    if path.is_file() and path.suffix.lower() in images.IMAGE_SUFFIXES:
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
        if self.jobs.busy:
            return
        try:
            loaded = self._clipboard_image()
        except Exception as error:
            self.alerts.error('Cannot paste image', str(error))
            return
        if loaded is None:
            self.alerts.info('Paste image', 'The clipboard does not contain an image.')
            return
        if not self._prepare_image_open():
            return
        image, path, pasted = loaded
        self._present_image(image, path, pasted=pasted)

    def _store_active(self):
        if self.session.active is None or self.session.review.image is None:
            return
        if not 0 <= self.session.active < len(self.session.entries):
            return
        entry = self.session.entries[self.session.active]
        if entry.reviewed and not self.session.review.confirmed:
            entry.saved = False
        entry.reviewed = self.session.review.confirmed

    def _show_folder_image(self, index):
        if not 0 <= index < len(self.session.entries) or self.session.active == index:
            return
        self._cancel_capture()
        self._store_active()
        self.session.active = index
        entry = self.session.entries[index]
        self.session.pasted_image = False
        self.session.review.path = entry.path
        self.session.review.boxset = entry.boxset
        self.session.review.confirmed = entry.reviewed
        self.session.review.viewport.clear()
        try:
            image, entry.stamp = images.read_folder_image(entry.path, entry.stamp)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            self.session.review.image = None
            entry.error = 'Open failed'
            self.alerts.set_status(f'{entry.path.name} · {error}')
        else:
            self.session.review.image = image
            self.session.review.viewport.reset(image.size)
            self._refresh_display()
            self.alerts.set_status(
                f'{entry.path.name} · {entry.status} · {len(entry.selected)} boxes selected'
            )
        self._folder_model.set_active(index)
        self._folder_model.set_selection(self.session.row_selection)
        self.imageChanged.emit()
        self._emit_review()
        self._emit_view()
        self.scrollRequested.emit(index)

    @Slot(int, bool, bool)
    def selectRow(self, index, control, shift):
        if not 0 <= index < len(self.session.entries):
            return
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
        if not self.session.row_selection:
            return
        target = index if index in self.session.row_selection else min(self.session.row_selection)
        if target != self.session.active:
            self._show_folder_image(target)

    @Slot(int, int)
    def setViewSize(self, width, height):
        self.session.review.set_view_size(width, height)
        self._emit_view()

    @Slot(int, int)
    def press(self, x, y):
        if self.capture != 'none' and self.session.review.image is not None:
            self.session.review.viewport.begin_drag(x, y)
            self.drag = (x, y, 0, 0)
            self._emit_view()
            return
        self.session.review.press(x, y)

    @Slot(int, int)
    def move(self, x, y):
        if self.session.review.viewport.pan_origin is not None:
            if self.session.review.pan_move(x, y):
                self._emit_view()
            return
        rect = self.session.review.viewport.drag_rect(x, y)
        if rect is not None:
            self.drag = rect
            self._emit_view()

    @Slot(int, int)
    def release(self, x, y):
        if self._panning:
            if self.session.review.pan_end():
                self._panning = False
                self.viewChanged.emit()
            return
        if (self.capture != 'none' and self.session.review.viewport.drag_origin is not None
                and self.session.review.image is not None):
            capture = self.capture
            anchor = self.session.review.viewport.drag_region(x, y)
            self._cancel_capture()
            if capture == 'area':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    self.alerts.set_status('Area too small. Click Scan area and draw around the text again.')
                elif self.session.active is None:
                    self._start_single_scan(area=anchor)
                else:
                    self._start_scan([self.session.entries[self.session.active]], rescan=True, area=anchor)
            elif capture == 'learn':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    self.alerts.set_status('Area too small. Draw a tight box around the text you want to block.')
                else:
                    self._learn_pattern(anchor)
            else:
                self._match_boxes_to_folder(anchor)
            return
        self.drag = None
        action = self.session.review.release(x, y)
        if action != 'none':
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self.alerts.set_status(self._review_status())
        self._emit_view()

    @Slot(int, int, int)
    def zoomAt(self, x, y, delta):
        if self.session.review.zoom_at(x, y, 1 if delta > 0 else -1):
            self._emit_view()

    @Slot(int)
    def zoomStep(self, direction):
        if self.session.review.image is None:
            return
        viewport = self.session.review.viewport
        if self.session.review.zoom_at(viewport.view_width / 2, viewport.view_height / 2, direction):
            self._emit_view()

    @Slot()
    def zoomFit(self):
        if self.session.review.image is None:
            return
        viewport = self.session.review.viewport
        viewport.zoom = 1.0
        viewport.refit()
        self._emit_view()

    @Slot(int, int)
    def panStep(self, dx, dy):
        if self.session.review.image is None or self.session.review.zoom <= 1.0:
            return
        viewport = self.session.review.viewport
        viewport.offset_x += dx
        viewport.offset_y += dy
        viewport.clamp_offsets()
        self._emit_view()

    @Slot()
    def selectAllBoxes(self):
        if self.session.review.select_all():
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self.alerts.set_status(self._review_status())

    @Slot()
    def selectNoBoxes(self):
        if self.session.review.select_none():
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self.alerts.set_status(self._review_status())

    @Slot(int, int)
    def beginPan(self, x, y):
        if self.session.review.pan_begin(x, y):
            self._panning = True
            self.viewChanged.emit()

    @Slot(int, int)
    def movePan(self, x, y):
        if self.session.review.pan_move(x, y):
            self.viewChanged.emit()

    @Slot()
    def endPan(self):
        if self.session.review.pan_end():
            self._panning = False
            self.viewChanged.emit()

    @Slot(int)
    def toggleBox(self, index):
        if self.session.review.confirmed:
            return
        if self.session.review.toggle_box(index):
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self.alerts.set_status(self._review_status())

    @Slot(int)
    def removeBox(self, index):
        if self.session.review.confirmed:
            return
        if self.session.review.remove_box(index):
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._emit_view()
            self.alerts.set_status(
                f'{self.session.review.path.name}: box removed. '
                f'{len(self.session.review.selected)} selected of {len(self.session.review.boxes)}.'
            )

    @Slot()
    def undo(self):
        if self.session.review.undo():
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._emit_view()
        if self.session.review.image is not None:
            self.alerts.set_status(self._review_status())

    @Slot()
    def editBoxes(self):
        if self.session.review.image is None or not self.session.review.confirmed:
            return
        self.session.review.confirmed = False
        self._refresh_display()
        self._store_active()
        self._emit_review()
        self.alerts.set_status('Click an X to remove a box. Confirm selection when ready.')

    @Slot()
    def clearBoxes(self):
        if not self.session.review.boxes:
            return
        if not self.alerts.ask('Clear boxes', 'Remove all suggested and manually drawn boxes?'):
            return
        self.session.review.clear()
        self._refresh_display()
        self._store_active()
        self._emit_review()
        self._emit_view()
        self.alerts.set_status('Boxes cleared. Scan again or drag to add an area.')

    @Slot()
    def confirmSelection(self):
        if self.jobs.busy or self.session.review.image is None:
            return
        selected = sorted(self.session.row_selection) if self.session.entries else ()
        if len(selected) > 1:
            self._confirm_entries([self.session.entries[index] for index in selected], 'Confirm selected images')
        else:
            self.session.review.confirmed = True
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self.alerts.set_status(
                f'{len(self.session.review.selected)} boxes applied in preview. '
                'Save, or click to change your selection.'
            )

    @Slot()
    def cancelCapture(self):
        if self.capture != 'none':
            self._cancel_capture()
            self.alerts.set_status('Area selection canceled.')

    def _cancel_capture(self):
        if self.capture != 'none' or self.drag is not None:
            self.capture = 'none'
            self.drag = None
            self.session.review.viewport.cancel_drag()
            self.captureChanged.emit()
            self._emit_view()

    def _scan_engine(self):
        return self.session.scan_engine()

    def _scan_settings(self):
        return self.session.scan_settings()

    def _scan_metrics(self):
        return self.session.scan_metrics()

    @Slot()
    def find(self):
        if self.jobs.busy or self.session.review.image is None:
            return
        if self.session.active is not None:
            self._start_scan([self.session.entries[self.session.active]], rescan=True)
            return
        self._start_single_scan()

    def _start_single_scan(self, area=None):
        if self.session.review.image is None or self.jobs.busy:
            return
        try:
            engine = self._scan_engine()
            settings = self._scan_settings()
        except OSError as error:
            self.alerts.error('OCR unavailable', str(error), 'RETRY',
                        lambda: self._start_single_scan(area=area))
            return
        except (ValueError, re.error) as error:
            self.alerts.error('Invalid detection settings', str(error), 'OPEN SETTINGS',
                        self.requestSettings)
            return
        stages = Queue()
        info = {'added': None, 'incomplete': [], 'error': None}
        label = 'Scanning area' if area is not None else 'Scanning image'

        def operation(job):
            incomplete = []
            found = ocr.recognize_regions(
                self.session.review.image, engine, settings, self.session.preferences.enhanced_ocr,
                color_assisted=self.session.preferences.color_ocr, incomplete=incomplete,
                area=area, progress=stages.put,
            )
            return None, found, incomplete

        def accept(index, result, error):
            if error is not None:
                info['error'] = error
                self.alerts.set_status(f'Scan failed: {error}')
                return
            _, found, incomplete = result
            added = self.session.review.add_suggestions(found)
            self._refresh_display()
            self._store_active()
            self._emit_review()
            self._emit_view()
            info['added'] = added
            info['incomplete'] = incomplete
            detail = f' Incomplete OCR passes: {", ".join(incomplete)}.' if incomplete else ''
            self.alerts.set_status(
                f'{added} selected suggestions added.{detail} Review the entire image.'
            )

        def finish():
            if info['error'] is not None:
                return 'Scan failed'
            return f'{info["added"] or 0} new OCR suggestions'

        def complete():
            if info['error'] is not None:
                self.alerts.error('Local OCR failed', f'Text recognition failed: {info["error"]}',
                            'RETRY', lambda: self._start_single_scan(area=area))
                return
            if info['added'] is None:
                return
            detail = (f' Incomplete OCR passes: {", ".join(info["incomplete"])}.'
                      if info['incomplete'] else '')
            self.alerts.info(
                'Review required',
                f'Added {info["added"]} selected boxes.{detail} Review the image before confirming.',
            )

        self.alerts.set_status(
            'Scanning the selected area. Progress is shown above the screenshot.' if area is not None
            else 'Scanning image. Progress is shown above the screenshot.'
        )
        self.jobs.run(
            label, [self.session.review.path], operation, accept, finish,
            metrics_settings=self._scan_metrics(), stage_queue=stages,
            complete=complete, report_failures=False,
        )

    @Slot()
    def beginScanArea(self):
        if self.jobs.busy or self.session.review.image is None:
            return
        self._cancel_capture()
        self.capture = 'area'
        self.captureChanged.emit()
        self.alerts.set_status(
            'Drag around the text to scan. For small labels, draw a tight box around a single row. Esc cancels.'
        )

    @Slot()
    def beginAnchorCapture(self):
        if self.jobs.busy or self.session.active is None or self.session.review.image is None:
            return
        if not self.session.review.selected or len(self.session.entries) < 2:
            self.alerts.info(
                'Match by visual anchor',
                'Select redaction boxes on one image in a folder with at least two images.',
            )
            return
        self._cancel_capture()
        self.editBoxes()
        self.capture = 'anchor'
        self.captureChanged.emit()
        self.alerts.set_status('Drag around a distinctive logo or label near the boxes. Esc cancels.')

    @Slot()
    def beginLearnPattern(self):
        if self.jobs.busy or self.session.review.image is None:
            return
        self._cancel_capture()
        self.capture = 'learn'
        self.captureChanged.emit()
        self.alerts.set_status(
            'Drag around the text to block. The area is read locally and turned into a pattern. Esc cancels.'
        )

    @Slot()
    def scanAll(self):
        self._start_scan(self.session.entries, follow=True)

    @Slot()
    def scanSelected(self):
        if self.jobs.busy:
            return
        selected = sorted(self.session.row_selection)
        if not selected:
            self.alerts.info('Scan selected', 'Select one or more images in the folder list first.')
            return
        self._start_scan([self.session.entries[index] for index in selected], rescan=True, follow=True)

    @Slot()
    def rescanAll(self):
        if not self.jobs.busy and self.session.entries and self.alerts.ask(
                'Rescan all images?',
                'Keep existing boxes and add new suggestions. All rescanned images will need review again.'):
            self._start_scan(self.session.entries, rescan=True, follow=True)

    def _start_scan(self, entries, rescan=False, *, follow=False, area=None):
        if self.jobs.busy:
            return
        self._store_active()
        plan = workflows.plan_scan(self.session.entries, entries, rescan=rescan, area=area)
        pending = plan.entries
        if not pending:
            self.alerts.info(
                'Folder scan',
                'Every image has been scanned or manually reviewed. '
                'Use Find likely identifiers to rescan an image.',
            )
            return
        try:
            engine = self._scan_engine()
            settings = self._scan_settings()
        except OSError as error:
            self.alerts.error('OCR unavailable', str(error), 'RETRY',
                        lambda: self._start_scan(entries, rescan=rescan, follow=follow, area=area))
            return
        except (ValueError, re.error) as error:
            self.alerts.error('Invalid detection settings', str(error), 'OPEN SETTINGS',
                        self.requestSettings)
            return
        cancel = Event()
        enhanced = self.session.preferences.enhanced_ocr
        color_assisted = self.session.preferences.color_ocr
        processed = []
        area_completed = False

        def show_image(index):
            row = rows[pending[index].path]
            self._show_folder_image(int(row))

        def operation(job):
            path, stamp = job
            return ocr.scan_folder_image(
                path, stamp, engine, settings, enhanced, cancel,
                color_assisted=color_assisted, area=area,
            )

        def accept(index, result, error):
            nonlocal area_completed
            entry = pending[index]
            if error:
                if area is None:
                    entry.error = 'Scan failed'
                self.alerts.set_status(f'{entry.path.name} · {error}')
                return
            outcome = workflows.apply_scan_result(entry, result, area=area)
            if outcome.error:
                return
            area_completed = area is not None
            if self.session.active is not None and entry is self.session.entries[self.session.active] and self.session.review.image is not None:
                if outcome.changed:
                    self.session.review.confirmed = False
                    self._refresh_display()
                    self._emit_review()
                    self._emit_view()
                detail = (f' Partial scan: {", ".join(outcome.incomplete)}.'
                          if outcome.incomplete else '')
                self.alerts.set_status(
                    f'{entry.path.name} · {outcome.count} new OCR suggestions.{detail} Review before confirming.'
                )

        def track_result(index, result, error):
            accept(index, result, error)
            processed.append(pending[index])

        def finish():
            return workflows.scan_summary(processed, area=area, area_completed=area_completed)

        self.jobs.run(
            plan.label, list(plan.jobs), operation, track_result, finish,
            cancel=cancel, show_image=show_image if follow else None,
            metrics_settings=self._scan_metrics(), rows=plan.rows,
        )

    @Slot()
    def cancelScan(self):
        self.jobs.cancel()

    def _folder_rows(self):
        return {entry.path: index for index, entry in enumerate(self.session.entries)}

    @Slot()
    def copyBoxesToFolder(self):
        if self.jobs.busy or self.session.active is None or self.session.review.image is None:
            return
        boxes = self.session.review.selected_boxes()
        if not boxes:
            self.alerts.info('Copy selected boxes', 'Select or draw the boxes you want to copy first.')
            return
        targets = [entry for index, entry in enumerate(self.session.entries) if index != self.session.active]
        if not targets:
            self.alerts.info('Copy selected boxes', 'Open a folder with at least two images.')
            return
        if not self.alerts.ask(
                'Copy selected boxes?',
                f'Copy {len(boxes)} selected box(es) to the same positions on other images of the same size? '
                'Check that the content lines up before confirming and saving.'):
            return
        size = self.session.review.image.size
        applied = skipped = unchanged = 0

        def operation(job):
            path, expected = job
            stamp = images.file_stamp(path)
            if expected is not None and stamp != expected:
                raise ValueError(f'{path.name} changed. Reopen the folder before copying boxes.')
            with Image.open(path) as image:
                matches = image.size == size
            if images.file_stamp(path) != stamp:
                raise ValueError(f'{path.name} changed while reading.')
            return stamp, matches

        def accept(index, result, error):
            nonlocal applied, skipped, unchanged
            if error:
                return
            entry = targets[index]
            stamp, matches = result
            outcome = workflows.copy_boxes_to_entry(entry, boxes, stamp, matches)
            if outcome == 'skipped':
                skipped += 1
                return
            if outcome == 'unchanged':
                unchanged += 1
                return
            applied += 1
            if self.session.active is not None and self.session.entries[self.session.active] is entry and self.session.review.image is not None:
                self.session.review.confirmed = False
                self._refresh_display()
                self._emit_review()

        def finish():
            return (f'{applied} updated · {skipped} skipped (size or source changed) · '
                    f'{unchanged} already selected')

        self.jobs.run(
            'Copying boxes',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self._folder_rows(),
        )

    def _match_boxes_to_folder(self, anchor):
        try:
            from .visual_anchor import locate_anchor, prepare_anchor, relocate_boxes
        except ImportError:
            self.alerts.error(
                'Visual matching unavailable',
                'Install the project dependencies with pip install -e . and restart.',
            )
            return
        boxes = self.session.review.selected_boxes()
        if not boxes:
            self.alerts.set_status('Select boxes to match across the folder.')
            return
        left, top, right, bottom = anchor
        if right - left < 20 or bottom - top < 20:
            self.alerts.set_status(
                'Anchor too small. Click Match boxes by visual anchor and drag around a larger area.'
            )
            return
        try:
            patch = prepare_anchor(self.session.review.image, anchor)
        except ValueError as error:
            self.alerts.set_status(str(error))
            return
        targets = [entry for index, entry in enumerate(self.session.entries) if index != self.session.active]
        matched = skipped = 0

        def operation(job):
            path, expected = job
            image, stamp = images.read_folder_image(path, expected)
            match = locate_anchor(image, patch)
            placed = relocate_boxes(boxes, anchor, match, image.size) if match else []
            return stamp, placed

        def accept(index, result, error):
            nonlocal matched, skipped
            entry = targets[index]
            if error:
                return
            stamp, placed = result
            matched_here, changed = workflows.match_boxes_to_entry(entry, placed, stamp)
            if not matched_here:
                skipped += 1
                return
            matched += 1
            if changed and self.session.active is not None and self.session.entries[self.session.active] is entry:
                self.session.review.confirmed = False
                self._refresh_display()
                self._emit_review()

        def finish():
            return f'{matched} matched · {skipped} skipped (no reliable placement)'

        self.jobs.run(
            'Matching visual anchor',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=self._folder_rows(),
        )

    @Slot()
    def confirmAll(self):
        if not self.jobs.busy and self.session.entries:
            self._confirm_entries(self.session.entries, 'Confirm all')

    def _confirm_entries(self, entries, title):
        self._store_active()
        pending = workflows.eligible_for_confirmation(entries)
        if not pending:
            self.alerts.info(
                title,
                'No eligible images are awaiting confirmation. Check whether they are already '
                'reviewed, have no selected boxes, or have a scan error.',
            )
            return
        if not self.alerts.ask(title, workflows.confirmation_prompt(pending, self.session.preferences.method)):
            return
        for entry in pending:
            entry.reviewed = True
        if self.session.active is not None and self.session.review.image is not None:
            self.session.review.confirmed = self.session.entries[self.session.active].reviewed
            self._refresh_display()
            self._emit_review()
        self._folder_model.refresh()
        self.folderChanged.emit()
        self.alerts.set_status(
            f'Confirmed {len(pending)} image(s). Use Save reviewed to export them.'
        )

    @Slot()
    def saveReviewed(self):
        if self.jobs.busy:
            return
        self._store_active()
        pending = [(index, entry) for index, entry in enumerate(self.session.entries)
                   if entry.reviewed and not entry.saved]
        if not pending:
            self.alerts.info('Save reviewed', 'Confirm the selection on each image you want to save.')
            return
        self._export_entries(pending)

    @Slot()
    def copyRedacted(self):
        if self.session.review.image is None:
            return
        if not self.session.review.confirmed:
            self.alerts.set_status('Confirm selection to copy the redacted image.')
            return
        if not self.session.review.selected and not self.alerts.ask(
                'No redactions', 'No areas are selected. Copy the unredacted image?'):
            return
        if self._display_qimage.isNull():
            self.alerts.error('Copy failed', 'The preview is not available.',
                        'RETRY', self.copyRedacted)
            return
        QGuiApplication.clipboard().setImage(self._display_qimage.copy())
        if self.session.review.selected:
            self.alerts.set_status(
                f'Copied the redacted image with {len(self.session.review.selected)} box(es) to the clipboard.'
            )
        else:
            self.alerts.set_status('Copied the unredacted image to the clipboard.')

    @Slot()
    def save(self):
        if self.jobs.busy or self.session.review.image is None:
            return
        if self.session.active is None:
            self._save_single()
            return
        self._store_active()
        entry = self.session.entries[self.session.active]
        if self.session.review.image is None or not entry.reviewed:
            self.alerts.set_status('Confirm the selection on this image before saving.')
            return
        self._export_entries([(self.session.active, entry)], individual=True)

    def _save_single(self):
        if self.session.review.image is None:
            return
        if not self.session.review.confirmed:
            self.alerts.set_status('Confirm the selection before saving.')
            return
        if not self.session.review.selected and not self.alerts.ask(
                'No redactions', 'No areas are selected. Save an unredacted copy?'):
            return
        initial = self.session.review.path.stem + '_redacted.png'
        chosen, _ = QFileDialog.getSaveFileName(
            None, 'Save redacted copy', initial, 'PNG image (*.png)'
        )
        if not chosen:
            return
        target = Path(chosen)
        if target.resolve() == self.session.review.path.resolve():
            self.alerts.error('Choose a different file', 'The original image cannot be overwritten.')
            return
        include_log = self.session.preferences.include_log
        trace = PerformanceRun('Saving image', 1, {
            'method': self.session.preferences.method, 'coordinate_logs': include_log,
        })
        self.jobs.begin_manual('Saving copy')
        self.alerts.set_status('Saving the redacted copy…')
        QGuiApplication.processEvents()
        error = None
        try:
            with trace.image(0):
                job = export.snapshot(
                    self.session.review.path, target, self.session.review.boxes, self.session.review.selected,
                    self.session.preferences.method, image=self.session.review.image,
                    pasted=self.session.pasted_image,
                )
                export.write_copy(job, include_log=include_log, overwrite=True)
        except Exception as exc:
            error = exc
        finally:
            trace.finish()
            self.jobs.end_manual()
        if error is not None:
            self.alerts.error('Save failed', str(error), 'RETRY', self.save)
            return
        note = ' and coordinate log' if include_log else ''
        self.alerts.info(
            'Saved',
            f'Saved the redacted PNG{note}. Review before sharing; '
            'pixelated text can sometimes be recovered.',
        )

    def _export_entries(self, pending, individual=False):
        def choose(target):
            chosen, _ = QFileDialog.getSaveFileName(
                None, 'Save redacted copy', str(target), 'PNG image (*.png)'
            )
            return chosen or None

        try:
            plan = workflows.plan_exports(
                pending,
                output_directory=self.session.output_directory,
                template=self.session.preferences.filename_template,
                include_log=self.session.preferences.include_log,
                choose=choose if individual else None,
            )
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            self.alerts.error('Cannot save images', str(error), 'RETRY', self.saveReviewed)
            return
        if plan is None:
            return
        jobs = list(plan.jobs)
        unredacted = plan.unredacted
        if unredacted and not self.alerts.ask(
                'Save unredacted copies?',
                f'{unredacted} reviewed image(s) have no selected boxes. '
                'Save them as unredacted PNG copies?'):
            return

        include_log = self.session.preferences.include_log
        snapshots = [
            (entry, export.snapshot(entry.path, target, entry.boxes, entry.selected,
                                    entry.method, stamp=entry.stamp))
            for entry, target in jobs
        ]

        def operation(job):
            entry, snapshot = job
            snapshot.target.parent.mkdir(parents=True, exist_ok=True)
            export.write_copy(snapshot, include_log=include_log)

        def accept(index, result, error):
            entry, target = jobs[index]
            snapshot = snapshots[index][1]
            if error:
                self.alerts.set_status(f'{entry.path.name} · {error}')
            elif workflows.export_succeeded(entry, snapshot):
                entry.saved = True
                entry.error = ''
                self.alerts.set_status(f'Saved {target.name} to {target.parent}')

        self.jobs.run(
            'Saving', snapshots, operation, accept,
            metrics_settings={'method': self.session.preferences.method, 'coordinate_logs': include_log},
            rows=self._folder_rows(),
        )

    def _method_changed(self):
        if not self.session.entries:
            if self.session.review.confirmed:
                self._refresh_display()
            return
        method = self.session.preferences.method
        for entry in self.session.entries:
            if entry.method != method:
                entry.method = method
                entry.reviewed = entry.saved = False
        self.session.review.confirmed = False
        self._refresh_display()
        self._emit_review()
        self._folder_model.refresh()
        self.folderChanged.emit()
        self.alerts.set_status(
            f'{method} will be used across the folder. '
            'Confirm the updated redactions before saving.'
        )
