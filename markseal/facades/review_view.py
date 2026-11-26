class ReviewView:
    def __init__(self, owner):
        self.owner = owner

    def status(self):
        owner = self.owner
        name = owner.session.review.path.name if owner.session.review.path else ''
        return (f'{name}: {len(owner.session.review.selected)} selected of '
                f'{len(owner.session.review.boxes)}. Confirm to apply.')

    def setViewSize(self, width, height):
        owner = self.owner
        owner.session.review.set_view_size(width, height)
        owner.emit_view()

    def press(self, x, y):
        owner = self.owner
        if owner.capture != 'none' and owner.session.review.image is not None:
            owner.session.review.viewport.begin_drag(x, y)
            owner.drag = (x, y, 0, 0)
            owner.emit_view()
            return
        owner.session.review.press(x, y)

    def move(self, x, y):
        owner = self.owner
        if owner.session.review.viewport.pan_origin is not None:
            if owner.session.review.pan_move(x, y):
                owner.emit_view()
            return
        rect = owner.session.review.viewport.drag_rect(x, y)
        if rect is not None:
            owner.drag = rect
            owner.emit_view()

    def release(self, x, y):
        owner = self.owner
        if owner._panning:
            if owner.session.review.pan_end():
                owner._panning = False
                owner.viewChanged.emit()
            return
        if (owner.capture != 'none' and owner.session.review.viewport.drag_origin is not None
                and owner.session.review.image is not None):
            capture = owner.capture
            anchor = owner.session.review.viewport.drag_region(x, y)
            owner.cancel_capture()
            if capture == 'area':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    owner.alerts.set_status(
                        'Area too small. Open More, choose Scan a region, and draw around the text again.'
                    )
                elif owner.session.active is None:
                    owner.start_single_scan(area=anchor)
                else:
                    owner.batch.scan_entry(
                        owner.session.entries[owner.session.active], rescan=True, area=anchor
                    )
            elif capture == 'learn':
                if anchor[2] - anchor[0] < 4 or anchor[3] - anchor[1] < 4:
                    owner.alerts.set_status(
                        'Area too small. Draw a tight box around the text you want to block again.'
                    )
                else:
                    owner.session.facades.settings.learn_pattern(anchor)
            else:
                owner.batch.match_boxes_to_folder(anchor)
            return
        owner.drag = None
        action = owner.session.review.release(x, y)
        if action != 'none':
            owner._load.refresh_display()
            owner.session.store_active()
            owner.emit_review()
            owner.alerts.set_status(owner._view.status())
        owner.emit_view()

    def zoomAt(self, x, y, delta):
        owner = self.owner
        if owner.session.review.zoom_at(x, y, 1 if delta > 0 else -1):
            owner.emit_view()

    def zoomStep(self, direction):
        owner = self.owner
        if owner.session.review.image is None:
            return
        viewport = owner.session.review.viewport
        if owner.session.review.zoom_at(
                viewport.view_width / 2, viewport.view_height / 2, direction):
            owner.emit_view()

    def zoomFit(self):
        owner = self.owner
        if owner.session.review.image is None:
            return
        viewport = owner.session.review.viewport
        viewport.zoom = 1.0
        viewport.refit()
        owner.emit_view()

    def panStep(self, dx, dy):
        owner = self.owner
        if owner.session.review.image is None or owner.session.review.zoom <= 1.0:
            return
        viewport = owner.session.review.viewport
        viewport.offset_x += dx
        viewport.offset_y += dy
        viewport.clamp_offsets()
        owner.emit_view()

    def selectAllBoxes(self):
        owner = self.owner
        if owner.session.review.select_all():
            owner._load.refresh_display()
            owner.session.store_active()
            owner.emit_review()
            owner.alerts.set_status(owner._view.status())

    def selectNoBoxes(self):
        owner = self.owner
        if owner.session.review.select_none():
            owner._load.refresh_display()
            owner.session.store_active()
            owner.emit_review()
            owner.alerts.set_status(owner._view.status())

    def beginPan(self, x, y):
        owner = self.owner
        if owner.session.review.pan_begin(x, y):
            owner._panning = True
            owner.viewChanged.emit()

    def movePan(self, x, y):
        owner = self.owner
        if owner.session.review.pan_move(x, y):
            owner.viewChanged.emit()

    def endPan(self):
        owner = self.owner
        if owner.session.review.pan_end():
            owner._panning = False
            owner.viewChanged.emit()

    def toggleBox(self, index):
        owner = self.owner
        if owner.session.review.confirmed:
            return
        if owner.session.review.toggle_box(index):
            owner._load.invalidate_export()
            owner.session.store_active()
            owner.emit_review()
            owner.alerts.set_status(owner._view.status())

    def removeBox(self, index):
        owner = self.owner
        if owner.session.review.confirmed:
            return
        if owner.session.review.remove_box(index):
            owner._load.invalidate_export()
            owner.session.store_active()
            owner.emit_review()
            owner.emit_view()
            owner.alerts.set_status(
                f'{owner.session.review.path.name}: box removed. '
                f'{len(owner.session.review.selected)} selected of '
                f'{len(owner.session.review.boxes)}.'
            )

    def undo(self):
        owner = self.owner
        was_confirmed = owner.session.review.confirmed
        if owner.session.review.undo():
            owner._load.invalidate_export()
            if was_confirmed:
                owner._load.refresh_display()
            owner.session.store_active()
            owner.emit_review()
            owner.emit_view()
        if owner.session.review.image is not None:
            owner.alerts.set_status(owner._view.status())

    def redo(self):
        owner = self.owner
        was_confirmed = owner.session.review.confirmed
        if owner.session.review.redo():
            owner._load.invalidate_export()
            if was_confirmed:
                owner._load.refresh_display()
            owner.session.store_active()
            owner.emit_review()
            owner.emit_view()
        if owner.session.review.image is not None:
            owner.alerts.set_status(owner._view.status())

    def editBoxes(self):
        owner = self.owner
        if owner.session.review.image is None or not owner.session.review.confirmed:
            return
        owner.session.review.confirmed = False
        owner._load.invalidate_export()
        owner._load.refresh_display()
        owner.session.store_active()
        owner.emit_review()
        owner.alerts.set_status(
            'Click an X to remove a box. Confirm selection when ready.'
        )

    def clearBoxes(self):
        owner = self.owner
        if not owner.session.review.boxes:
            return
        if not owner.alerts.ask('Clear boxes', 'Remove all suggested and manually drawn boxes?'):
            return
        was_confirmed = owner.session.review.confirmed
        owner.session.review.clear()
        owner._load.invalidate_export()
        if was_confirmed:
            owner._load.refresh_display()
        owner.session.store_active()
        owner.emit_review()
        owner.emit_view()
        owner.alerts.set_status('Boxes cleared. Scan again or drag to add a box.')

    def cancelCapture(self):
        owner = self.owner
        if owner.capture != 'none':
            owner.cancel_capture()
            owner.alerts.set_status('Area selection canceled.')

    def cancel_capture(self):
        owner = self.owner
        if owner.capture != 'none' or owner.drag is not None:
            owner.capture = 'none'
            owner.drag = None
            owner.session.review.viewport.cancel_drag()
            owner.captureChanged.emit()
            owner.emit_view()
