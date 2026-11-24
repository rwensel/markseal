"""Non-Qt planning and result handling for scans, batch tools, and exports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import export
from .boxset import new_ocr_boxes


@dataclass(frozen=True)
class ScanPlan:
    entries: tuple
    label: str
    jobs: tuple
    rows: dict


def plan_scan(entries, selected, *, rescan=False, area=None):
    pending = tuple(
        entry for entry in selected if rescan or not (entry.scanned or entry.reviewed)
    )
    return ScanPlan(
        entries=pending,
        label='Scanning area' if area is not None else 'Scanning',
        jobs=tuple((entry.path, entry.stamp) for entry in pending),
        rows={entry.path: index for index, entry in enumerate(entries)},
    )


@dataclass(frozen=True)
class ScanOutcome:
    count: int
    changed: bool
    incomplete: tuple
    error: str = ''


def apply_scan_result(entry, result, *, area=None):
    stamp, found, incomplete = result
    if entry.stamp is not None and entry.stamp != stamp:
        entry.error = 'Source changed'
        return ScanOutcome(0, False, tuple(incomplete), 'Source changed')
    entry.stamp = stamp
    if area is None:
        count = entry.add_suggestions(found, incomplete)
        changed = True
    else:
        added = new_ocr_boxes(found, entry.boxes)
        count = len(added)
        changed = entry.add_shared_boxes(added, found.rules, source='Area OCR')
    return ScanOutcome(count, changed, tuple(incomplete))


def scan_summary(processed, *, area=None, area_completed=False):
    if area is not None:
        return ('Area scan finished · review suggested boxes'
                if processed and area_completed else 'No area results')
    complete = sum(
        entry.scanned and not entry.incomplete_ocr and not entry.error
        for entry in processed
    )
    partial = sum(bool(entry.incomplete_ocr) and not entry.error for entry in processed)
    return f'{complete} succeeded' + (f' · {partial} partial' if partial else '')


@dataclass(frozen=True)
class ExportPlan:
    jobs: tuple
    unredacted: int


def plan_exports(pending, *, output_directory, template, include_log, choose=None):
    jobs = []
    targets = set()
    for index, entry in pending:
        target = export.output_path(output_directory, template, entry.path, index + 1)
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
            if key in targets or path.exists():
                raise ValueError(
                    f'{path.name} already exists or would be written twice. '
                    'Choose another name or folder.'
                )
            targets.add(key)
        jobs.append((entry, target))
    return ExportPlan(tuple(jobs), sum(not entry.selected for _, entry in pending))


def export_succeeded(entry, snapshot):
    return (
        entry.reviewed
        and (tuple(entry.boxes), set(entry.selected), entry.method)
        == (tuple(snapshot.boxes), set(snapshot.selected), snapshot.method)
    )


def auto_export_snapshot(entry, output_directory, template, include_log):
    """Confirm one image and plan its own export, refusing an existing target."""
    entry.reviewed = True
    plan = plan_exports(
        [(0, entry)], output_directory=output_directory,
        template=template, include_log=include_log,
    )
    _entry, target = plan.jobs[0]
    return export.snapshot(entry.path, target, entry.boxes, entry.selected,
                           entry.method, stamp=entry.stamp), include_log


def copy_boxes_to_entry(entry, boxes, stamp, matches):
    if not matches or (entry.stamp is not None and entry.stamp != stamp):
        return 'skipped'
    entry.stamp = stamp
    return 'applied' if entry.add_shared_boxes(boxes, source='Copied box') else 'unchanged'


def match_boxes_to_entry(entry, placed, stamp):
    if not placed or (entry.stamp is not None and entry.stamp != stamp):
        return False, False
    entry.stamp = stamp
    return True, entry.add_shared_boxes(placed, source='Anchor match')


def eligible_for_confirmation(entries):
    return [entry for entry in entries
            if entry.selected and not entry.error and not entry.reviewed]


def confirmation_prompt(pending, method):
    prompt = f'Apply {method} to the selected boxes on {len(pending)} image(s)?'
    partial = sum(bool(entry.incomplete_ocr) for entry in pending)
    if partial:
        prompt += (f'\n\n{partial} image(s) have partial scans. '
                   'Confirm only if you have checked those images for missed sensitive text.')
    return prompt
