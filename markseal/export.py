"""One owner for export naming, snapshots, coordinate logs and atomic publish."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from .performance_log import stage

from .images import read_folder_image
from .redaction import apply_redactions

PNG_COMPRESSION = 3
NOTE = ('Automated suggestions can miss identifiers; manual review required. '
        'Pixelation may not fully conceal sensitive content.')


def output_path(directory, template, source, index):
    name = template.format(stem=source.stem, ext=source.suffix[1:].lower(), index=index)
    if not name.lower().endswith('.png'):
        name += '.png'
    if (not name[:-4].strip(' .') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.startswith(' ') or re.fullmatch(r'(?i)(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', name.split('.')[0].rstrip(' '))):
        raise ValueError('Enter a valid filename template without folders.')
    return directory / name


def stage_export(target, write):
    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, suffix='.redactor-tmp', delete=False) as stream:
            temporary = Path(stream.name)
            write(stream)
        return temporary
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def publish_export(temporary, target, overwrite=False):
    if overwrite:
        temporary.replace(target)
    elif os.name == 'nt':
        temporary.rename(target)  # On Windows rename fails if target exists.
    else:
        os.link(temporary, target)


def save_export(image, target, log, *, overwrite=False):
    temporary_files = []
    published = []
    try:
        with stage('encode_png', width=image.width, height=image.height, compression_level=PNG_COMPRESSION):
            png = stage_export(target, lambda stream: image.save(
                stream, format='PNG', compress_level=PNG_COMPRESSION))
            temporary_files.append(png)
        log_target = target.with_suffix('.redactions.json')
        if log is not None:
            with stage('encode_coordinate_log'):
                sidecar = stage_export(log_target, lambda stream: stream.write(
                    json.dumps(log, indent=2).encode('utf-8')))
                temporary_files.append(sidecar)
        with stage('publish_export'):
            if log is not None:
                publish_export(sidecar, log_target, overwrite)
                published.append(log_target)
            publish_export(png, target, overwrite)
    except Exception:
        if not overwrite:
            for path in published:
                path.unlink(missing_ok=True)
        raise
    finally:
        for path in temporary_files:
            path.unlink(missing_ok=True)


def coordinate_log(source, target, dimensions, boxes, method, *, note=NOTE, pasted=False,
                   source_page=None):
    message = note
    if pasted:
        message += ' No source file exists; this copy came from an in-memory image (paste or screen capture).'
    log = {
        'source_filename': Path(source).name,
        'output_filename': Path(target).name,
        'image_dimensions': list(dimensions),
        'redaction_rectangles_xyxy': list(boxes),
        'created_local_time': datetime.now().isoformat(timespec='seconds'),
        'method': method,
        'note': message,
    }
    if source_page is not None:
        log['source_page'] = source_page
    return log


@dataclass(frozen=True)
class ExportJob:
    source: Path
    target: Path
    boxes: tuple
    selected: frozenset
    method: str
    stamp: tuple | None = None
    image: object | None = None
    pasted: bool = False
    page: int | None = None

    @property
    def selected_boxes(self):
        return [box for index, box in enumerate(self.boxes) if index in self.selected]


def snapshot(source, target, boxes, selected, method, *, stamp=None, image=None, pasted=False,
             page=None):
    return ExportJob(
        source=Path(source),
        target=Path(target),
        boxes=tuple(boxes),
        selected=frozenset(selected),
        method=method,
        stamp=stamp,
        image=image,
        pasted=pasted,
        page=page,
    )


def write_copy(job, *, include_log=True, overwrite=False):
    if job.image is not None:
        image = job.image
    else:
        image, _ = read_folder_image(job.source, job.stamp)
    boxes = job.selected_boxes
    rendered = apply_redactions(image, boxes, job.method)
    rendered.info.clear()
    log = (coordinate_log(job.source, job.target, image.size, boxes, job.method,
                          pasted=job.pasted, source_page=job.page)
           if include_log else None)
    save_export(rendered, job.target, log, overwrite=overwrite)


def write_folder_copy(entry, target, include_log):
    write_copy(snapshot(entry.path, target, entry.boxes, entry.selected, entry.method,
                        stamp=entry.stamp), include_log=include_log)
