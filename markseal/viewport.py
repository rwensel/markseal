"""One owner for view transforms, hit-testing, drag boxes and pan anchoring."""
from __future__ import annotations


class Viewport:
    def __init__(self):
        self.image_size: tuple[int, int] | None = None
        self.view_width = 1
        self.view_height = 1
        self.zoom = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.scale = 1.0
        self.drag_origin: tuple | None = None
        self.pan_origin: tuple | None = None

    def clear(self):
        self.image_size = None
        self.drag_origin = self.pan_origin = None

    def reset(self, image_size):
        self.image_size = image_size
        self.zoom = 1.0
        self.offset_x = self.offset_y = 0.0
        self.drag_origin = self.pan_origin = None
        self.refit()

    def set_view_size(self, width, height):
        self.view_width = max(1, int(width))
        self.view_height = max(1, int(height))
        self.refit()

    def refit(self):
        if self.image_size is None:
            return
        width, height = self.image_size
        self.scale = min(self.view_width / width, self.view_height / height, 1.0) * self.zoom
        self.clamp_offsets()

    def clamp_offsets(self):
        if self.image_size is None:
            return
        width, height = self.image_size
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

    def image_coordinates(self, x, y):
        return int((x - self.offset_x) / self.scale), int((y - self.offset_y) / self.scale)

    def clamped_axis(self, value, limit):
        return max(0, min(limit, value))

    def drag_box(self, x, y, start=None):
        start_x, start_y = self.drag_origin if start is None else start
        width, height = self.image_size
        left, right = sorted((start_x, x))
        top, bottom = sorted((start_y, y))
        x1 = self.clamped_axis(int((left - self.offset_x) / self.scale), width)
        x2 = min(width, self.clamped_axis(int((right - self.offset_x) / self.scale) + 1, width))
        y1 = self.clamped_axis(int((top - self.offset_y) / self.scale), height)
        y2 = min(height, self.clamped_axis(int((bottom - self.offset_y) / self.scale) + 1, height))
        return x1, y1, x2, y2

    def drag_region(self, x, y, start=None):
        start_x, start_y = self.drag_origin if start is None else start
        width, height = self.image_size
        left, right = sorted((start_x, x))
        top, bottom = sorted((start_y, y))
        return (
            self.clamped_axis(int((left - self.offset_x) / self.scale), width),
            self.clamped_axis(int((top - self.offset_y) / self.scale), height),
            self.clamped_axis(int((right - self.offset_x) / self.scale), width),
            self.clamped_axis(int((bottom - self.offset_y) / self.scale), height),
        )

    def drag_rect(self, x, y):
        if self.drag_origin is None:
            return None
        start_x, start_y = self.drag_origin
        x1, x2 = sorted((start_x, x))
        y1, y2 = sorted((start_y, y))
        return x1, y1, x2 - x1, y2 - y1

    def begin_drag(self, x, y):
        if self.image_size is None or self.pan_origin is not None:
            return False
        self.drag_origin = (x, y)
        return True

    def take_drag(self):
        origin, self.drag_origin = self.drag_origin, None
        return origin

    def cancel_drag(self):
        self.drag_origin = None

    def hit_index(self, x, y, boxes):
        image_x, image_y = self.image_coordinates(x, y)
        for index in range(len(boxes) - 1, -1, -1):
            x1, y1, x2, y2 = boxes[index]
            if x1 <= image_x < x2 and y1 <= image_y < y2:
                return index
        return None

    def zoom_at(self, x, y, direction):
        if self.image_size is None or self.pan_origin is not None:
            return False
        zoom = max(1.0, min(6.0, self.zoom * (1.2 if direction > 0 else 1 / 1.2)))
        image_x, image_y = (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale
        self.zoom = zoom
        width, height = self.image_size
        self.scale = min(self.view_width / width, self.view_height / height, 1.0) * zoom
        self.offset_x, self.offset_y = x - image_x * self.scale, y - image_y * self.scale
        self.clamp_offsets()
        return True

    def pan_begin(self, x, y):
        if self.image_size is None or self.zoom <= 1.0:
            return False
        self.drag_origin = None
        self.pan_origin = (x, y)
        return True

    def pan_move(self, x, y):
        if self.image_size is None or self.pan_origin is None:
            return False
        self.offset_x += x - self.pan_origin[0]
        self.offset_y += y - self.pan_origin[1]
        self.pan_origin = (x, y)
        self.clamp_offsets()
        return True

    def pan_end(self):
        if self.pan_origin is None:
            return False
        self.pan_origin = None
        return True
