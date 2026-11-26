import unittest
from pathlib import Path

from PIL import Image

from markseal import documents
from markseal.pdf_review import PdfReview


class FakeDocument:
    def __init__(self, path):
        self.path = Path(path)
        self.page_count = 2
        self.closed = False
        self.fail_page = None

    def render_page(self, index):
        if index == self.fail_page:
            raise documents.PdfError(f'Cannot render page {index + 1}')
        return documents.PdfPage(
            image=Image.new('RGB', (40, 30), 'white'),
            index=index,
            page_count=self.page_count,
            dpi=72,
        )

    def close(self):
        self.closed = True


class PdfReviewTests(unittest.TestCase):
    def setUp(self):
        self.document = None

        def factory(path):
            self.document = FakeDocument(path)
            return self.document

        self.review = PdfReview(Path('document.pdf'), document_factory=factory)

    def test_open_returns_the_first_page_state(self):
        state = self.review.open()

        self.assertEqual(state.page.index, 0)
        self.assertEqual(state.page.page_count, 2)
        self.assertEqual((self.review.page_index, self.review.page_count), (0, 2))
        self.assertFalse(state.confirmed)
        self.assertFalse(state.boxset.boxes)

    def test_switch_stores_each_page_boxset_and_confirmation(self):
        first = self.review.open()
        first.boxset.add((1, 1, 5, 5), 'Page one')
        second = self.review.switch(
            1, current=first.boxset, confirmed=True)
        second.boxset.add((6, 6, 9, 9), 'Page two')

        back = self.review.switch(
            0, current=second.boxset, confirmed=False)

        self.assertEqual(self.review.page_index, 0)
        self.assertEqual(back.boxset.boxes, [(1, 1, 5, 5)])
        self.assertTrue(back.confirmed)
        self.assertTrue(self.review.unsaved())

    def test_a_failed_render_keeps_the_current_page(self):
        state = self.review.open()
        state.boxset.add((1, 1, 5, 5), 'Page one')
        self.document.fail_page = 1

        with self.assertRaises(documents.PdfError):
            self.review.switch(1, current=state.boxset, confirmed=True)

        self.assertEqual(self.review.page_index, 0)
        self.assertEqual(self.review.unsaved(), True)

    def test_close_clears_the_page_machine(self):
        self.review.open()

        self.review.close()

        self.assertTrue(self.document.closed)
        self.assertEqual(self.review.page_index, 0)
        self.assertFalse(self.review.unsaved())

    def test_unsaved_is_false_until_a_page_has_boxes(self):
        state = self.review.open()

        self.assertFalse(self.review.unsaved())

        state.boxset.add((1, 1, 5, 5), 'Page one')
        self.assertTrue(self.review.unsaved())


if __name__ == '__main__':
    unittest.main()
