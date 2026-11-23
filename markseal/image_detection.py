"""OpenCV QR and YuNet face detection on a PIL image."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

_FACE_MODEL = Path(__file__).resolve().parent / 'models' / 'face_detection_yunet_2023mar.onnx'
_FACE_DETECTOR = None


def _face_detector():
    global _FACE_DETECTOR
    if _FACE_DETECTOR is None:
        if not _FACE_MODEL.is_file():
            return None
        _FACE_DETECTOR = cv2.FaceDetectorYN_create(str(_FACE_MODEL), '', (320, 320),
                                                   0.9, 0.3, 5000)
    return _FACE_DETECTOR


def _frame(image):
    return cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2BGR)


def _clamp(box, size):
    left, top, right, bottom = box
    return (max(0, int(left)), max(0, int(top)),
            min(size[0], int(right)), min(size[1], int(bottom)))


def detect_faces(image):
    detector = _face_detector()
    if detector is None:
        return []
    frame = _frame(image)
    height, width = frame.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(frame)
    if faces is None:
        return []
    return [_clamp((x, y, x + w, y + h), image.size) for x, y, w, h, *_ in faces]


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
