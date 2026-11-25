from __future__ import annotations

from dataclasses import dataclass, field

from .boxset import same_region

PADDING = 4


def padded_rect(box, size):
    return (max(0, box[0] - PADDING), max(0, box[1] - PADDING),
            min(size[0], box[2] + PADDING), min(size[1], box[3] + PADDING))


def padded_box(words, size):
    words = list(words)
    return padded_rect((min(word[1] for word in words), min(word[2] for word in words),
                        max(word[3] for word in words), max(word[4] for word in words)), size)


def contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


@dataclass
class SuggestionSet:
    boxes: list = field(default_factory=list)
    rules: dict = field(default_factory=dict)

    def __post_init__(self):
        self.boxes = list(self.boxes)
        self.rules = {box: tuple(labels) for box, labels in self.rules.items()}

    @classmethod
    def from_parts(cls, boxes, rules):
        return cls(boxes, rules)

    def add(self, box, category):
        match = next((existing for existing in self.boxes
                      if same_region(existing, box)), None)
        if match is None:
            self.boxes.append(box)
            self.rules[box] = (category,)
            return
        labels = list(self.rules.get(match, ()))
        if category not in labels:
            labels.append(category)
        self.rules[match] = tuple(labels)

    def add_exact(self, box, category):
        if box not in self.rules:
            self.boxes.append(box)
            labels = []
        else:
            labels = list(self.rules[box])
        if category not in labels:
            labels.append(category)
        self.rules[box] = tuple(labels)

    def add_unlabeled(self, box):
        if any(same_region(existing, box) for existing in self.boxes):
            return
        self.boxes.append(box)
        self.rules[box] = ()

    def merge(self, other, *, prefer_larger=False):
        for box in other.boxes:
            self._merge_one(box, other.rules.get(box, ()), prefer_larger)

    def _merge_one(self, box, labels, prefer_larger):
        match = next((existing for existing in self.boxes
                      if same_region(existing, box)), None)
        if match is None:
            self.boxes.append(box)
            self.rules[box] = tuple(labels)
            return
        if prefer_larger and _area(box) > _area(match):
            previous = self.rules.pop(match, ())
            self.boxes[self.boxes.index(match)] = box
            self.rules[box] = tuple(previous)
            match = box
        merged = list(self.rules.get(match, ()))
        for label in labels:
            if label not in merged:
                merged.append(label)
        self.rules[match] = tuple(merged)

    def merge_personal(self, other):
        for box in other.boxes:
            labels = other.rules.get(box, ())
            match = next((existing for existing in self.boxes
                          if same_region(existing, box)), None)
            if match is not None:
                if _area(box) > _area(match):
                    previous = self.rules.pop(match, ())
                    self.boxes[self.boxes.index(match)] = box
                    self.rules[box] = tuple(previous)
                    match = box
                merged = list(self.rules.get(match, ()))
                for label in labels:
                    if label not in merged:
                        merged.append(label)
                self.rules[match] = tuple(merged)
                continue
            container = next((existing for existing in self.boxes
                              if set(self.rules.get(existing, ())) & set(labels)
                              and contains(existing, box)), None)
            if container is None:
                self.boxes.append(box)
                self.rules[box] = tuple(labels)
                continue
            merged = list(self.rules.get(container, ()))
            for label in labels:
                if label not in merged:
                    merged.append(label)
            self.rules[container] = tuple(merged)

    def cover(self, box, category):
        covered = [existing for existing in self.boxes if contains(box, existing)]
        for existing in covered:
            self.boxes.remove(existing)
            self.rules.pop(existing, None)
        self.boxes.append(box)
        self.rules[box] = (category,)

    def prune_contained(self):
        kept = []
        for box in self.boxes:
            labels = self.rules.get(box, ())
            container = next((other for other in self.boxes
                              if other != box and contains(other, box)
                              and set(self.rules.get(other, ())) & set(labels)), None)
            if container is None:
                kept.append(box)
                continue
            merged = list(self.rules.get(container, ()))
            for label in labels:
                if label not in merged:
                    merged.append(label)
            self.rules[container] = tuple(merged)
            self.rules.pop(box, None)
        self.boxes[:] = kept

    def parts(self):
        return self.boxes, dict(self.rules)
