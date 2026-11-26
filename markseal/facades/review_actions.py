from pathlib import Path
from queue import Queue

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from ..export_copy import CopyRequest, ExportCopies
from ..performance_log import PerformanceRun
from ..scan import Scan, ScanError


class ReviewActions:
    def __init__(self, owner):
        self.owner = owner

    def confirmSelection(self):
        owner = self.owner
        if owner.session.jobs.busy or owner.session.review.image is None:
            return
        selected = sorted(owner.session.row_selection) if owner.session.entries else ()
        if len(selected) > 1:
            owner.batch.confirm_entries(
                [owner.session.entries[index] for index in selected],
                'Confirm selected images',
            )
            return
        owner.session.review.confirmed = True
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.session.store_active()
        owner.emit_review()
        owner.alerts.set_status(
            f'{len(owner.session.review.selected)} '
            f'{"box" if len(owner.session.review.selected) == 1 else "boxes"} '
            'applied in preview. Save, or click to change your selection.'
        )

    def redactAll(self):
        owner = self.owner
        review = owner.session.review
        if owner.session.jobs.busy or review.image is None or review.confirmed:
            return
        if not review.boxes:
            return
        review.select_all()
        review.confirmed = True
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.session.store_active()
        owner.emit_review()
        count = len(review.selected)
        noun = 'box' if count == 1 else 'boxes'
        prefix = 'All ' if count > 1 else ''
        owner.alerts.set_status(
            f'{prefix}{count} {noun} applied in preview. '
            'Save, or click to change your selection.'
        )






    def copyRedacted(self):
        owner = self.owner
        if owner.session.review.image is None:
            return
        if not owner.session.review.confirmed:
            owner.alerts.set_status('Confirm selection to copy the redacted image.')
            return
        if not owner.session.review.selected and not owner.alerts.ask(
                'No boxes selected', 'Copy the unredacted image?'):
            return
        if owner._display_qimage.isNull():
            owner.alerts.error('Copy failed', 'The preview is not available.',
                              'RETRY', owner.copyRedacted)
            return
        QGuiApplication.clipboard().setImage(owner._display_qimage.copy())
        count = len(owner.session.review.selected)
        if count:
            noun = 'box' if count == 1 else 'boxes'
            owner.alerts.set_status(
                f'Copied the redacted image with {count} {noun} to the clipboard.'
            )
        else:
            owner.alerts.set_status('Copied the unredacted image to the clipboard.')

    def save(self):
        owner = self.owner
        if owner.session.jobs.busy or owner.session.review.image is None:
            return
        if owner.session.active is None:
            owner.save_single()
            return
        owner.session.store_active()
        entry = owner.session.entries[owner.session.active]
        if owner.session.review.image is None or not entry.reviewed:
            owner.alerts.set_status('Confirm the selection on this image before saving.')
            return
        owner.batch.save_active()

    def save_single(self):
        owner = self.owner
        if owner.session.review.image is None:
            return
        if not owner.session.review.confirmed:
            owner.alerts.set_status('Confirm the selection before saving.')
            return
        if not owner.session.review.selected and not owner.alerts.ask(
                'No boxes selected', 'Save an unredacted copy?'):
            return
        initial = owner.session.review.path.stem + '_redacted.png'
        page = owner.pdfPage if owner._pdf is not None else None
        if page is not None:
            initial = f'{owner.session.review.path.stem}_page-{page:03d}_redacted.png'
        copies = ExportCopies(owner.session.preferences)

        def choose(target):
            chosen, _ = QFileDialog.getSaveFileName(
                None, 'Save redacted copy', str(target), 'PNG image (*.png)'
            )
            return chosen or None

        request = CopyRequest(
            source=owner.session.review.path,
            method=owner.session.preferences.method,
            boxes=tuple(owner.session.review.boxes),
            selected=frozenset(owner.session.review.selected),
            image=owner.session.review.image,
            pasted=owner.session.pasted_image,
            page=page,
            target=Path(initial),
        )
        try:
            plan = copies.plan(
                [request], output_directory=Path('.'), choose=choose,
                allow_overwrite=True,
            )
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            owner.alerts.error('Cannot save image', str(error), 'RETRY', owner.save)
            return
        if plan is None:
            return
        target = plan.jobs[0].target
        if target.resolve() == owner.session.review.path.resolve():
            owner.alerts.error('Choose a different file',
                              'The original image cannot be overwritten.')
            return
        include_log = plan.include_log
        trace = PerformanceRun('Saving image', 1, {
            'method': owner.session.preferences.method, 'coordinate_logs': include_log,
        })
        owner.session.jobs.begin_manual('Saving copy')
        owner.alerts.set_status('Saving the redacted copy…')
        QGuiApplication.processEvents()
        error = None
        try:
            with trace.image(0):
                job = copies.snapshot(plan.jobs[0])
                copies.write(job, include_log=include_log, overwrite=True)
        except Exception as exc:
            error = exc
        finally:
            trace.finish()
            owner.session.jobs.end_manual()
        if error is not None:
            owner.alerts.error('Save failed', str(error), 'RETRY', owner.save)
            return
        owner.last_export = target
        owner.last_verify = None
        note = ' and coordinate log' if include_log else ''
        warning = {
            'Blur': 'blurred text can sometimes be recovered.',
            'Erase': 'erased text is filled with nearby pixels; check the result.',
        }.get(owner.session.preferences.method, 'pixelated text can sometimes be recovered.')
        owner.alerts.info(
            'Saved',
            f'Saved the redacted PNG{note}. Review before sharing; {warning}',
        )

    def verifyCurrent(self):
        owner = self.owner
        if owner._pdf is not None:
            owner.alerts.info(
                'Verify unavailable',
                'Verify compares a PNG export with an image source. '
                'PDF page exports do not have an image original to compare.',
            )
            return
        source = owner.session.review.path
        if owner.session.pasted_image or source is None:
            owner.alerts.set_status(
                'Cannot verify a pasted image: there is no original file to compare.'
            )
            return
        path = owner.last_export
        if path is None or not Path(path).is_file():
            owner.alerts.set_status('Save the redacted copy first, then verify it.')
            return
        if not owner.session.preferences.include_log:
            owner.alerts.info(
                'Verify needs a coordinate log',
                'This export was saved without a coordinate log. '
                'Turn on Include coordinate log in Settings, save the export again, '
                'then verify.',
            )
            return
        result = ExportCopies(owner.session.preferences).verify(
            Path(path), Path(source).parent)
        owner.last_verify = result
        owner.verifyResult.emit(result)
        name = Path(path).name
        if result['issue']:
            owner.alerts.error('Verify failed', f'{name}: {result["issue"]}')
        elif result['outside_pixels_unchanged']:
            owner.alerts.set_status(
                f'Verified {name}: pixels outside redactions unchanged.'
            )
        else:
            owner.alerts.error('Verify failed', f'{name}: pixels outside redactions changed.')
