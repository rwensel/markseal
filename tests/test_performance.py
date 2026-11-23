"""Parallel jobs, engine pool, and performance traces."""
import unittest

from tests.support import (
    Barrier,
    FakeEngine,
    Image,
    Lock,
    Path,
    PerformanceRun,
    SimpleNamespace,
    TemporaryDirectory,
    Thread,
    batch_worker_count,
    json,
    patch,
    rapidocr_backend,
    stage,
)


class PerformanceTests(unittest.TestCase):
    def test_batch_worker_count_is_bounded_by_jobs_and_limit(self):
        self.assertEqual(batch_worker_count(3, 10, 8), 3)
        self.assertEqual(batch_worker_count(0, 10, 8), 1)
        self.assertEqual(batch_worker_count(99, 4, 8), 4)
        self.assertEqual(batch_worker_count(2, 0, 8), 1)

    def test_parallel_performance_traces_remain_valid_jsonl(self):
        with TemporaryDirectory() as folder, patch('redactor.performance_log.log_directory', return_value=Path(folder)):
            run = PerformanceRun('Scanning', 4)
            barrier = Barrier(4)

            def record(index):
                barrier.wait()
                with run.image(index):
                    pass

            threads = [Thread(target=record, args=(index,)) for index in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            run.finish()

            events = [json.loads(line) for line in run.path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(sum(event.get('event') == 'image' for event in events), 4)
            self.assertEqual(events[-1]['event'], 'finish')
            self.assertEqual(events[-1]['attempted'], 4)
            self.assertEqual(events[-1]['failed'], 0)

    def test_rapidocr_pool_allows_concurrent_engine_calls(self):
        active = [0]
        peak = [0]
        guard = Lock()
        barrier = Barrier(2)

        class FakeEngine:
            def __call__(self, image, **options):
                with guard:
                    active[0] += 1
                    peak[0] = max(peak[0], active[0])
                barrier.wait()
                with guard:
                    active[0] -= 1
                return SimpleNamespace(boxes=None, txts=None)

        pool = rapidocr_backend.EnginePool(lambda: FakeEngine())
        with patch('redactor.rapidocr_backend._pool', pool):
            threads = [Thread(target=rapidocr_backend.recognize_words,
                              args=(Image.new('RGB', (20, 20)),)) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(peak[0], 2)

    def test_performance_log_records_timings_without_exception_message(self):
        with TemporaryDirectory() as folder, patch('redactor.performance_log.log_directory', return_value=Path(folder)):
            run = PerformanceRun('Scanning', 1)
            with self.assertRaises(OSError), run.image(0), stage('OCR'):
                raise OSError('private filename')
            run.finish()
            raw = run.path.read_text(encoding='utf-8')
            self.assertNotIn('private filename', raw)
            start, image, end = map(json.loads, raw.splitlines())
            self.assertEqual(image['image_index'], 1)
            self.assertEqual(image['stages'][0]['error_type'], 'OSError')
            self.assertGreaterEqual(image['stages'][0]['elapsed_ms'], 0)
            self.assertEqual(end['failed'], 1)
