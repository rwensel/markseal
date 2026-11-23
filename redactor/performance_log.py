"""Local performance traces. Never records images, OCR text, filenames, or error messages."""
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from threading import RLock
from time import perf_counter
from uuid import uuid4

_current = ContextVar('redactor_metrics', default=None)


def log_directory():
    local = os.environ.get('LOCALAPPDATA')
    return (Path(local) if local else Path.home() / '.config') / 'OfflineScreenshotRedactor' / 'performance'


def now_ms():
    return perf_counter() * 1000


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def stage(name, **details):
    stages = _current.get()
    if stages is None:
        yield
        return
    start = now_ms()
    entry = {'stage': name, 'started_ms': round(start-stages[0], 2), **details}
    stages[1].append(entry)
    try:
        yield entry
    except Exception as error:
        entry['error_type'] = type(error).__name__
        raise
    finally:
        entry['elapsed_ms'] = round(now_ms()-start, 2)


def timed(name):
    def decorate(function):
        @wraps(function)
        def call(*args, **kwargs):
            with stage(name):
                return function(*args, **kwargs)
        return call
    return decorate


class PerformanceRun:
    def __init__(self, operation, total, settings=None):
        self.started = now_ms()
        self.previous_end = self.started
        self.path = log_directory() / f'{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}.jsonl'
        self.durations = []
        self.failed = 0
        self.canceled = 0
        self.available = True
        self._lock = RLock()
        self.write({'event': 'start', 'utc': timestamp(), 'operation': operation,
                    'planned_images': total, 'settings': settings or {}})

    def write(self, entry):
        if not self.available:
            return
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open('a', encoding='utf-8') as file:
                    file.write(json.dumps(entry) + '\n')
        except OSError:
            self.available = False

    @contextmanager
    def image(self, index):
        start = now_ms()
        stages = []
        token = _current.set((start, stages))
        with self._lock:
            gap = start - self.previous_end
        item = {'event': 'image', 'image_index': index+1, 'gap_ms': round(gap, 2),
                'outcome': 'ok', 'stages': stages}
        try:
            yield item
        except Exception as error:
            item['error_type'] = type(error).__name__
            with self._lock:
                if item['error_type'] == 'ScanCancelled':
                    self.canceled += 1
                    item['outcome'] = 'canceled'
                else:
                    self.failed += 1
                    item['outcome'] = 'failed'
            raise
        finally:
            _current.reset(token)
            with self._lock:
                self.previous_end = now_ms()
                elapsed = round(self.previous_end-start, 2)
                self.durations.append(elapsed)
                item['elapsed_ms'] = elapsed
                self.write(item)

    def finish(self, stopped=False):
        with self._lock:
            self.write({'event': 'finish', 'utc': timestamp(), 'wall_ms': round(now_ms()-self.started, 2),
                        'attempted': len(self.durations), 'failed': self.failed,
                        'canceled_images': self.canceled, 'stopped': stopped,
                        'average_image_ms': round(sum(self.durations)/len(self.durations), 2) if self.durations else None})



def summarize(path):
    from collections import defaultdict
    from math import ceil

    times = defaultdict(list)
    additions = defaultdict(int)
    with path.open(encoding='utf-8') as file:
        for line in file:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # A currently running job may be writing its last line.
            if event.get('event') == 'image':
                times['image total'].append(event['elapsed_ms'])
                times['gap before image'].append(event['gap_ms'])
                for item in event['stages']:
                    name = item.get('pass_name', item['stage'])
                    times[name].append(item['elapsed_ms'])
                    if 'new_suggestions' in item:
                        additions[name] += item['new_suggestions']
    print(path.name)
    print(f'{"Stage":30} {"Count":>6} {"Mean ms":>10} {"P95 ms":>10} {"New boxes":>10}')
    for name, samples in times.items():
        samples.sort()
        print(f'{name:30} {len(samples):6} {sum(samples)/len(samples):10.1f} '
              f'{samples[ceil(.95*len(samples))-1]:10.1f} {str(additions.get(name, "")):>10}')


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description='Summarize timings from an offline redactor run.')
    parser.add_argument('trace', type=Path, nargs='?', help='JSONL file. Defaults to the latest run.')
    args = parser.parse_args(argv)
    path = args.trace or max(log_directory().glob('*.jsonl'), default=None, key=lambda p: p.stat().st_mtime)
    if path is None:
        parser.error('No performance traces found. Run a scan or export first.')
    summarize(path)


if __name__ == '__main__':
    main()
