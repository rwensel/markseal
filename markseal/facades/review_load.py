from pathlib import Path

from PySide6.QtGui import QImage

from .. import documents, redaction
from ..pdf_review import PdfReview


class ReviewLoad:
    def __init__(self, owner):
        self.owner = owner

    def invalidate_export(self):
        self.owner.last_export = None
        self.owner.last_verify = None

    def refresh_display(self):
        owner = self.owner
        image = owner.session.review.image
        if image is not None and owner.session.review.confirmed:
            image = redaction.apply_redactions(
                image, owner.session.review.selected_boxes(), owner.session.preferences.method
            )
        if image is None:
            owner._display_qimage = QImage()
        else:
            owner._display_qimage = self._pil_to_qimage(image)
        owner.image_revision += 1
        owner.imageRevisionChanged.emit()

    def _pil_to_qimage(self, image):
        owner = self.owner
        if image.mode != 'RGB':
            image = image.convert('RGB')
        raw = image.tobytes('raw', 'RGB')
        return QImage(
            raw, image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
        ).copy()

    def load_image(self, image, path, pasted=False):
        owner = self.owner
        self._close_pdf()
        owner.session.pasted_image = pasted
        owner.session.review.load(image, path)
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.imageChanged.emit()
        owner.emit_review()
        owner.emit_view()

    def load_pdf(self, path):
        owner = self.owner
        pdf = PdfReview(path)
        try:
            state = pdf.open()
        except Exception:
            pdf.close()
            raise
        self._close_pdf()
        owner._pdf = pdf
        owner.session.pasted_image = False
        owner.session.review.load(state.page.image, path)
        owner.session.review.boxset = state.boxset
        owner.session.review.confirmed = state.confirmed
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.imageChanged.emit()
        owner.emit_review()
        owner.emit_view()

    def _switch_pdf_page(self, index):
        owner = self.owner
        if owner._pdf is None or owner.session.jobs.busy:
            return
        if not 0 <= index < owner._pdf.page_count or index == owner._pdf.page_index:
            return
        try:
            state = owner._pdf.switch(
                index, current=owner.session.review.boxset,
                confirmed=owner.session.review.confirmed)
        except documents.PdfError as error:
            owner.alerts.error('Cannot render PDF page', str(error))
            return
        owner.session.review.load(state.page.image, owner._pdf.path)
        owner.session.review.boxset = state.boxset
        owner.session.review.confirmed = state.confirmed
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.imageChanged.emit()
        owner.emit_review()
        owner.emit_view()
        owner.alerts.set_status(
            f'Page {index + 1} of {owner._pdf.page_count}.')

    def previousPdfPage(self):
        owner = self.owner
        if owner._pdf is not None:
            self._switch_pdf_page(owner._pdf.page_index - 1)

    def nextPdfPage(self):
        owner = self.owner
        if owner._pdf is not None:
            self._switch_pdf_page(owner._pdf.page_index + 1)

    def goToPdfPage(self, page):
        owner = self.owner
        self._switch_pdf_page(page - 1)

    def unsaved_pdf_work(self):
        owner = self.owner
        return owner._pdf is not None and owner._pdf.unsaved()

    def _close_pdf(self):
        owner = self.owner
        if owner._pdf is not None:
            owner._pdf.close()
        owner._pdf = None

    def adopt_entry(self, entry):
        owner = self.owner
        self._close_pdf()
        owner.session.pasted_image = False
        owner.session.review.path = entry.path
        owner.session.review.boxset = entry.boxset
        owner.session.review.confirmed = entry.reviewed
        owner.session.review.viewport.clear()
        owner._load.invalidate_export()

    def set_entry_image(self, image):
        owner = self.owner
        owner.session.review.image = image
        if image is not None:
            owner.session.review.viewport.reset(image.size)
            owner._load.refresh_display()

    def invalidate(self):
        owner = self.owner
        owner.session.review.confirmed = False
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.emit_review()

    def apply_confirmation(self):
        owner = self.owner
        if owner.session.active is not None and owner.session.review.image is not None:
            owner.session.review.confirmed = owner.session.entries[owner.session.active].reviewed
            owner._load.refresh_display()
            owner.emit_review()

    def method_changed(self):
        owner = self.owner
        if not owner.session.entries:
            owner._load.invalidate_export()
            if owner.session.review.confirmed:
                owner._load.refresh_display()
            return
        method = owner.session.preferences.method
        for entry in owner.session.entries:
            entry.set_method(method)
        owner.session.review.confirmed = False
        owner._load.refresh_display()
        owner.emit_review()
        owner.alerts.set_status(
            f'{method} will be used across the folder. '
            'Confirm the updated redactions before saving.'
        )

    def selection_changed(self):
        owner = self.owner
        owner.confirmLabelChanged.emit()
