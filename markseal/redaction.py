"""Pixelation, blur, erase, and solid-fill redaction."""
from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .performance_log import timed


# Very coarse blocks remove fine detail, but mosaic redaction can remain reversible.
def pixelate(image, boxes, block_size=32):
    out = image.copy()
    for x1, y1, x2, y2 in boxes:
        crop = out.crop((x1, y1, x2, y2))
        small = crop.resize((max(1, (x2-x1)//block_size), max(1, (y2-y1)//block_size)), Image.Resampling.BOX)
        out.paste(small.resize(crop.size, Image.Resampling.NEAREST), (x1, y1))
    return out


def blur(image, boxes, radius=16):
    out = image.copy()
    for x1, y1, x2, y2 in boxes:
        if x2 <= x1 or y2 <= y1:
            continue
        out.paste(out.crop((x1, y1, x2, y2)).filter(ImageFilter.GaussianBlur(radius)), (x1, y1))
    return out


def erase(image, boxes, radius=7):
    source = np.array(image.convert('RGB'))
    mask = np.zeros(source.shape[:2], np.uint8)
    for x1, y1, x2, y2 in boxes:
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = 255
    if not mask.any():
        return image.copy()
    try:
        filled = cv2.inpaint(source, mask, radius, cv2.INPAINT_TELEA)
    except cv2.error:
        filled = np.zeros_like(source)
    out = source.copy()
    for x1, y1, x2, y2 in boxes:
        if x2 > x1 and y2 > y1:
            out[y1:y2, x1:x2] = filled[y1:y2, x1:x2]
    return Image.fromarray(out)


@timed('render_redactions')
def apply_redactions(image, boxes, method='Pixelate'):
    if method == 'Pixelate':
        return pixelate(image, boxes)
    if method == 'Blur':
        return blur(image, boxes)
    if method == 'Erase':
        return erase(image, boxes)
    out = image.copy(); draw = ImageDraw.Draw(out)
    for x1, y1, x2, y2 in boxes: draw.rectangle((x1,y1,x2-1,y2-1), fill='black')
    return out
