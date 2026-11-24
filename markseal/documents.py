"""Local PDF page rendering for the redactor."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image


PDF_SUFFIXES = {'.pdf'}
PDF_RENDER_DPI = 200
PDF_MAX_PIXELS = 40_000_000


class PdfError(Exception):
    pass


@dataclass(frozen=True)
class PdfPage:
    image: Image.Image
    index: int
    page_count: int
    dpi: int


def render_scale(width_points: float, height_points: float, dpi: int = PDF_RENDER_DPI,
                 max_pixels: int = PDF_MAX_PIXELS):
    if width_points <= 0 or height_points <= 0 or dpi <= 0:
        raise ValueError('PDF page dimensions and render DPI must be positive.')
    scale = dpi / 72
    pixels = width_points * scale * height_points * scale
    if pixels > max_pixels:
        scale *= math.sqrt(max_pixels / pixels)
    return scale, max(1, int(round(scale * 72)))


class PdfDocument:
    def __init__(self, path):
        self.path = Path(path)
        self._document = None
        self._closed = False
        try:
            self._document = pdfium.PdfDocument(str(self.path))
            self.page_count = len(self._document)
        except (pdfium.PdfiumError, OSError) as error:
            self.close()
            raise PdfError(self._message(error)) from error
        if self.page_count <= 0:
            self.close()
            raise PdfError('This PDF has no pages.')

    def render_page(self, index):
        if self._document is None or self._closed:
            raise PdfError('This PDF is no longer open.')
        if not 0 <= index < self.page_count:
            raise PdfError(f'Page {index + 1} does not exist in this PDF.')
        page = None
        bitmap = None
        try:
            page = self._document[index]
            width, height = page.get_size()
            scale, actual_dpi = render_scale(width, height)
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            if image.mode == 'RGBA':
                background = Image.new('RGB', image.size, 'white')
                background.paste(image, mask=image.getchannel('A'))
                image = background
            else:
                image = image.convert('RGB')
            return PdfPage(image=image, index=index, page_count=self.page_count,
                           dpi=actual_dpi)
        except (pdfium.PdfiumError, OSError) as error:
            raise PdfError(f'Cannot render page {index + 1} of {self.path.name}.') from error
        finally:
            if bitmap is not None:
                bitmap.close()
            if page is not None:
                page.close()

    def close(self):
        if self._document is not None and not self._closed:
            self._document.close()
        self._closed = True
        self._document = None

    def _message(self, error):
        detail = str(error).lower()
        if 'password' in detail or 'encrypted' in detail:
            return ('This PDF is password-protected. '
                    'MarkSeal does not support password-protected PDFs yet.')
        return f'Cannot open {self.path.name}. It may be damaged or unsupported.'
