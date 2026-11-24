from __future__ import annotations

from pathlib import Path

from PIL import Image

from .boxset import BoxSet
from .viewport import Viewport


class Review:
    def __init__(self):
        self.image: Image.Image | None = None
        self.path: Path | None = None
        self._state = BoxSet()
        self._viewport = Viewport()
        self.confirmed = False

    @property
    def viewport(self):
        return self._viewport

    @property
    def boxset(self):
        return self._state

    @boxset.setter
    def boxset(self, value):
        self._state = value

    @property
    def boxes(self):
        return self._state.boxes

    @boxes.setter
    def boxes(self, value):
        self._state.boxes = list(value)

    @property
    def rules(self):
        return self._state.rules

    @rules.setter
    def rules(self, value):
        self._state.rules = dict(value)

    @property
    def selected(self):
        return self._state.selected

    @selected.setter
    def selected(self, value):
        self._state.selected = set(value)

    @property
    def scale(self):
        return self._viewport.scale

    @property
    def offset_x(self):
        return self._viewport.offset_x

    @property
    def offset_y(self):
        return self._viewport.offset_y

    @property
    def zoom(self):
        return self._viewport.zoom

    def load(self, image, path):
        self.image = image
        self.path = Path(path)
        self._state = BoxSet()
        self.confirmed = False
        self._viewport.reset(image.size)

    def set_view_size(self, width, height):
        self._viewport.set_view_size(width, height)

    def zoom_at(self, x, y, direction):
        return self._viewport.zoom_at(x, y, direction)

    def pan_begin(self, x, y):
        return self._viewport.pan_begin(x, y)

    def pan_move(self, x, y):
        return self._viewport.pan_move(x, y)

    def pan_end(self):
        return self._viewport.pan_end()

    def press(self, x, y):
        return self._viewport.begin_drag(x, y)

    def release(self, x, y):
        if self._viewport.drag_origin is None or self.image is None:
            return 'none'
        start_x, start_y = self._viewport.take_drag()
        if abs(x - start_x) <= 4 and abs(y - start_y) <= 4:
            index = self._viewport.hit_index(start_x, start_y, self.boxes)
            if index is not None:
                self._state.toggle(index)
                self.confirmed = False
                return 'toggle'
            return 'none'
        x1, y1, x2, y2 = self._viewport.drag_box(x, y, start=(start_x, start_y))
        if x2 > x1 and y2 > y1:
            self._state.add((x1, y1, x2, y2), 'Manual box')
            self.confirmed = False
            return 'add'
        return 'none'

    def remove_box(self, index):
        if not self._state.remove(index):
            return False
        self.confirmed = False
        return True

    def toggle_box(self, index):
        if not 0 <= index < len(self.boxes):
            return False
        self._state.toggle(index)
        self.confirmed = False
        return True

    def select_all(self):
        if self.confirmed or not self.boxes or len(self.selected) == len(self.boxes):
            return False
        self._state.selected = set(range(len(self.boxes)))
        self.confirmed = False
        return True

    def select_none(self):
        if self.confirmed or not self._state.selected:
            return False
        self._state.selected.clear()
        self.confirmed = False
        return True

    def undo(self):
        if not self._state.undo():
            return False
        self.confirmed = False
        return True

    def can_redo(self):
        return self._state.can_redo()

    def redo(self):
        if not self._state.redo():
            return False
        self.confirmed = False
        return True

    def clear(self):
        if not self._state.clear():
            return False
        self.confirmed = False
        return True

    def selected_boxes(self):
        return self._state.selected_boxes()

    def add_suggestions(self, found, rules=None):
        outcome = self._state.suggest(found, rules)
        if outcome.changed:
            self.confirmed = False
        return outcome.added
