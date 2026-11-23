"""Local visual-anchor matching for redaction boxes."""
import math

import cv2
import numpy as np


def prepare_anchor(image, bounds):
    patch = np.asarray(image.crop(bounds).convert('L'))
    if min(patch.shape) < 20 or patch.std() < 10:
        raise ValueError('Choose a larger, detailed anchor such as a logo or a distinctive label.')
    return patch


def locate_anchor(image, patch, min_score=0.82, min_gap=0.06):
    """Return the best unambiguous match in source pixels, or None."""
    gray = np.asarray(image.convert('L'))
    ratio = min(1.0, 1600 / max(gray.shape))
    if ratio < 1:
        gray = cv2.resize(gray, (round(gray.shape[1]*ratio), round(gray.shape[0]*ratio)),
                          interpolation=cv2.INTER_AREA)
    candidates = []
    height, width = patch.shape
    for scale in (1.0, 0.95, 1.05, 0.90, 1.10, 0.85, 1.15, 0.80, 1.20, 0.75, 1.25, 1.30):
        w, h = round(width*scale*ratio), round(height*scale*ratio)
        if min(w, h) < 12 or w > gray.shape[1] or h > gray.shape[0]:
            continue
        interpolation = cv2.INTER_AREA if scale*ratio < 1 else cv2.INTER_LINEAR
        template = cv2.resize(patch, (w, h), interpolation=interpolation)
        if template.std() < 5:
            continue
        scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
        for _ in range(2):
            _, score, _, (x, y) = cv2.minMaxLoc(scores)
            candidates.append((score, x, y, w, h))
            dx, dy = max(1, w//3), max(1, h//3)
            scores[max(0, y-dy):y+dy+1, max(0, x-dx):x+dx+1] = -1

    if not candidates:
        return None
    best = max(candidates)
    score, x, y, w, h = best
    if score < min_score:
        return None
    center_x, center_y = x+w/2, y+h/2
    for other_score, ox, oy, ow, oh in candidates:
        distinct = abs(ox+ow/2-center_x) > max(w, ow)/3 or abs(oy+oh/2-center_y) > max(h, oh)/3
        if distinct and other_score >= score-min_gap:
            return None
    return x/ratio, y/ratio, w/(width*ratio), h/(height*ratio)


def relocate_boxes(boxes, anchor, match, image_size):
    x, y, scale_x, scale_y = match
    anchor_x, anchor_y = anchor[:2]
    width, height = image_size
    placed = []
    for left, top, right, bottom in boxes:
        box = (math.floor(x+(left-anchor_x)*scale_x), math.floor(y+(top-anchor_y)*scale_y),
               math.ceil(x+(right-anchor_x)*scale_x), math.ceil(y+(bottom-anchor_y)*scale_y))
        if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            return []
        placed.append(box)
    return placed
