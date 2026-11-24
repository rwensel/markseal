"""Export pipeline and coordinate log behavior."""
import unittest

from tests.support import (
    Image,
    Path,
    TemporaryDirectory,
    audit_exports,
    export,
    json,
    save_export,
)


class ExportPipelineTests(unittest.TestCase):
    def make_source(self, folder):
        path = Path(folder) / 'source.png'
        image = Image.new('RGB', (120, 80), 'white')
        for x in range(10, 60):
            for y in range(10, 40):
                image.putpixel((x, y), (x * 3 % 256, y * 2 % 256, 90))
        image.save(path)
        return path

    def test_both_export_paths_write_the_same_log_shape(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            with Image.open(source) as handle:
                image = handle.convert('RGB')
            boxes = [(10, 10, 40, 30)]
            file_target = Path(folder) / 'folder.png'
            memory_target = Path(folder) / 'memory.png'
            export.write_copy(export.snapshot(source, file_target, boxes, {0}, 'Pixelate'))
            export.write_copy(export.snapshot(source, memory_target, boxes, {0}, 'Solid black',
                                              image=image))
            file_log = json.loads(file_target.with_suffix('.redactions.json')
                                  .read_text(encoding='utf-8'))
            memory_log = json.loads(memory_target.with_suffix('.redactions.json')
                                    .read_text(encoding='utf-8'))
        self.assertEqual(set(file_log), set(memory_log))
        self.assertEqual(set(file_log), {
            'source_filename', 'output_filename', 'image_dimensions',
            'redaction_rectangles_xyxy', 'created_local_time', 'method', 'note',
        })
        self.assertEqual(file_log['source_filename'], 'source.png')
        self.assertEqual(file_log['output_filename'], 'folder.png')
        self.assertEqual(file_log['redaction_rectangles_xyxy'], [[10, 10, 40, 30]])
        self.assertEqual(memory_log['method'], 'Solid black')
        self.assertEqual(memory_log['note'], export.NOTE)

    def test_pasted_source_adds_the_in_memory_sentence(self):
        log = export.coordinate_log(Path('pasted-image.png'), Path('out.png'), (10, 10),
                                    [], 'Pixelate', pasted=True)
        self.assertTrue(log['note'].endswith(
            'No source file exists; this copy came from an in-memory image (paste or screen capture).'))

    def test_source_page_is_optional_and_recorded_when_given(self):
        image_log = export.coordinate_log(Path('source.png'), Path('out.png'), (10, 10),
                                          [], 'Pixelate')
        pdf_log = export.coordinate_log(Path('source.pdf'), Path('out.png'), (10, 10),
                                         [], 'Pixelate', source_page=3)
        self.assertNotIn('source_page', image_log)
        self.assertEqual(pdf_log['source_page'], 3)

    def test_snapshot_carries_the_page_into_the_log(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            job = export.snapshot(source, target, [(10, 10, 40, 30)], {0}, 'Pixelate', page=2)
            self.assertEqual(job.page, 2)
            export.write_copy(job)
            log = json.loads(target.with_suffix('.redactions.json').read_text(encoding='utf-8'))
            self.assertEqual(log['source_page'], 2)

    def test_export_refuses_to_overwrite_and_rolls_back_the_sidecar(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            target.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                export.write_copy(export.snapshot(source, target, [], set(), 'Pixelate'))
            self.assertEqual(target.read_bytes(), b'original')
            self.assertFalse(target.with_suffix('.redactions.json').exists())
            self.assertEqual(sorted(path.name for path in Path(folder).iterdir()),
                             ['copy.png', 'source.png'])

    def test_include_log_false_writes_no_sidecar(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            export.write_copy(export.snapshot(source, target, [(10, 10, 40, 30)], {0},
                                              'Solid black'), include_log=False)
            self.assertTrue(target.is_file())
            self.assertFalse(target.with_suffix('.redactions.json').exists())

    def test_export_preserves_pixels_outside_selected_boxes_and_audits(self):
        with TemporaryDirectory() as folder:
            source = self.make_source(folder)
            target = Path(folder) / 'copy.png'
            export.write_copy(export.snapshot(source, target, [(10, 10, 40, 30)], {0},
                                              'Solid black'))
            with Image.open(source) as handle:
                original = handle.convert('RGB')
            with Image.open(target) as handle:
                exported = handle.convert('RGB')
        exact, _ = audit_exports.audit_export(original, exported, [(10, 10, 40, 30)])
        self.assertTrue(exact)
        self.assertEqual(original.getpixel((70, 60)), exported.getpixel((70, 60)))
        self.assertEqual(exported.getpixel((20, 20)), (0, 0, 0))

    def test_snapshot_freezes_the_entry_state(self):
        job = export.snapshot(Path('source.png'), Path('out.png'), [(1, 1, 5, 5)], {0},
                              'Pixelate')
        self.assertEqual(job.boxes, ((1, 1, 5, 5),))
        self.assertEqual(job.selected, frozenset({0}))
        self.assertEqual(job.selected_boxes, [(1, 1, 5, 5)])

    def test_output_path_names_and_rejects_unsafe_templates(self):
        self.assertEqual(export.output_path(Path('out'), '{stem}-{index}', Path('shot.PNG'), 2),
                         Path('out') / 'shot-2.png')
        with self.assertRaises(ValueError):
            export.output_path(Path('out'), 'bad/name', Path('a.png'), 1)


class RedactionTests(unittest.TestCase):
    def test_failed_png_encoding_does_not_publish_partial_file(self):
        class BrokenImage:
            width = height = 100

            def save(self, stream, **options):
                stream.write(b'incomplete')
                raise OSError('write failed')

        with TemporaryDirectory() as folder:
            target = Path(folder) / 'test.png'
            with self.assertRaises(OSError):
                save_export(BrokenImage(), target, {'boxes': []})
            self.assertEqual(list(Path(folder).iterdir()), [])
            target.write_bytes(b'existing')
            with self.assertRaises(FileExistsError):
                save_export(Image.new('RGB', (10, 10)), target, {'boxes': []})
            self.assertEqual(target.read_bytes(), b'existing')
            self.assertEqual(list(Path(folder).iterdir()), [target])
