"""Pixelation and solid-fill redaction."""
from __future__ import annotations

from PIL import Image, ImageDraw

from performance_log import timed


# Very coarse blocks remove fine detail, but mosaic redaction can remain reversible.
def pixelate(image, boxes, block_size=32):
    out = image.copy()
    for x1, y1, x2, y2 in boxes:
        crop = out.crop((x1, y1, x2, y2))
        small = crop.resize((max(1, (x2-x1)//block_size), max(1, (y2-y1)//block_size)), Image.Resampling.BOX)
        out.paste(small.resize(crop.size, Image.Resampling.NEAREST), (x1, y1))
    return out


@timed('render_redactions')
def apply_redactions(image, boxes, method='Pixelate'):
    if method == 'Pixelate': return pixelate(image, boxes)
    out = image.copy(); draw = ImageDraw.Draw(out)
    for x1, y1, x2, y2 in boxes: draw.rectangle((x1,y1,x2-1,y2-1), fill='black')
    return out
