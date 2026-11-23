from __future__ import annotations

from pathlib import Path

from PIL import Image

from .boxset import BoxSet


class Review:
    def __init__(self):
        self.image: Image.Image | None = None
        self.path: Path | None = None
        self._state = BoxSet()
        self.confirmed = False
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.view_width = 1
        self.view_height = 1
        self.scale = 1.0
        self.start: tuple | None = None
        self.pan_start: tuple | None = None

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

    def load(self, image, path):
        self.image = image
        self.path = Path(path)
        self._state = BoxSet()
        self.confirmed = False
        self.zoom = 1.0
        self.offset_x = self.offset_y = 0.0
        self.start = self.pan_start = None
        self.refit()

    def set_view_size(self, width, height):
        self.view_width = max(1, int(width))
        self.view_height = max(1, int(height))
        self.refit()

    def refit(self):
        if self.image is None:
            return
        width, height = self.image.size
        self.scale = min(self.view_width / width, self.view_height / height, 1.0) * self.zoom
        self.clamp_offsets()

    def clamp_offsets(self):
        if self.image is None:
            return
        width, height = self.image.size
        scaled_width = width * self.scale
        scaled_height = height * self.scale
        if scaled_width <= self.view_width:
            self.offset_x = (self.view_width - scaled_width) / 2
        else:
            self.offset_x = min(0.0, max(self.view_width - scaled_width, self.offset_x))
        if scaled_height <= self.view_height:
            self.offset_y = (self.view_height - scaled_height) / 2
        else:
            self.offset_y = min(0.0, max(self.view_height - scaled_height, self.offset_y))

    def zoom_at(self, x, y, direction):
        if self.image is None or self.pan_start is not None:
            return False
        zoom = max(1.0, min(6.0, self.zoom * (1.2 if direction > 0 else 1 / 1.2)))
        image_x, image_y = (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale
        self.zoom = zoom
        width, height = self.image.size
        self.scale = min(self.view_width / width, self.view_height / height, 1.0) * zoom
        self.offset_x, self.offset_y = x - image_x * self.scale, y - image_y * self.scale
        self.clamp_offsets()
        return True

    def pan_begin(self, x, y):
        if self.image is None or self.zoom <= 1.0:
            return False
        self.start = None
        self.pan_start = (x, y)
        return True

    def pan_move(self, x, y):
        if self.image is None or self.pan_start is None:
            return False
        self.offset_x += x - self.pan_start[0]
        self.offset_y += y - self.pan_start[1]
        self.pan_start = (x, y)
        self.clamp_offsets()
        return True

    def pan_end(self):
        if self.pan_start is None:
            return False
        self.pan_start = None
        return True

    def press(self, x, y):
        if self.image is None or self.pan_start is not None:
            return False
        self.start = (x, y)
        return True

    def release(self, x, y):
        if self.start is None or self.image is None:
            return 'none'
        start_x, start_y = self.start
        self.start = None
        if abs(x - start_x) <= 4 and abs(y - start_y) <= 4:
            image_x = int((start_x - self.offset_x) / self.scale)
            image_y = int((start_y - self.offset_y) / self.scale)
            for index in range(len(self.boxes) - 1, -1, -1):
                x1, y1, x2, y2 = self.boxes[index]
                if x1 <= image_x < x2 and y1 <= image_y < y2:
                    self._state.toggle(index)
                    self.confirmed = False
                    return 'toggle'
            return 'none'
        width, height = self.image.size
        left = max(0, min(width, int((start_x - self.offset_x) / self.scale)))
        right = max(0, min(width, int((x - self.offset_x) / self.scale) + 1))
        top = max(0, min(height, int((start_y - self.offset_y) / self.scale)))
        bottom = max(0, min(height, int((y - self.offset_y) / self.scale) + 1))
        x1, x2 = sorted((left, right))
        y1, y2 = sorted((top, bottom))
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

    def undo(self):
        if not self._state.undo():
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
