"""Tests for the local PDF renderer."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from markseal import documents


FIXTURES = Path(__file__).parent / 'fixtures'


def write_pdf(path, count=2):
    pages = [Image.new('RGB', (612, 792), 'white') for _ in range(count)]
    pages[0].save(path, 'PDF', save_all=True, append_images=pages[1:], resolution=72)


class PdfDocumentTests(unittest.TestCase):
    def test_page_count_and_first_page_render(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'two-pages.pdf'
            write_pdf(path)
            document = documents.PdfDocument(path)
            try:
                self.assertEqual(document.page_count, 2)
                page = document.render_page(0)
                self.assertEqual(page.index, 0)
                self.assertEqual(page.page_count, 2)
                self.assertEqual(page.image.size, (1700, 2200))
                self.assertEqual(page.image.mode, 'RGB')
            finally:
                document.close()

    def test_render_page_rejects_out_of_range_index(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'one-page.pdf'
            write_pdf(path, count=1)
            document = documents.PdfDocument(path)
            try:
                with self.assertRaises(documents.PdfError):
                    document.render_page(1)
            finally:
                document.close()

    def test_corrupt_pdf_raises_pdf_error(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'broken.pdf'
            path.write_bytes(b'%PDF-1.7\nnot a real pdf')
            with self.assertRaises(documents.PdfError):
                documents.PdfDocument(path)

    def test_password_pdf_raises_clear_error(self):
        with self.assertRaises(documents.PdfError) as caught:
            documents.PdfDocument(FIXTURES / 'encrypted.pdf')
        message = str(caught.exception).lower()
        self.assertTrue('password' in message or 'protected' in message)

    def test_rotated_page_renders_upright(self):
        document = documents.PdfDocument(FIXTURES / 'rotated.pdf')
        try:
            page = document.render_page(0)
            self.assertEqual(page.image.size, (2200, 1700))
        finally:
            document.close()

    def test_render_scale_caps_large_pages(self):
        scale, actual_dpi = documents.render_scale(20000, 20000)
        self.assertLess(scale, documents.PDF_RENDER_DPI / 72)
        self.assertLess(actual_dpi, documents.PDF_RENDER_DPI)
        self.assertGreaterEqual(actual_dpi, 1)

    def test_close_is_idempotent(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'close.pdf'
            write_pdf(path, count=1)
            document = documents.PdfDocument(path)
            document.close()
            document.close()


if __name__ == '__main__':
    unittest.main()
