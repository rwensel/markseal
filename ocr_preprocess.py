"""In-memory OCR preprocessing with unchanged pixel coordinates."""
import cv2
import numpy as np
from PIL import Image


def color_ocr_variants(image):
    lab = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2LAB)
    lightness, red_green, blue_yellow = cv2.split(lab)
    contrast = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    yield Image.fromarray(contrast.apply(lightness))

    for channel in (red_green, blue_yellow):
        # Ignore isolated outliers and skip channels with little color information.
        histogram = np.bincount(channel.ravel(), minlength=256).cumsum()
        low, middle, high = np.searchsorted(histogram, channel.size * np.array([.0025, .5, .9975]))
        if high - low < 8:
            continue
        lookup = np.clip((np.arange(256) - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
        if lookup[middle] < 128:
            lookup = 255 - lookup
        yield Image.fromarray(cv2.LUT(channel, lookup))



def small_text_tiles(image):
    """Yield overlapping views so a large image does not shrink before OCR."""
    width, height = image.size
    if max(width, height) < 1000 or min(width, height) < 400:
        return
    for top, bottom in ((0, round(.59*height)), (round(.41*height), height)):
        for left, right in ((0, round(.59*width)), (round(.41*width), width)):
            tile = image.crop((left, top, right, bottom))
            factor = min(2, 1600 / max(tile.size))
            size = tuple(max(1, round(side*factor)) for side in tile.size)
            yield (left, top, right, bottom), tile.resize(size, Image.Resampling.LANCZOS)


def strike_reduced_variant(image):
    """Reduce thin red deletion strokes on an OCR-only copy."""
    rgb = np.asarray(image.convert('RGB'))
    r, g, b = rgb.astype(np.int16).transpose(2, 0, 1)
    red_mask = ((r - g > 17) & (r - b > 12) & (r > 65)).astype(np.uint8) * 255
    minimum_length = max(24, image.width // 80)
    lines = cv2.HoughLinesP(red_mask, 1, np.pi/180, threshold=max(16, minimum_length//2),
                            minLineLength=minimum_length, maxLineGap=3)
    if lines is None:
        return None
    stroke_mask = np.zeros_like(red_mask)
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        if abs(y2-y1) <= .10 * abs(x2-x1):
            cv2.line(stroke_mask, (x1, y1), (x2, y2), 255, 1)
    if not stroke_mask.any():
        return None
    # Restrict removal to the colored stroke. Surrounding text retains its geometry.
    stroke_mask = cv2.bitwise_and(cv2.dilate(stroke_mask, np.ones((3, 1), dtype=np.uint8)), red_mask)
    return Image.fromarray(cv2.inpaint(rgb, stroke_mask, 2, cv2.INPAINT_TELEA))
