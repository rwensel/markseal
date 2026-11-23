"""OCR seam: one adapter interface with a Tesseract and a RapidOCR adapter."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
from pathlib import Path
from time import monotonic

from performance_log import stage

from .jobs import ScanCancelled


def find_tesseract():
    bundled = Path(__file__).resolve().parent.parent / 'tools' / 'tesseract' / 'tesseract.exe'
    if bundled.is_file(): return str(bundled)
    found = shutil.which('tesseract')
    if found: return found
    for base in (os.environ.get('PROGRAMFILES', ''), os.environ.get('LOCALAPPDATA', '')):
        path = Path(base) / 'Tesseract-OCR' / 'tesseract.exe'
        if path.is_file(): return str(path)
    return None


def cancellable_ocr(command, data, creationflags, cancel, *, timeout=120, env=None):
    if cancel.is_set():
        raise ScanCancelled
    deadline = monotonic() + timeout
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, creationflags=creationflags, env=env) as process:
        pending_input = data
        try:
            while True:
                if cancel.is_set():
                    raise ScanCancelled
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(input=pending_input, timeout=min(0.15, remaining))
                    break
                except subprocess.TimeoutExpired:
                    # communicate retains its input and output across a timeout.
                    pending_input = None
        except (ScanCancelled, subprocess.TimeoutExpired):
            process.kill()
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        return stdout


class TesseractEngine:
    single_label = False

    def __init__(self, executable):
        self.executable = executable

    def recognize(self, image, *, psm=None, cancel=None, timeout=120):
        command = [self.executable, 'stdin', 'stdout']
        if psm:
            command.extend(['--psm', str(psm)])
        command.append('tsv')
        data = io.BytesIO()
        with stage('ocr_input_encoding', width=image.width, height=image.height):
            image.save(data, format='PNG')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        environment = {**os.environ, 'OMP_THREAD_LIMIT': '1'}
        with stage('tesseract_inference'):
            if cancel is None:
                result = subprocess.run(command, input=data.getvalue(), capture_output=True,
                                        timeout=timeout, check=True, creationflags=flags,
                                        env=environment)
                stdout = result.stdout
            else:
                stdout = cancellable_ocr(command, data.getvalue(), flags, cancel,
                                         timeout=timeout, env=environment)
        return stdout.decode('utf-8', errors='replace')


class RapidEngine:
    single_label = True

    def recognize(self, image, *, psm=None, cancel=None, timeout=120):
        from rapidocr_backend import recognize_words
        with stage('rapidocr_inference', width=image.width, height=image.height):
            return recognize_words(image)

    def read_label(self, crop):
        from rapidocr_backend import recognize_single_label
        return recognize_single_label(crop)


def make_engine(name, executable=None):
    if name == 'RapidOCR':
        from rapidocr_backend import model_files
        model_files()
        return RapidEngine()
    if executable is None:
        executable = find_tesseract()
    if not executable:
        raise OSError('Restore Tesseract in tools/tesseract or add it to PATH.')
    return TesseractEngine(executable)
