"""Run a batch of image jobs on a bounded pool of daemon threads.

The module has no Qt imports. The controller owns the timer and the widgets;
it calls :meth:`JobRunner.poll` from its event loop and renders the plain
events this module returns. Jobs, results, progress text and the finish
summary are plain data so the runner is testable without a QApplication.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
from typing import Any, Callable

from .performance_log import PerformanceRun


class ScanCancelled(Exception):
    """The user stopped a scan before this image finished."""


def batch_worker_count(requested, job_count, limit):
    return max(1, min(int(requested), max(1, int(job_count)), max(1, int(limit))))


def job_path(job):
    target = job[0] if isinstance(job, tuple) else job
    return Path(getattr(target, 'path', target))


def job_display_name(job):
    return job_path(job).name


def progress_line(label, completed, total, jobs, workers=1):
    """Progress board text and the current-image line for one poll tick."""
    percent = completed * 100 // total if total else 0
    note = f' · {workers} parallel' if workers > 1 else ''
    text = f'{label} · {completed}/{total} processed ({percent}%){note}'
    if workers > 1:
        current = f'{workers} parallel workers'
    elif completed < len(jobs):
        current = f'Current image: {job_display_name(jobs[completed])}'
    else:
        current = ''
    return text, current


@dataclass
class BatchSummary:
    label: str
    completed: int
    total: int
    failures: tuple[str, ...]
    canceled: bool
    trace_available: bool
    finish: Callable[[], str] | None
    complete: Callable[[], None] | None
    report_failures: bool

    def lines(self):
        """Final progress text and detail line, after every result was accepted."""
        detail = (self.finish() if self.finish is not None
                  else f'{self.completed - len(self.failures)} succeeded')
        if self.canceled:
            detail += f' · {self.total - self.completed} remaining'
        if self.failures:
            detail += f' · {len(self.failures)} failed'
        if not self.trace_available:
            detail += ' · performance log unavailable'
        outcome = 'Scan canceled' if self.canceled else f'{self.label} finished'
        return f'{outcome} · {self.completed}/{self.total} processed', detail


@dataclass
class BatchEvents:
    stages: tuple[str, ...] = ()
    started: tuple[int, ...] = ()
    results: tuple[tuple[int, Any, str | None], ...] = ()
    result_rows: tuple[int | None, ...] = ()
    completed: int = 0
    progress_changed: bool = False
    finished: bool = False
    summary: BatchSummary | None = None


@dataclass
class _Batch:
    label: str
    jobs: list
    operation: Callable[[Any], Any]
    accept: Callable[[int, Any, str | None], None]
    finish: Callable[[], str] | None
    cancel: Event | None
    show_image: Callable[[int], None] | None
    workers: int
    stage_queue: Queue | None
    complete: Callable[[], None] | None
    report_failures: bool
    queue: Queue
    pending: Queue
    failures: list
    advance: Event | None
    stop: Event
    trace: PerformanceRun
    job_rows: list
    done: Event
    total: int
    completed: int = 0

    @property
    def paced(self):
        return self.advance is not None

    @property
    def canceled(self):
        return self.cancel is not None and self.cancel.is_set()

    @property
    def cancel_pending(self):
        return self.canceled and self.completed < self.total


class JobRunner:
    """Own threads, queues and pacing for one batch of jobs at a time.

    ``accept`` runs on the caller's polling thread, in queue order; ``finish``
    runs through the returned summary once every result was accepted.
    """

    def __init__(self, limit, trace_factory=PerformanceRun):
        self.limit = max(1, int(limit))
        self._trace_factory = trace_factory
        self._batch: _Batch | None = None
        self.generation = 0

    @property
    def busy(self):
        return self._batch is not None

    @property
    def paced(self):
        return self._batch is not None and self._batch.paced

    @property
    def can_cancel(self):
        return self._batch is not None and self._batch.cancel is not None

    @property
    def cancel_pending(self):
        return self._batch is not None and self._batch.cancel_pending

    @property
    def label(self):
        return self._batch.label if self._batch is not None else ''

    @property
    def jobs(self):
        return list(self._batch.jobs) if self._batch is not None else []

    @property
    def total(self):
        return self._batch.total if self._batch is not None else 0

    @property
    def completed(self):
        return self._batch.completed if self._batch is not None else 0

    @property
    def workers(self):
        return self._batch.workers if self._batch is not None else 1

    @property
    def job_rows(self):
        return list(self._batch.job_rows) if self._batch is not None else []

    def start(self, label, jobs, operation, accept, finish=None, *, cancel=None,
              show_image=None, metrics_settings=None, rows=None, workers=1,
              stage_queue=None, complete=None, report_failures=True):
        if not jobs or self._batch is not None:
            return False
        jobs = list(jobs)
        total = len(jobs)
        worker_count = batch_worker_count(workers, total, self.limit)
        paced = show_image is not None and worker_count == 1
        queue = Queue()
        pending = Queue()
        for index in range(total):
            pending.put(index)
        advance = Event() if paced else None
        stop = Event()
        failures = []
        done = Event()
        job_rows = [rows.get(job_path(job)) if rows else None for job in jobs]
        trace_settings = dict(metrics_settings or {})
        trace_settings['parallel_jobs'] = worker_count
        trace = self._trace_factory(label, total, trace_settings)

        def worker():
            while not stop.is_set():
                try:
                    index = pending.get_nowait()
                except Empty:
                    return
                if cancel is not None and cancel.is_set():
                    return
                if advance is not None:
                    while not advance.wait(0.1):
                        if cancel is not None and cancel.is_set():
                            return
                    advance.clear()
                if cancel is not None and cancel.is_set():
                    return
                queue.put(('start', index))
                try:
                    with trace.image(index) as metrics:
                        result = operation(jobs[index])
                        if cancel is not None and isinstance(result, tuple) and len(result) == 3:
                            metrics.update(suggestions=len(result[1]),
                                           incomplete_passes=len(result[2]))
                    queue.put(('result', index, result, None))
                except ScanCancelled:
                    return
                except Exception as error:
                    queue.put(('result', index, None, str(error)))

        threads = [Thread(target=worker, daemon=True) for _ in range(worker_count)]

        def coordinator():
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            trace.finish(stopped=cancel is not None and cancel.is_set())
            queue.put(None)
            done.set()

        self._batch = _Batch(
            label=label, jobs=jobs, operation=operation, accept=accept, finish=finish,
            cancel=cancel, show_image=show_image, workers=worker_count,
            stage_queue=stage_queue, complete=complete, report_failures=report_failures,
            queue=queue, pending=pending, failures=failures, advance=advance, stop=stop,
            trace=trace, job_rows=job_rows, done=done, total=total,
        )
        self.generation += 1
        Thread(target=coordinator, daemon=True).start()
        return True

    def poll(self):
        """Drain finished work. Returns None when no batch is running."""
        batch = self._batch
        if batch is None:
            return None
        previous = batch.completed
        stages = []
        if batch.stage_queue is not None:
            while True:
                try:
                    stages.append(batch.stage_queue.get_nowait())
                except Empty:
                    break
        started = []
        results = []
        finished = False
        while True:
            try:
                item = batch.queue.get_nowait()
            except Empty:
                break
            if item is None:
                finished = True
                break
            if item[0] == 'start':
                started.append(item[1])
                continue
            _, index, result, error = item
            batch.accept(index, result, error)
            if error is not None:
                batch.failures.append(error or 'Unknown error')
            batch.completed += 1
            results.append((index, result, error))
        events = BatchEvents(
            stages=tuple(stages),
            started=tuple(started),
            results=tuple(results),
            result_rows=tuple(batch.job_rows[index] for index, _, _ in results),
            completed=batch.completed,
        )
        if not finished:
            events.progress_changed = batch.completed != previous
            return events
        self._batch = None
        if batch.cancel_pending:
            batch.stop.set()
        events.finished = True
        events.summary = BatchSummary(
            label=batch.label,
            completed=batch.completed,
            total=batch.total,
            failures=tuple(batch.failures),
            canceled=batch.cancel_pending,
            trace_available=batch.trace.available,
            finish=batch.finish,
            complete=batch.complete,
            report_failures=batch.report_failures,
        )
        return events

    def cancel(self):
        batch = self._batch
        if batch is None or batch.cancel is None:
            return False
        batch.cancel.set()
        return True

    def next_paced(self, generation):
        """Show the next image in a paced batch; returns its index or None."""
        batch = self._batch
        if batch is None or not batch.paced or self.generation != generation:
            return None
        if batch.canceled or batch.completed >= batch.total:
            return None
        index = batch.completed
        batch.show_image(index)
        return index

    def release_paced(self, generation):
        batch = self._batch
        if batch is None or not batch.paced or self.generation != generation:
            return False
        batch.advance.set()
        return True

    def wait(self, timeout=None):
        """Block until the current batch finishes (or no batch is running)."""
        batch = self._batch
        if batch is None:
            return True
        return batch.done.wait(timeout)
