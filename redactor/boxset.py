"""One owner for an image's boxes, rules, selection and merge policy.

``Review`` and ``FolderImage`` expose this state as thin views. A folder
image and the review of that image share the same :class:`BoxSet`, so the
active selection never has to be copied between them.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class BoxList(list):
    def __init__(self, iterable=(), rules=None):
        super().__init__(iterable)
        self.rules = {box: tuple(labels) for box, labels in (rules or {}).items() if labels}


def same_region(first, second):
    if first == second:
        return True
    widths = (first[2]-first[0], second[2]-second[0])
    heights = (first[3]-first[1], second[3]-second[1])
    areas = (widths[0]*heights[0], widths[1]*heights[1])
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1]))
    if overlap >= 0.75 * max(areas):
        return True

    # Different passes can put larger padding around the very same word.
    # Require close centers and comparable dimensions so a word inside a much
    # wider line, or a neighboring label whose edges touch, is still distinct.
    center_dx = abs(first[0]+first[2]-second[0]-second[2]) / 2
    center_dy = abs(first[1]+first[3]-second[1]-second[3]) / 2
    return (overlap >= 0.9 * min(areas)
            and min(widths) >= 0.45 * max(widths)
            and min(heights) >= 0.45 * max(heights)
            and center_dx <= 0.2 * max(widths)
            and center_dy <= 0.2 * max(heights))


def new_ocr_boxes(candidates, existing=()):
    kept = list(existing)
    added = []
    for box in candidates:
        if not any(same_region(box, previous) for previous in kept):
            added.append(box)
            kept.append(box)
    return added


def strip_contained_selected(boxes, selected):
    selected = set(selected)

    def contains(outer, inner):
        outer_area = (outer[2] - outer[0]) * (outer[3] - outer[1])
        inner_area = (inner[2] - inner[0]) * (inner[3] - inner[1])
        return (outer_area > inner_area
                and outer[0] <= inner[0] + 2
                and outer[1] <= inner[1] + 2
                and outer[2] >= inner[2] - 2
                and outer[3] >= inner[3] - 2)

    kept = []
    kept_selected = set()
    for index, box in enumerate(boxes):
        if index in selected and any(
                other != index and other in selected and contains(boxes[other], box)
                for other in range(len(boxes))):
            continue
        if index in selected:
            kept_selected.add(len(kept))
        kept.append(box)
    return kept, kept_selected


def image_status(*, error='', saved=False, reviewed=False, incomplete_ocr=(),
                 scanned=False, boxes=()):
    if error:
        return error
    if saved:
        return 'Saved'
    if reviewed:
        return 'Reviewed'
    if incomplete_ocr:
        return 'Partial scan · review needed'
    if scanned:
        return 'Scanned · review needed'
    if boxes:
        return 'Boxes added · review needed'
    return 'Not checked'


@dataclass(frozen=True)
class Merge:
    added: int
    changed: bool


class BoxSet:
    def __init__(self, boxes=(), rules=None, selected=()):
        self.boxes = list(boxes)
        self.rules = {box: tuple(labels) for box, labels in (rules or {}).items() if labels}
        self.selected = set(selected)

    def selected_boxes(self):
        return [box for index, box in enumerate(self.boxes) if index in self.selected]

    def add(self, box, label='Manual box'):
        self.boxes.append(box)
        self.rules[box] = (label,)
        self.selected.add(len(self.boxes) - 1)

    def toggle(self, index):
        if index in self.selected:
            self.selected.remove(index)
        else:
            self.selected.add(index)

    def remove(self, index):
        if not 0 <= index < len(self.boxes):
            return False
        removed = self.boxes.pop(index)
        self.rules.pop(removed, None)
        self.selected = {i if i < index else i - 1 for i in self.selected if i != index}
        return True

    def undo(self):
        if not self.boxes:
            return False
        self.selected.discard(len(self.boxes) - 1)
        removed = self.boxes.pop()
        self.rules.pop(removed, None)
        return True

    def clear(self):
        if not self.boxes:
            return False
        self.boxes.clear()
        self.rules.clear()
        self.selected.clear()
        return True

    def merge(self, boxes, rules=None, source='Copied box'):
        before_boxes = list(self.boxes)
        before_selected = set(self.selected)
        indices = {box: index for index, box in enumerate(self.boxes)}
        rule_values = rules or {}
        new_boxes = []
        for box in boxes:
            index = indices.get(box)
            if index is None:
                index = len(self.boxes)
                self.boxes.append(box)
                indices[box] = index
                new_boxes.append(box)
                self.rules.setdefault(box, tuple(rule_values.get(box, ()) or (source,)))
            elif box not in self.rules:
                self.rules[box] = tuple(rule_values.get(box, ()) or (source,))
            if index not in self.selected:
                self.selected.add(index)
        kept, kept_selected = strip_contained_selected(self.boxes, self.selected)
        if kept != self.boxes:
            self.boxes[:] = kept
            for box in list(self.rules):
                if box not in self.boxes:
                    del self.rules[box]
            self.selected.clear()
            self.selected.update(kept_selected)
        changed = self.boxes != before_boxes or self.selected != before_selected
        selected_boxes = set(self.selected_boxes())
        return Merge(sum(1 for box in new_boxes if box in selected_boxes), changed)

    def suggest(self, found, rules=None, source='OCR suggestion'):
        if rules is None:
            rules = getattr(found, 'rules', {})
        added = new_ocr_boxes(found, self.boxes)
        return self.merge(added, rules, source)


class FolderImage:
    def __init__(self, path, boxes=(), rules=None, selected=(), scanned=False,
                 incomplete_ocr=(), reviewed=False, saved=False, error='', stamp=None,
                 method='Pixelate'):
        self.path = path
        self.boxset = BoxSet(boxes, rules, selected)
        self.scanned = scanned
        self.incomplete_ocr = tuple(incomplete_ocr)
        self.reviewed = reviewed
        self.saved = saved
        self.error = error
        self.stamp = stamp
        self.method = method

    @property
    def boxes(self):
        return self.boxset.boxes

    @boxes.setter
    def boxes(self, value):
        self.boxset.boxes = list(value)

    @property
    def rules(self):
        return self.boxset.rules

    @rules.setter
    def rules(self, value):
        self.boxset.rules = dict(value)

    @property
    def selected(self):
        return self.boxset.selected

    @selected.setter
    def selected(self, value):
        self.boxset.selected = set(value)

    @property
    def status(self):
        return image_status(error=self.error, saved=self.saved, reviewed=self.reviewed,
                            incomplete_ocr=self.incomplete_ocr, scanned=self.scanned,
                            boxes=self.boxes)

    def add_shared_boxes(self, boxes, rules=None, source='Copied box'):
        outcome = self.boxset.merge(boxes, rules, source)
        if outcome.changed:
            self.reviewed = self.saved = False
        return outcome.changed

    def add_suggestions(self, found, incomplete=(), rules=None):
        outcome = self.boxset.suggest(found, rules)
        self.scanned = True
        self.incomplete_ocr = tuple(incomplete)
        self.reviewed = self.saved = False
        self.error = ''
        return outcome.added
