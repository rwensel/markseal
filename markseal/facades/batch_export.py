from PySide6.QtWidgets import QFileDialog

from ..export_copy import CopyRequest, ExportCopies, export_succeeded


class BatchExport:
    def __init__(self, owner):
        self.owner = owner

    def saveReviewed(self):
        owner = self.owner
        if owner.session.jobs.busy:
            return
        owner.session.store_active()
        pending = [(index, entry) for index, entry in enumerate(owner.session.entries)
                   if entry.reviewed and not entry.saved]
        if not pending:
            owner.alerts.info('Save reviewed',
                             'Confirm the selection on each image you want to save.')
            return
        self.export_entries(pending)

    def save_active(self):
        owner = self.owner
        entry = owner.session.entries[owner.session.active]
        self.export_entries([(owner.session.active, entry)], individual=True)

    def export_entries(self, pending, individual=False):
        owner = self.owner
        def choose(target):
            chosen, _ = QFileDialog.getSaveFileName(
                None, 'Save redacted copy', str(target), 'PNG image (*.png)'
            )
            return chosen or None

        def output_for(entry):
            watches = getattr(owner.session.facades, 'watches', None)
            if watches is not None:
                directory_for = getattr(watches, 'output_for_source', None)
                if directory_for is not None:
                    directory = directory_for(entry.path)
                    if directory is not None:
                        return directory
            return owner.session.output_directory

        copies = ExportCopies(owner.session.preferences)
        try:
            plan = copies.plan(
                [CopyRequest.from_entry(entry) for _index, entry in pending],
                output_directory=output_for,
                choose=choose if individual else None,
            )
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            title = 'Cannot save image' if individual else 'Cannot save images'
            retry = owner.save_active if individual else owner.saveReviewed
            owner.alerts.error(title, str(error), 'RETRY', retry)
            return
        if plan is None:
            return
        unredacted = plan.unredacted
        if unredacted and not owner.alerts.ask(
                'Save unredacted copies?',
                f'{unredacted} reviewed image{"" if unredacted == 1 else "s"} '
                f'{"has" if unredacted == 1 else "have"} no selected boxes. '
                'Save them as unredacted PNG copies?'):
            return

        snapshots = [
            (planned.request.entry, copies.snapshot(planned))
            for planned in plan.jobs
        ]

        def operation(job):
            _entry, snapshot = job
            snapshot.target.parent.mkdir(parents=True, exist_ok=True)
            copies.write(snapshot, include_log=plan.include_log)

        def accept(index, result, error):
            planned = plan.jobs[index]
            entry = planned.request.entry
            target = planned.target
            snapshot = snapshots[index][1]
            if error:
                owner.alerts.set_status(f'{entry.path.name} · {error}')
            elif export_succeeded(entry, snapshot):
                entry.mark_saved(target)
                entry.error = ''
                owner.session.facades.review.last_export = target
                watches = getattr(owner.session.facades, 'watches', None)
                if watches is not None:
                    watches.note_export(entry.path, target)
                owner.alerts.set_status(f'Saved {target.name} to {target.parent}')

        owner.session.jobs.run(
            'Saving', snapshots, operation, accept,
            metrics_settings={'method': owner.session.preferences.method,
                              'coordinate_logs': plan.include_log},
            rows=owner.session.facades.folder.rows(),
        )

    def verifyReviewed(self):
        owner = self.owner
        if owner.session.jobs.busy:
            return
        owner.session.store_active()
        saved = [entry for entry in owner.session.entries
                 if entry.saved and entry.export_path is not None]
        copies = ExportCopies(owner.session.preferences)
        files = []
        for entry in saved:
            target = entry.export_path
            if target.is_file():
                files.append(copies.verify(target, entry.path.parent))
        result = {
            'files': files,
            'all_ok': bool(files) and all(
                item['outside_pixels_unchanged'] and not item['issue'] for item in files),
        }
        owner.last_verify = result
        owner.verifyResult.emit(result)
        if not files:
            owner.alerts.set_status(
                'No exported copies found to verify. Save reviewed images first.'
            )
        elif result['all_ok']:
            count = len(files)
            noun = 'export' if count == 1 else 'exports'
            owner.alerts.set_status(
                f'Verified {count} {noun}: pixels outside redactions unchanged.'
            )
        else:
            problems = [
                f'{item["export"]}: '
                f'{item["issue"] or "pixels changed outside redactions"}'
                for item in files
                if item['issue'] or not item['outside_pixels_unchanged']
            ]
            owner.alerts.error('Verify failed', '; '.join(problems))
