from threading import Event

from .. import workflows
from ..scan import Scan, ScanError


class BatchScan:
    def __init__(self, owner):
        self.owner = owner

    def scanAll(self):
        owner = self.owner
        owner.start_scan(owner.session.entries, follow=True)

    def scanSelected(self):
        owner = self.owner
        if owner.session.jobs.busy:
            return
        selected = sorted(owner.session.row_selection)
        if not selected:
            owner.alerts.info('Scan selected',
                             'Select one or more images in the folder list first.')
            return
        owner.start_scan([owner.session.entries[index] for index in selected],
                        rescan=True, follow=True)

    def rescanAll(self):
        owner = self.owner
        if not owner.session.jobs.busy and owner.session.entries and owner.alerts.ask(
                'Rescan all images?',
                'Keep existing boxes and add new suggestions. '
                'All rescanned images will need review again.'):
            owner.start_scan(owner.session.entries, rescan=True, follow=True)

    def start_scan(self, entries, rescan=False, *, follow=False, area=None):
        owner = self.owner
        if owner.session.jobs.busy:
            return
        owner.session.store_active()
        plan = workflows.plan_scan(
            owner.session.entries, entries, rescan=rescan, area=area
        )
        pending = plan.entries
        if not pending:
            owner.alerts.info(
                'Folder scan',
                'Every image has been scanned or manually reviewed. '
                'Use Find likely identifiers to rescan an image.',
            )
            return
        try:
            scan = Scan(
                owner.session.preferences,
                engine_factory=owner.session.scan_engine,
            )
        except ScanError as error:
            if error.kind == 'unavailable':
                owner.alerts.error(
                    'OCR unavailable', str(error), 'RETRY',
                    lambda: owner.start_scan(
                        entries, rescan=rescan, follow=follow, area=area),
                )
            else:
                owner.alerts.error(
                    'Invalid detection settings', str(error), 'OPEN SETTINGS',
                    owner.session.facades.settings.requestSettings)
            return
        cancel = Event()
        processed = []
        area_completed = False
        review = owner.session.facades.review

        def show_image(index):
            row = plan.rows[pending[index].path]
            owner.session.facades.folder.activate_entry(int(row))

        def operation(job):
            path, stamp = job
            result = scan.file(path, stamp, cancel=cancel, area=area)
            return result.stamp, result.found, result.incomplete

        def accept(index, result, error):
            nonlocal area_completed
            entry = pending[index]
            if error:
                if area is None:
                    entry.error = 'Scan failed'
                owner.alerts.set_status(f'{entry.path.name} · {error}')
                return
            outcome = workflows.apply_scan_result(entry, result, area=area)
            if outcome.error:
                return
            area_completed = area is not None
            if (owner.session.active is not None
                    and entry is owner.session.entries[owner.session.active]
                    and owner.session.review.image is not None):
                if outcome.changed:
                    review.invalidate()
                    review.emit_view()
                detail = (f' Partial scan: {", ".join(outcome.incomplete)}.'
                          if outcome.incomplete else '')
                owner.alerts.set_status(
                    f'{entry.path.name} · {outcome.count} new OCR suggestions.{detail} '
                    'Review before confirming.'
                )

        def track_result(index, result, error):
            accept(index, result, error)
            processed.append(pending[index])

        def finish():
            return workflows.scan_summary(
                processed, area=area, area_completed=area_completed
            )

        owner.session.jobs.run(
            plan.label, list(plan.jobs), operation, track_result, finish,
            cancel=cancel, show_image=show_image if follow else None,
            metrics_settings=owner.session.scan_metrics(), rows=plan.rows,
        )

    def scan_entry(self, entry, rescan=False, area=None):
        owner = self.owner
        owner.start_scan([entry], rescan=rescan, area=area)

    def cancelScan(self):
        owner = self.owner
        owner.session.jobs.cancel()
