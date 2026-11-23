"""OpenCV QR-code detection on a PIL image."""
from __future__ import annotations

import cv2
import numpy as np


def _frame(image):
    return cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2BGR)


def _clamp(box, size):
    left, top, right, bottom = box
    return (max(0, int(left)), max(0, int(top)),
            min(size[0], int(right)), min(size[1], int(bottom)))


def detect_qr_codes(image):
    frame = _frame(image)
    detected, points = cv2.QRCodeDetector().detectMulti(frame)
    if not detected or points is None:
        return []
    boxes = []
    for quad in points:
        xs = quad[:, 0]
        ys = quad[:, 1]
        boxes.append(_clamp((xs.min(), ys.min(), xs.max(), ys.max()), image.size))
    return boxes
