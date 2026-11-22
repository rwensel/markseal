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
