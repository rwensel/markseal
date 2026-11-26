"""The current image's review: boxes, selection, viewport, and clipboard."""
from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QImage

from .review_actions import ReviewActions
from .review_scan_actions import ReviewScanActions
from .review_load import ReviewLoad
from .review_view import ReviewView


class ReviewFacade(QObject):
    imageChanged = Signal()
    imageRevisionChanged = Signal()
    reviewChanged = Signal()
    viewChanged = Signal()
    captureChanged = Signal()
    confirmLabelChanged = Signal()
    verifyResult = Signal(dict)

    def __init__(self, session, alerts, parent=None):
        super().__init__(parent)
        self.session = session
        self.alerts = alerts
        self.capture = 'none'
        self.drag = None
        self._panning = False
        self.image_revision = 0
        self._display_qimage = QImage()
        self.batch = None
        self.last_export = None
        self.last_verify = None
        self._pdf = None
        self._view = ReviewView(self)
        self._actions = ReviewActions(self)
        self._scan_actions = ReviewScanActions(self)
        self._load = ReviewLoad(self)


    @Property(bool, notify=imageChanged)
    def hasImage(self):
        return self.session.review.image is not None

    @Property(bool, notify=imageChanged)
    def isPdf(self):
        return self._pdf is not None

    @Property(int, notify=imageChanged)
    def pdfPage(self):
        return self._pdf.page_index + 1 if self._pdf is not None else 0

    @Property(int, notify=imageChanged)
    def pdfPageCount(self):
        return self._pdf.page_count if self._pdf is not None else 0

    @Property(bool, notify=imageChanged)
    def canPreviousPdfPage(self):
        return self._pdf is not None and self._pdf.page_index > 0

    @Property(bool, notify=imageChanged)
    def canNextPdfPage(self):
        return (self._pdf is not None
                and self._pdf.page_index + 1 < self._pdf.page_count)

    @Property(bool, notify=imageChanged)
    def canVerify(self):
        return self._pdf is None

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

    @Property(str, notify=confirmLabelChanged)
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

    def display_qimage(self):
        return self._display_qimage



    def emit_review(self):
        self.reviewChanged.emit()

    def emit_view(self):
        self.viewChanged.emit()


    def load_image(self, image, path, pasted=False): self._load.load_image(image, path, pasted)
    def load_pdf(self, path): self._load.load_pdf(path)

    @Slot()
    def previousPdfPage(self): self._load.previousPdfPage()
    @Slot()
    def nextPdfPage(self): self._load.nextPdfPage()
    @Slot(int)
    def goToPdfPage(self, page): self._load.goToPdfPage(page)
    def unsaved_pdf_work(self):
        return self._load.unsaved_pdf_work()


    def adopt_entry(self, entry): self._load.adopt_entry(entry)
    def set_entry_image(self, image): self._load.set_entry_image(image)
    def invalidate(self): self._load.invalidate()
    def apply_confirmation(self): self._load.apply_confirmation()
    def method_changed(self): self._load.method_changed()
    def selection_changed(self): self._load.selection_changed()
    @Slot(int, int)
    def setViewSize(self, width, height): self._view.setViewSize(width, height)
    @Slot(int, int)
    def press(self, x, y): self._view.press(x, y)
    @Slot(int, int)
    def move(self, x, y): self._view.move(x, y)
    @Slot(int, int)
    def release(self, x, y): self._view.release(x, y)
    @Slot(int, int, int)
    def zoomAt(self, x, y, delta): self._view.zoomAt(x, y, delta)
    @Slot(int)
    def zoomStep(self, direction): self._view.zoomStep(direction)
    @Slot()
    def zoomFit(self): self._view.zoomFit()
    @Slot(int, int)
    def panStep(self, dx, dy): self._view.panStep(dx, dy)
    @Slot()
    def selectAllBoxes(self): self._view.selectAllBoxes()
    @Slot()
    def selectNoBoxes(self): self._view.selectNoBoxes()
    @Slot(int, int)
    def beginPan(self, x, y): self._view.beginPan(x, y)
    @Slot(int, int)
    def movePan(self, x, y): self._view.movePan(x, y)
    @Slot()
    def endPan(self): self._view.endPan()
    @Slot(int)
    def toggleBox(self, index): self._view.toggleBox(index)
    @Slot(int)
    def removeBox(self, index): self._view.removeBox(index)
    @Slot()
    def undo(self): self._view.undo()
    @Property(bool, notify=reviewChanged)
    def canRedo(self):
        return self.session.review.can_redo()

    @Slot()
    def redo(self): self._view.redo()
    @Slot()
    def editBoxes(self): self._view.editBoxes()
    @Slot()
    def clearBoxes(self): self._view.clearBoxes()
    @Slot()
    def confirmSelection(self): self._actions.confirmSelection()
    @Slot()
    def redactAll(self): self._actions.redactAll()
    @Slot()
    def cancelCapture(self): self._view.cancelCapture()
    def cancel_capture(self): self._view.cancel_capture()
    @Slot()
    def find(self): self._scan_actions.find()
    def start_single_scan(self, area=None): self._scan_actions.start_single_scan(area)
    @Slot()
    def beginScanArea(self): self._scan_actions.beginScanArea()
    @Slot()
    def beginAnchorCapture(self): self._scan_actions.beginAnchorCapture()
    @Slot()
    def beginLearnPattern(self): self._scan_actions.beginLearnPattern()
    @Slot()
    def copyRedacted(self): self._actions.copyRedacted()
    @Slot()
    def save(self): self._actions.save()
    def save_single(self): self._actions.save_single()
    @Slot()
    def verifyCurrent(self):
        self._actions.verifyCurrent()
