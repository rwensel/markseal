"""Parallel job runner behavior."""
import unittest

from tests.support import (
    Barrier,
    Event,
    JobRunner,
    Lock,
    Path,
    TemporaryDirectory,
    json,
    patch,
    progress_line,
    time,
)


class JobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.log_patch = patch('redactor.performance_log.log_directory',
                               return_value=Path(self.temporary.name))
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def drain_until(self, runner, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = runner.poll()
            if events is not None and predicate(events):
                return events
            time.sleep(0.005)
        self.fail('runner did not reach the expected state')

    def test_parallel_batch_runs_workers_together_within_the_limit(self):
        runner = JobRunner(limit=2)
        barrier = Barrier(2)
        guard = Lock()
        active = [0]
        peak = [0]
        accepted = []

        def operation(job):
            with guard:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            barrier.wait(5)
            with guard:
                active[0] -= 1
            return job

        self.assertTrue(runner.start('Parallel', [0, 1, 2, 3], operation,
                                     lambda index, result, error: accepted.append(index),
                                     workers=8))
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.finished)
        self.assertEqual(events.completed, 4)
        self.assertEqual(sorted(accepted), [0, 1, 2, 3])
        self.assertEqual(peak[0], 2)

    def test_cancel_stops_queued_work_and_reports_the_remaining_count(self):
        runner = JobRunner(limit=1)
        cancel = Event()
        release = Event()
        started = []

        def operation(job):
            started.append(job)
            release.wait(5)
            return job

        self.assertTrue(runner.start('Cancel', [0, 1, 2], operation,
                                     lambda index, result, error: None, cancel=cancel))
        events = self.drain_until(runner, lambda item: bool(item.started))
        self.assertEqual(events.started, (0,))
        self.assertTrue(runner.cancel())
        self.assertTrue(runner.cancel_pending)
        release.set()
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.finished)
        self.assertEqual(started, [0])
        self.assertTrue(events.summary.canceled)
        text, detail = events.summary.lines()
        self.assertEqual(text, 'Scan canceled · 1/3 processed')
        self.assertIn('2 remaining', detail)

    def test_started_and_result_rows_follow_the_folder_rows(self):
        runner = JobRunner(limit=1)
        gate = Event()
        first, second = Path('a.png'), Path('b.png')

        def operation(job):
            gate.wait(5)
            return job

        self.assertTrue(runner.start('Rows', [first, second], operation,
                                     lambda index, result, error: None,
                                     rows={first: 0, second: 1}))
        events = self.drain_until(runner, lambda item: bool(item.started))
        self.assertEqual(events.started, (0,))
        self.assertEqual(runner.job_rows, [0, 1])
        gate.set()
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertEqual(events.result_rows, (0, 1))

    def test_failures_are_aggregated_through_accept(self):
        runner = JobRunner(limit=1)
        seen = []

        def operation(job):
            if job == 1:
                raise ValueError('broken job')
            return job

        self.assertTrue(runner.start('Failing', [0, 1, 2], operation,
                                     lambda index, result, error: seen.append((index, error)),
                                     workers=1))
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.finished)
        self.assertEqual(events.summary.failures, ('broken job',))
        self.assertEqual(events.summary.completed, 3)
        self.assertIn((1, 'broken job'), seen)
        self.assertEqual(events.summary.lines(),
                         ('Failing finished · 3/3 processed', '2 succeeded · 1 failed'))

    def test_paced_batch_releases_one_image_at_a_time(self):
        runner = JobRunner(limit=1)
        shown = []

        self.assertTrue(runner.start('Paced', [0, 1], lambda job: job,
                                     lambda index, result, error: None,
                                     show_image=shown.append))
        generation = runner.generation
        self.assertTrue(runner.paced)
        self.assertEqual(runner.next_paced(generation), 0)
        self.assertEqual(shown, [0])
        self.assertTrue(runner.release_paced(generation))
        self.drain_until(runner, lambda item: item.completed == 1)
        self.assertEqual(runner.next_paced(generation), 1)
        self.assertEqual(shown, [0, 1])
        self.assertTrue(runner.release_paced(generation))
        self.assertTrue(runner.wait(5))
        self.assertTrue(runner.poll().finished)
        self.assertIsNone(runner.next_paced(generation))

    def test_completed_batch_finishes_the_performance_trace(self):
        runner = JobRunner(limit=1)
        self.assertTrue(runner.start('Trace', [0, 1], lambda job: job,
                                     lambda index, result, error: None,
                                     metrics_settings={'engine': 'Fake'}))
        self.assertTrue(runner.wait(5))
        events = runner.poll()
        self.assertTrue(events.summary.trace_available)
        trace_files = list(Path(self.temporary.name).glob('*.jsonl'))
        self.assertEqual(len(trace_files), 1)
        entries = [json.loads(line) for line in
                   trace_files[0].read_text(encoding='utf-8').splitlines()]
        self.assertEqual(entries[0]['operation'], 'Trace')
        self.assertEqual(entries[0]['settings']['parallel_jobs'], 1)
        self.assertEqual(entries[-1]['event'], 'finish')
        self.assertEqual(entries[-1]['attempted'], 2)

    def test_progress_line_names_the_current_image_and_parallel_note(self):
        jobs = [Path('one.png'), Path('two.png')]
        self.assertEqual(progress_line('Scanning', 0, 2, jobs, 1),
                         ('Scanning · 0/2 processed (0%)', 'Current image: one.png'))
        self.assertEqual(progress_line('Scanning', 1, 2, jobs, 2),
                         ('Scanning · 1/2 processed (50%) · 2 parallel',
                          '2 parallel workers'))

    def test_runner_accepts_only_one_batch_at_a_time(self):
        runner = JobRunner(limit=1)
        gate = Event()

        def operation(job):
            gate.wait(5)
            return job

        self.assertTrue(runner.start('First', [0], operation,
                                     lambda index, result, error: None))
        self.assertFalse(runner.start('Second', [1], operation,
                                      lambda index, result, error: None))
        gate.set()
        self.assertTrue(runner.wait(5))
        runner.poll()
        self.assertFalse(runner.busy)
        self.assertFalse(runner.start('Second', [], operation,
                                      lambda index, result, error: None))
