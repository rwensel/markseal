from queue import Queue

from ..scan import Scan, ScanError


class ReviewScanActions:
    def __init__(self, owner):
        self.owner = owner

    def find(self):
        owner = self.owner
        if owner.session.jobs.busy or owner.session.review.image is None:
            return
        if owner.session.active is not None:
            owner.batch.scan_entry(owner.session.entries[owner.session.active], rescan=True)
            return
        owner.start_single_scan()

    def start_single_scan(self, area=None):
        owner = self.owner
        if owner.session.review.image is None or owner.session.jobs.busy:
            return
        owner._load.invalidate_export()
        try:
            scan = Scan(
                owner.session.preferences,
                engine_factory=owner.session.scan_engine,
            )
        except ScanError as error:
            if error.kind == 'unavailable':
                owner.alerts.error('OCR unavailable', str(error), 'RETRY',
                                  lambda: owner.start_single_scan(area=area))
            else:
                owner.alerts.error('Invalid detection settings', str(error), 'OPEN SETTINGS',
                                  owner.session.facades.settings.requestSettings)
            return
        stages = Queue()
        info = {'added': None, 'incomplete': [], 'error': None}
        label = 'Scanning area' if area is not None else 'Scanning image'

        def operation(job):
            result = scan.image(
                owner.session.review.image, area=area, progress=stages.put)
            return None, result.found, list(result.incomplete)

        def accept(index, result, error):
            if error is not None:
                info['error'] = error
                owner.alerts.set_status(f'Scan failed: {error}')
                return
            _, found, incomplete = result
            added = owner.session.review.add_suggestions(found)
            owner._load.refresh_display()
            owner.session.store_active()
            owner.emit_review()
            owner.emit_view()
            info['added'] = added
            info['incomplete'] = incomplete
            detail = f' Incomplete OCR passes: {", ".join(incomplete)}.' if incomplete else ''
            if added:
                noun = 'suggestion' if added == 1 else 'suggestions'
                message = f'{added} selected {noun} added.'
            else:
                message = 'No new suggestions found.'
            owner.alerts.set_status(f'{message}{detail} Review the entire image.')

        def finish():
            if info['error'] is not None:
                return 'Scan failed'
            count = info['added'] or 0
            if count == 0:
                return 'No new OCR suggestions'
            noun = 'suggestion' if count == 1 else 'suggestions'
            return f'{count} new OCR {noun}'

        def complete():
            if info['error'] is not None:
                owner.alerts.error(
                    'Local OCR failed', f'Text recognition failed: {info["error"]}',
                    'RETRY', lambda: owner.start_single_scan(area=area),
                )
                return
            if info['added'] is None:
                return
            detail = (f' Incomplete OCR passes: {", ".join(info["incomplete"])}.'
                      if info['incomplete'] else '')
            added = info['added']
            if added:
                noun = 'box' if added == 1 else 'boxes'
                message = f'Added {added} selected {noun}.{detail} Review the image before confirming.'
            else:
                message = f'No new boxes were added.{detail} Review the image or draw a box.'
            owner.alerts.info('Review required', message)

        owner.alerts.set_status(
            'Scanning the selected area. Progress is shown above the screenshot.'
            if area is not None
            else 'Scanning image. Progress is shown above the screenshot.'
        )
        owner.session.jobs.run(
            label, [owner.session.review.path], operation, accept, finish,
            metrics_settings=owner.session.scan_metrics(), stage_queue=stages,
            complete=complete, report_failures=False,
        )

    def beginScanArea(self):
        owner = self.owner
        if owner.session.jobs.busy or owner.session.review.image is None:
            return
        owner.cancel_capture()
        owner.capture = 'area'
        owner.captureChanged.emit()
        owner.alerts.set_status(
            'Drag around the text to scan. For small labels, draw a tight box around '
            'a single row. Esc cancels.'
        )

    def beginAnchorCapture(self):
        owner = self.owner
        if (owner.session.jobs.busy or owner.session.active is None
                or owner.session.review.image is None):
            return
        if not owner.session.review.selected or len(owner.session.entries) < 2:
            owner.alerts.info(
                'Match by visual anchor',
                'Select redaction boxes on one image in a folder with at least two images.',
            )
            return
        owner.cancel_capture()
        owner.editBoxes()
        owner.capture = 'anchor'
        owner.captureChanged.emit()
        owner.alerts.set_status(
            'Drag around a distinctive logo or label near the boxes. Esc cancels.'
        )

    def beginLearnPattern(self):
        owner = self.owner
        if owner.session.jobs.busy or owner.session.review.image is None:
            return
        owner.cancel_capture()
        owner.capture = 'learn'
        owner.captureChanged.emit()
        owner.alerts.set_status(
            'Drag around the text to block. The area is read locally and turned into '
            'a pattern. Esc cancels.'
        )
