"""Face and QR detection on synthetic images."""
import unittest

import cv2
import numpy as np

from tests.support import FakeEngine, Image, patch, recognize_regions

from markseal import image_detection


def qr_image(text='markseal-update', size=240):
    encoded = cv2.QRCodeEncoder.create().encode(text)
    return Image.fromarray(encoded).convert('RGB').resize((size, size), Image.NEAREST)


class ImageDetectionTests(unittest.TestCase):
    def test_face_model_loads(self):
        self.assertIsNotNone(image_detection._face_detector())

    def test_blank_image_yields_no_faces_or_qr(self):
        blank = Image.new('RGB', (240, 180), 'white')
        self.assertEqual(image_detection.detect_faces(blank), [])
        self.assertEqual(image_detection.detect_qr_codes(blank), [])

    def test_face_boxes_are_mapped_and_clipped(self):
        image = Image.new('RGB', (100, 80), 'white')
        detection = np.array([[10, 20, 30, 40] + [0.0] * 11], dtype=np.float32)
        with patch.object(image_detection, '_face_detector') as detector:
            detector.return_value.detect.return_value = (1, detection)
            boxes = image_detection.detect_faces(image)
        self.assertEqual(boxes, [(10, 20, 40, 60)])

    def test_qr_code_is_found(self):
        boxes = image_detection.detect_qr_codes(qr_image())
        self.assertTrue(boxes)
        left, top, right, bottom = boxes[0]
        self.assertTrue(0 <= left < right <= 240 and 0 <= top < bottom <= 240)

    def test_scan_merges_face_and_qr_boxes(self):
        image = Image.new('RGB', (200, 120), 'white')
        header = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
        settings = (False, {'Faces', 'QR codes'}, 50, '', ())
        with patch('markseal.ocr.image_boxes',
                   return_value=[((10, 10, 30, 30), 'Face'),
                                 ((100, 40, 140, 80), 'QR code')]):
            found = recognize_regions(image, FakeEngine(header), settings)
        self.assertEqual(found.rules[(10, 10, 30, 30)], ('Face',))
        self.assertEqual(found.rules[(100, 40, 140, 80)], ('QR code',))


if __name__ == '__main__':
    unittest.main()
