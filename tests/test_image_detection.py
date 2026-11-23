"""QR detection on synthetic images."""
import unittest

import cv2

from tests.support import FakeEngine, Image, patch, recognize_regions

from markseal import image_detection


def qr_image(text='markseal-update', size=240):
    encoded = cv2.QRCodeEncoder.create().encode(text)
    return Image.fromarray(encoded).convert('RGB').resize((size, size), Image.NEAREST)


class ImageDetectionTests(unittest.TestCase):
    def test_blank_image_yields_no_qr(self):
        blank = Image.new('RGB', (240, 180), 'white')
        self.assertEqual(image_detection.detect_qr_codes(blank), [])

    def test_qr_code_is_found(self):
        boxes = image_detection.detect_qr_codes(qr_image())
        self.assertTrue(boxes)
        left, top, right, bottom = boxes[0]
        self.assertTrue(0 <= left < right <= 240 and 0 <= top < bottom <= 240)

    def test_scan_merges_qr_boxes_under_their_category(self):
        image = Image.new('RGB', (200, 120), 'white')
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        settings = (False, {'QR codes'}, 50, '', ())
        with patch('markseal.ocr.image_boxes',
                   return_value=[((100, 40, 140, 80), 'QR code')]):
            found = recognize_regions(image, FakeEngine(header), settings)
        self.assertIn((100, 40, 140, 80), found)
        self.assertEqual(found.rules[(100, 40, 140, 80)], ('QR code',))


if __name__ == '__main__':
    unittest.main()
