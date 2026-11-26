from pathlib import Path

from PIL import Image

from .. import images, workflows


class BatchTools:
    def __init__(self, owner):
        self.owner = owner

    def copyBoxesToFolder(self):
        owner = self.owner
        if (owner.session.jobs.busy or owner.session.active is None
                or owner.session.review.image is None):
            return
        boxes = owner.session.review.selected_boxes()
        if not boxes:
            owner.alerts.info('Copy selected boxes',
                             'Select or draw the boxes you want to copy first.')
            return
        targets = [entry for index, entry in enumerate(owner.session.entries)
                   if index != owner.session.active]
        if not targets:
            owner.alerts.info('Copy selected boxes',
                             'Open a folder with at least two images.')
            return
        if not owner.alerts.ask(
                'Copy selected boxes?',
                f'Copy {len(boxes)} selected box{"" if len(boxes) == 1 else "es"} '
                'to the same positions on other images of the same size? '
                'Check that the content lines up before confirming and saving.'):
            return
        size = owner.session.review.image.size
        applied = skipped = unchanged = 0
        review = owner.session.facades.review

        def operation(job):
            path, expected = job
            stamp = images.file_stamp(path)
            if expected is not None and stamp != expected:
                raise ValueError(
                    f'{path.name} changed. Reopen the folder before copying boxes.'
                )
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
            if (owner.session.active is not None
                    and owner.session.entries[owner.session.active] is entry
                    and owner.session.review.image is not None):
                review.invalidate()

        def finish():
            return (f'{applied} updated · {skipped} skipped (size or source changed) · '
                    f'{unchanged} already selected')

        owner.session.jobs.run(
            'Copying boxes',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=owner.session.facades.folder.rows(),
        )

    def match_boxes_to_folder(self, anchor):
        owner = self.owner
        try:
            from ..visual_anchor import locate_anchor, prepare_anchor, relocate_boxes
        except ImportError:
            owner.alerts.error(
                'Visual matching unavailable',
                'Install the project dependencies with pip install -e . and restart.',
            )
            return
        boxes = owner.session.review.selected_boxes()
        if not boxes:
            owner.alerts.set_status('Select boxes to match across the folder.')
            return
        left, top, right, bottom = anchor
        if right - left < 20 or bottom - top < 20:
            owner.alerts.set_status(
                'Anchor too small. Click Match boxes by visual anchor and drag around '
                'a larger area.'
            )
            return
        try:
            patch = prepare_anchor(owner.session.review.image, anchor)
        except ValueError as error:
            owner.alerts.set_status(str(error))
            return
        targets = [entry for index, entry in enumerate(owner.session.entries)
                   if index != owner.session.active]
        matched = skipped = 0
        review = owner.session.facades.review

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
            if (changed and owner.session.active is not None
                    and owner.session.entries[owner.session.active] is entry):
                review.invalidate()

        def finish():
            return f'{matched} matched · {skipped} skipped (no reliable placement)'

        owner.session.jobs.run(
            'Matching visual anchor',
            [(entry.path, entry.stamp) for entry in targets],
            operation, accept, finish, rows=owner.session.facades.folder.rows(),
        )

    def confirmAll(self):
        owner = self.owner
        if not owner.session.jobs.busy and owner.session.entries:
            owner.confirm_entries(owner.session.entries, 'Confirm all')

    def confirm_entries(self, entries, title):
        owner = self.owner
        owner.session.store_active()
        pending = workflows.eligible_for_confirmation(entries)
        if not pending:
            owner.alerts.info(
                title,
                'No eligible images are awaiting confirmation. Check whether they are '
                'already reviewed, have no selected boxes, or have a scan error.',
            )
            return
        if not owner.alerts.ask(
                title,
                workflows.confirmation_prompt(pending, owner.session.preferences.method)):
            return
        for entry in pending:
            entry.confirm(True)
        owner.session.facades.review.apply_confirmation()
        owner.session.facades.folder.refresh_and_emit()
        count = len(pending)
        noun = 'image' if count == 1 else 'images'
        pronoun = 'it' if count == 1 else 'them'
        owner.alerts.set_status(
            f'Confirmed {count} {noun}. Use Save reviewed to export {pronoun}.'
        )
