from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import export
from .audit_exports import verify_export


@dataclass(frozen=True)
class CopyRequest:
    source: Path
    method: str
    boxes: tuple = ()
    selected: frozenset = frozenset()
    entry: object | None = None
    stamp: tuple | None = None
    image: object | None = None
    pasted: bool = False
    page: int | None = None
    target: Path | None = None

    @classmethod
    def from_entry(cls, entry):
        return cls(
            source=Path(entry.path),
            method=entry.method,
            boxes=tuple(entry.boxes),
            selected=frozenset(entry.selected),
            entry=entry,
            stamp=entry.stamp,
        )


@dataclass(frozen=True)
class PlannedCopy:
    request: CopyRequest
    target: Path


@dataclass(frozen=True)
class CopyPlan:
    jobs: tuple[PlannedCopy, ...]
    unredacted: int
    include_log: bool


class ExportCopies:
    def __init__(self, preferences):
        self.preferences = preferences

    def plan(self, requests, *, output_directory, choose=None, allow_overwrite=False):
        jobs = []
        targets = set()
        include_log = bool(self.preferences.include_log)
        for index, request in enumerate(requests):
            if request.target is not None:
                target = Path(request.target)
            else:
                directory = (output_directory(request.entry)
                             if callable(output_directory) else output_directory)
                target = export.output_path(
                    directory, self.preferences.filename_template,
                    Path(request.source), index + 1)
            if choose is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                chosen = choose(target)
                if chosen is None:
                    return None
                target = Path(chosen)
                if target.suffix.lower() != '.png':
                    raise ValueError('Choose a filename ending in .png.')
            outputs = [target]
            if include_log:
                outputs.append(target.with_suffix('.redactions.json'))
            for path in outputs:
                key = str(path.resolve()).casefold()
                if key in targets or (not allow_overwrite and path.exists()):
                    raise ValueError(
                        f'{path.name} already exists or would be written twice. '
                        'Choose another name or folder.'
                    )
                targets.add(key)
            jobs.append(PlannedCopy(request, target))
        return CopyPlan(
            tuple(jobs),
            sum(not request.selected for request in requests),
            include_log,
        )

    def snapshot(self, planned):
        request = planned.request
        return export.snapshot(
            request.source, planned.target, request.boxes, request.selected,
            request.method, stamp=request.stamp, image=request.image,
            pasted=request.pasted, page=request.page,
        )

    def write(self, job, *, include_log=True, overwrite=False):
        export.write_copy(job, include_log=include_log, overwrite=overwrite)

    def verify(self, target, originals, *, patterns=(), run_ocr=False):
        return verify_export(target, originals, patterns=patterns, run_ocr=run_ocr)

    def auto_snapshot(self, entry, output_directory):
        entry.confirm(True)
        plan = self.plan(
            [CopyRequest.from_entry(entry)], output_directory=output_directory)
        planned = plan.jobs[0]
        return self.snapshot(planned), plan.include_log


def export_succeeded(entry, snapshot):
    return (
        entry.reviewed
        and (tuple(entry.boxes), set(entry.selected), entry.method)
        == (tuple(snapshot.boxes), set(snapshot.selected), snapshot.method)
    )
