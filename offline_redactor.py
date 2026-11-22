"""Offline image redactor. Requires Python 3 and Pillow. No network calls."""
import json
import math
import csv
import io
import os
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile
from dataclasses import dataclass, field
from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageTk, ImageDraw, ImageOps, ImageFilter

# Very coarse blocks remove fine detail, but mosaic redaction can remain reversible.
def pixelate(image, boxes, block_size=32):
    out = image.copy()
    for x1, y1, x2, y2 in boxes:
        crop = out.crop((x1, y1, x2, y2))
        small = crop.resize((max(1, (x2-x1)//block_size), max(1, (y2-y1)//block_size)), Image.Resampling.BOX)
        out.paste(small.resize(crop.size, Image.Resampling.NEAREST), (x1, y1))
    return out

PATTERNS = {
    'Emails': r"[\w.+-]+@[\w.-]+\.[a-z]{2,}",
    'URLs': r"(?:https?://|www\.)\S+|(?<![\w@.-])[a-z0-9-]+\.(?:com|org|net|io|local|internal)\b|\blocalhost(?::\d+)?(?:/\S*)?",
    'IP addresses': r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    'Ticket IDs': r"\b[A-Z][A-Z0-9]{1,9}-\d+\b",
    'Paths': r"(?:[a-z]:\\|/home/|/users/|\\\\)\S+",
    'Hashes': r"\b[0-9a-f]{7,64}\b",
    'Secrets': (
        r"(?<![\w.-])(?:[\w.-]*[_-])?(?:token|password|passwd|secret|api[_-]?key|"
        r"access[_-]?key(?:[_-]?id)?|private[_-]?key|client[_-]?secret|secret[_-]?name)"
        r"\s*[:=]\s*[^\s,}]+"
        r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\b(?:gh[pousr]_|github_pat_|glpat-|sk_(?:live|test)_)[\w-]{12,}"
        r"|\bBearer\s+[\w./+=-]{16,}|-----\s*BEGIN [A-Z0-9 ]*PRIVATE KEY\s*-----"
    ),
    'Infrastructure': (
        r"(?<![\w./-])(?:[\w.-]+/)+[\w.-]+\.(?:ya?ml|tf(?:vars)?|kubeconfig|crt|pem|key|p12|pfx)\b"
        r"|(?<![\w.-])/(?:etc|run/secrets|var/run/secrets|vault|secrets|opt)/[\w./-]+"
        r"|\b(?:VAULT|KUBE(?:RNETES)?|KAFKA|TLS|AWS|AZURE|GCP|DB|DATABASE|REDIS)"
        r"(?:\s*[_-]\s*[a-z0-9]+)+\b"
        r"|\b[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.(?:kafka|vault|kubernetes|tls|database)"
        r"(?:\.[a-z0-9_-]+)+\b"
        r"|\b(?:secret[_-]?name|secret[_-]?key[_-]?ref|config[_-]?map[_-]?ref|"
        r"cluster[_-]?name|namespace|service[_-]?account[_-]?name)\s*:\s*[\w.-]+"
        r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:svc(?:\.cluster\.local)?|corp|intranet)\b"
        r"|\barn:[a-z0-9-]+:[^\s,]+"
    ),
    'Long identifiers': r"\b[A-Za-z0-9_/-]{24,}\b",
}
PRESETS = {
    'Focused': {'Emails', 'URLs', 'IP addresses', 'Secrets', 'Infrastructure'},
    'Balanced': set(PATTERNS) - {'Long identifiers'},
    'Broad': set(PATTERNS),
}

def detect_regions(tsv, size, all_text=False, categories=None, min_confidence=0, custom_pattern=''):
    categories = set(PATTERNS) if categories is None else categories
    expressions = [re.compile(PATTERNS[name], re.IGNORECASE) for name in PATTERNS if name in categories]
    if custom_pattern: expressions.append(re.compile(custom_pattern, re.IGNORECASE))
    lines = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter='\t'):
        word = row.get('text', '').strip()
        if not word: continue
        try:
            confidence = float(row['conf'])
            left, top, width, height = (int(row[k]) for k in ('left','top','width','height'))
            key = tuple(row[k] for k in ('page_num','block_num','par_num','line_num'))
        except (ValueError, KeyError): continue
        if confidence < min_confidence or width <= 0 or height <= 0: continue
        lines.setdefault(key, []).append((word, left, top, left+width, top+height))
    boxes = []
    for words in lines.values():
        text = ' '.join(word[0] for word in words)
        spans = []
        if all_text:
            spans = [(0, len(text))]
        else:
            for expression in expressions:
                spans.extend((m.start(), m.end()) for m in expression.finditer(text) if m.end() > m.start())
        offset = 0
        for word, x1, y1, x2, y2 in words:
            start, end = offset, offset + len(word)
            if any(start < right and end > left for left, right in spans):
                box = (max(0,x1-4), max(0,y1-4), min(size[0],x2+4), min(size[1],y2+4))
                if box not in boxes: boxes.append(box)
            offset = end + 1
    return boxes

def apply_redactions(image, boxes, method='Pixelate'):
    if method == 'Pixelate': return pixelate(image, boxes)
    out = image.copy(); draw = ImageDraw.Draw(out)
    for x1, y1, x2, y2 in boxes: draw.rectangle((x1,y1,x2-1,y2-1), fill='black')
    return out

def find_tesseract():
    bundled = Path(__file__).resolve().parent / 'tools' / 'tesseract' / 'tesseract.exe'
    if bundled.is_file(): return str(bundled)
    found = shutil.which('tesseract')
    if found: return found
    for base in (os.environ.get('PROGRAMFILES', ''), os.environ.get('LOCALAPPDATA', '')):
        path = Path(base) / 'Tesseract-OCR' / 'tesseract.exe'
        if path.is_file(): return str(path)
    return None

def preferences_path():
    local = os.environ.get('LOCALAPPDATA')
    base = Path(local) if local else Path.home() / '.config'
    return base / 'OfflineScreenshotRedactor' / 'settings.json'


def write_preferences(path, preferences):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(preferences, stream, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Redactor:
    def __init__(self, root):
        self.root = root
        root.title('Offline Screenshot Redactor')
        self.image = None
        self.boxes = []
        self.selected = set()
        self.confirmed = False
        self.start = None
        self.zoom = 1.0
        self.offset_x = self.offset_y = 0.0
        self.pan_start = None
        bar = self.toolbar = tk.Frame(root); bar.pack(fill='x')
        for title, action in [('Open image', self.open), ('Find likely identifiers', self.find), ('Undo last box', self.undo), ('Confirm selection', self.confirm_selection), ('Save redacted copy', self.save)]:
            tk.Button(bar, text=title, command=action).pack(side='left', padx=4, pady=4)
        self.all_text = tk.BooleanVar(value=False)
        self.enhanced_ocr = tk.BooleanVar(value=False)
        self.color_ocr = tk.BooleanVar(value=False)
        self.sensitivity = tk.StringVar(value='Focused')
        self.confidence = tk.IntVar(value=50)
        self.method = tk.StringVar(value='Pixelate')
        self.default_method = self.method.get()
        self.preferences_file = preferences_path()
        self.custom_pattern = tk.StringVar(value='')
        self.category_vars = {name: tk.BooleanVar(value=name in PRESETS['Focused']) for name in PATTERNS}
        ttk.Button(bar, text='Edit boxes', command=self.edit_boxes).pack(side='left', padx=4)
        ttk.Button(bar, text='Clear boxes', command=self.clear_boxes).pack(side='left', padx=4)
        ttk.Button(bar, text='Settings…', command=self.open_settings).pack(side='right', padx=8)
        self.status = tk.Label(root, text='Click boxes to select or deselect; drag to add. Green = selected; orange = unselected. Confirm to apply.', anchor='w')
        self.status.pack(fill='x')
        self.workspace = tk.Frame(root)
        self.workspace.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(self.workspace, bg='#333333', width=1200, height=760, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self.down)
        self.canvas.bind('<B1-Motion>', self.move)
        self.canvas.bind('<ButtonRelease-1>', self.up)
        self.canvas.bind('<Configure>', lambda e: self.render())
        self.canvas.bind('<MouseWheel>', self.mouse_zoom)
        self.canvas.bind('<Button-4>', self.mouse_zoom)
        self.canvas.bind('<Button-5>', self.mouse_zoom)
        self.canvas.bind('<ButtonPress-3>', self.pan_down)
        self.canvas.bind('<B3-Motion>', self.pan_move)
        self.canvas.bind('<ButtonRelease-3>', self.pan_up)

    def open_settings(self):
        window = tk.Toplevel(self.root)
        window.title('Settings')
        window.transient(self.root)
        window.grab_set()

        notebook = ttk.Notebook(window)
        notebook.pack(fill='both', expand=True, padx=12, pady=(12, 8))
        detection = ttk.Frame(notebook, padding=12)
        redaction = ttk.Frame(notebook, padding=12)
        notebook.add(detection, text='Detection')
        notebook.add(redaction, text='Redaction')

        sensitivity = tk.StringVar(window, value=self.sensitivity.get())
        confidence = tk.StringVar(window, value=str(self.confidence.get()))
        all_text = tk.BooleanVar(window, value=self.all_text.get())
        enhanced = tk.BooleanVar(window, value=self.enhanced_ocr.get())
        color = tk.BooleanVar(window, value=self.color_ocr.get())
        method = tk.StringVar(window, value=self.method.get())
        pattern = tk.StringVar(window, value=self.custom_pattern.get())
        categories = {name: tk.BooleanVar(window, value=var.get()) for name, var in self.category_vars.items()}

        def apply_preset(event):
            preset = PRESETS.get(sensitivity.get())
            if preset is not None:
                for name, variable in categories.items():
                    variable.set(name in preset)

        ttk.Label(detection, text='Sensitivity').grid(row=0, column=0, sticky='w')
        presets = ttk.Combobox(detection, textvariable=sensitivity, values=[*PRESETS, 'Custom'],
                               state='readonly', width=12)
        presets.grid(row=0, column=1, sticky='w', padx=8)
        presets.bind('<<ComboboxSelected>>', apply_preset)
        ttk.Label(detection, text='Minimum OCR confidence (0–100)').grid(row=1, column=0, sticky='w', pady=6)
        ttk.Spinbox(detection, from_=0, to=100, textvariable=confidence, width=6).grid(
            row=1, column=1, sticky='w', padx=8)
        ttk.Checkbutton(detection, text='Enhanced OCR (slower, useful for screen photos)', variable=enhanced).grid(
            row=2, column=0, columnspan=2, sticky='w')
        ttk.Checkbutton(detection, text='Color-assisted OCR (slower, helps colored text)', variable=color).grid(
            row=3, column=0, columnspan=2, sticky='w')
        ttk.Checkbutton(detection, text='Suggest all detected text (bypasses patterns)', variable=all_text).grid(
            row=4, column=0, columnspan=2, sticky='w')

        patterns = ttk.LabelFrame(detection, text='Detection patterns', padding=8)
        patterns.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(8, 0))
        for index, (name, variable) in enumerate(categories.items()):
            ttk.Checkbutton(patterns, text=name, variable=variable,
                            command=lambda: sensitivity.set('Custom')).grid(
                row=index//2, column=index%2, sticky='w', padx=(0, 12))
        ttk.Label(detection, text='Custom regular expression').grid(row=6, column=0, sticky='w', pady=(8, 2))
        ttk.Entry(detection, textvariable=pattern).grid(row=7, column=0, columnspan=2, sticky='ew')
        ttk.Label(detection, text='Detection changes apply on the next scan.').grid(
            row=8, column=0, columnspan=2, sticky='w', pady=(6, 0))

        ttk.Label(redaction, text='Redaction method').grid(row=0, column=0, sticky='w')
        ttk.Combobox(redaction, textvariable=method, values=['Pixelate', 'Solid black'],
                     state='readonly', width=14).grid(row=0, column=1, sticky='w', padx=8)
        ttk.Label(redaction, text='Solid black fully covers the pixels within the selected boxes.',
                  wraplength=350).grid(row=1, column=0, columnspan=2, sticky='w', pady=(8, 0))
        prepare_output = self.build_output_settings(notebook)

        def apply():
            try:
                threshold = int(confidence.get())
                if not 0 <= threshold <= 100:
                    raise ValueError('OCR confidence must be between 0 and 100.')
                expression = pattern.get().strip()
                re.compile(expression)
                output = prepare_output() if prepare_output is not None else {}
                method_changed = method.get() != self.method.get()
                preferences = {
                    'sensitivity': sensitivity.get(),
                    'confidence': threshold,
                    'all_text': all_text.get(),
                    'enhanced_ocr': enhanced.get(),
                    'color_ocr': color.get(),
                    'custom_pattern': expression,
                    'categories': [name for name, variable in categories.items() if variable.get()],
                    'redaction_method': method.get() if method_changed else self.default_method,
                    **output,
                }
                write_preferences(self.preferences_file, preferences)
            except (ValueError, re.error, KeyError, IndexError, AttributeError) as error:
                messagebox.showerror('Invalid settings', str(error), parent=window)
                return
            except OSError as error:
                messagebox.showerror('Could not save settings', str(error), parent=window)
                return
            self.sensitivity.set(sensitivity.get())
            self.confidence.set(threshold)
            self.all_text.set(all_text.get())
            self.enhanced_ocr.set(enhanced.get())
            self.color_ocr.set(color.get())
            self.custom_pattern.set(expression)
            for name, variable in categories.items():
                self.category_vars[name].set(variable.get())
            self.restore_output_preferences(output)
            self.default_method = preferences['redaction_method']
            if method_changed:
                self.method.set(method.get())
                self.method_changed()
            window.destroy()

        footer = ttk.Frame(window, padding=(12, 0, 12, 12))
        footer.pack(fill='x')
        ttk.Button(footer, text='Apply', command=apply).pack(side='right')
        ttk.Button(footer, text='Cancel', command=window.destroy).pack(side='right', padx=(0, 6))
        window.bind('<Escape>', lambda event: window.destroy())
        window.protocol('WM_DELETE_WINDOW', apply)

    def load_preferences(self):
        try:
            saved = json.loads(self.preferences_file.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            self.status.config(text='Saved settings could not be loaded. Using defaults.')
            return
        if not isinstance(saved, dict):
            return
        preset = saved.get('sensitivity')
        if isinstance(preset, str) and preset in {*PRESETS, 'Custom'}:
            self.sensitivity.set(preset)
        categories = saved.get('categories')
        if isinstance(categories, list):
            for name, variable in self.category_vars.items():
                variable.set(name in categories)
        threshold = saved.get('confidence')
        if type(threshold) is int and 0 <= threshold <= 100:
            self.confidence.set(threshold)
        for key, variable in (('all_text', self.all_text), ('enhanced_ocr', self.enhanced_ocr),
                              ('color_ocr', self.color_ocr)):
            if isinstance(saved.get(key), bool):
                variable.set(saved[key])
        expression = saved.get('custom_pattern')
        if isinstance(expression, str):
            try:
                re.compile(expression)
            except re.error:
                pass
            else:
                self.custom_pattern.set(expression)
        method = saved.get('redaction_method')
        if method in ('Pixelate', 'Solid black'):
            self.default_method = method
            self.method.set(method)
        self.restore_output_preferences(saved)

    def restore_output_preferences(self, saved):
        pass

    def build_output_settings(self, notebook):
        return None

    def method_changed(self, event=None):
        if self.confirmed: self.render()

    def clear_boxes(self):
        if not self.boxes: return
        if not messagebox.askyesno('Clear boxes', 'Remove all suggested and manually drawn boxes?'): return
        self.boxes.clear(); self.selected.clear(); self.confirmed = False
        self.render(); self.status.config(text='Boxes cleared. Scan again or drag to add an area.')

    def open(self):
        if self.boxes and not messagebox.askyesno('Open another image', 'Discard the current unsaved markings?'):
            return
        path = filedialog.askopenfilename(filetypes=[('Images', '*.png *.jpg *.jpeg *.bmp *.tif *.tiff'), ('All files', '*.*')])
        if not path: return
        try:
            self.image = Image.open(path).convert('RGB')
        except Exception as e:
            messagebox.showerror('Cannot open image', str(e)); return
        self.path = Path(path); self.boxes = []; self.selected = set(); self.confirmed = False
        self.zoom = 1.0; self.offset_x = self.offset_y = 0.0
        self.start = self.pan_start = None
        self.canvas.configure(cursor='crosshair')
        self.render()
        self.status.config(text=f'{self.path.name}: find suggestions or drag to add a box, then confirm.')

    def render(self):
        if self.image is None: return
        w, h = self.image.size
        cw, ch = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        self.scale = min(cw / w, ch / h, 1.0) * self.zoom
        self.clamp_offsets()
        self.preview = apply_redactions(self.image, self.selected_boxes(), self.method.get()) if self.confirmed else self.image
        view = ((-self.offset_x)/self.scale, (-self.offset_y)/self.scale,
                (cw-self.offset_x)/self.scale, (ch-self.offset_y)/self.scale)
        displayed = self.preview.transform((cw, ch), Image.Transform.EXTENT, view,
                                           resample=Image.Resampling.BILINEAR, fillcolor='#333333')
        self.photo = ImageTk.PhotoImage(displayed)
        self.canvas.delete('all'); self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        if not self.confirmed:
            self.draw_boxes(cw, ch)

    def draw_boxes(self, width, height):
        handles = []
        for index, (x1, y1, x2, y2) in enumerate(self.boxes):
            left, right = (x1*self.scale+self.offset_x, x2*self.scale+self.offset_x)
            top, bottom = (y1*self.scale+self.offset_y, y2*self.scale+self.offset_y)
            if right <= 0 or bottom <= 0 or left >= width or top >= height:
                continue
            color = '#00b050' if index in self.selected else '#ff8c00'
            self.canvas.create_rectangle(left, top, right, bottom, outline=color, width=3)
            if 0 <= right <= width and 0 <= top < height:
                # Put the handle beside the corner so it covers less of the text.
                x = max(9, min(width-9, right+9))
                y = max(9, min(height-9, top))
                handles.append((index, x, y))
        for index, x, y in handles:
            tag = f'remove-box:{index}'
            self.canvas.create_rectangle(x-8, y-8, x+8, y+8, fill='#202020', outline='white', tags=(tag,))
            self.canvas.create_line(x-3, y-3, x+3, y+3, fill='white', width=2, tags=(tag,))
            self.canvas.create_line(x-3, y+3, x+3, y-3, fill='white', width=2, tags=(tag,))

    def edit_boxes(self):
        if self.image is None or not self.confirmed:
            return
        self.confirmed = False
        self.render()
        self.status.config(text='Click an X to remove a box. Confirm selection when ready.')

    def remove_box(self, index):
        self.boxes.pop(index)
        remaining = {i if i < index else i-1 for i in self.selected if i != index}
        self.selected.clear()
        self.selected.update(remaining)
        self.confirmed = False
        self.render()
        self.status.config(text=f'{self.path.name}: box removed. {len(self.selected)} selected of {len(self.boxes)}.')

    def clamp_offsets(self):
        w, h = self.image.size
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.offset_x = min(0.0, max(min(0.0, cw-w*self.scale), self.offset_x))
        self.offset_y = min(0.0, max(min(0.0, ch-h*self.scale), self.offset_y))

    def mouse_zoom(self, e):
        if self.image is None or self.pan_start is not None: return
        direction = 1 if getattr(e, 'num', None) == 4 or getattr(e, 'delta', 0) > 0 else -1
        zoom = max(1.0, min(6.0, self.zoom * (1.2 if direction > 0 else 1/1.2)))
        image_x, image_y = (e.x-self.offset_x)/self.scale, (e.y-self.offset_y)/self.scale
        self.zoom = zoom
        w, h = self.image.size
        self.scale = min(self.canvas.winfo_width()/w, self.canvas.winfo_height()/h, 1.0) * zoom
        self.offset_x, self.offset_y = e.x-image_x*self.scale, e.y-image_y*self.scale
        self.clamp_offsets()
        self.render()
        return 'break'

    def pan_down(self, e):
        if self.image is None or self.zoom <= 1.0:
            return
        self.start = None
        self.canvas.delete('drag')
        self.pan_start = (e.x, e.y)
        self.canvas.configure(cursor='fleur')
        return 'break'

    def pan_move(self, e):
        if self.image is None or self.pan_start is None:
            return
        self.offset_x += e.x-self.pan_start[0]
        self.offset_y += e.y-self.pan_start[1]
        self.pan_start = (e.x, e.y)
        self.clamp_offsets()
        self.render()
        return 'break'

    def pan_up(self, e):
        if self.pan_start is not None:
            self.pan_start = None
            self.canvas.configure(cursor='crosshair')
            return 'break'

    def down(self, e):
        if self.image is None or self.pan_start is not None:
            return
        if not self.confirmed:
            for item in reversed(self.canvas.find_overlapping(e.x, e.y, e.x, e.y)):
                for tag in self.canvas.gettags(item):
                    if tag.startswith('remove-box:'):
                        self.start = None
                        self.remove_box(int(tag.split(':', 1)[1]))
                        return 'break'
        self.start = (e.x, e.y)

    def move(self, e):
        if self.start is None: return
        self.canvas.delete('drag')
        self.canvas.create_rectangle(*self.start, e.x, e.y, outline='red', width=2, tags='drag')
    def up(self, e):
        if self.start is None or self.image is None: return
        sx, sy = self.start; self.start = None
        if abs(e.x - sx) <= 4 and abs(e.y - sy) <= 4:
            x, y = int((sx-self.offset_x) / self.scale), int((sy-self.offset_y) / self.scale)
            for i in range(len(self.boxes) - 1, -1, -1):
                x1, y1, x2, y2 = self.boxes[i]
                if x1 <= x < x2 and y1 <= y < y2:
                    if i in self.selected: self.selected.remove(i)
                    else: self.selected.add(i)
                    self.confirmed = False
                    break
            self.status.config(text=f'{self.path.name}: {len(self.selected)} selected of {len(self.boxes)}. Confirm to apply.')
            self.render()
            return
        w, h = self.image.size
        x1, x2 = sorted((max(0, min(w, int((sx-self.offset_x)/self.scale))), max(0, min(w, int((e.x-self.offset_x)/self.scale)+1))))
        y1, y2 = sorted((max(0, min(h, int((sy-self.offset_y)/self.scale))), max(0, min(h, int((e.y-self.offset_y)/self.scale)+1))))
        if x2 > x1 and y2 > y1:
            self.boxes.append((x1,y1,x2,y2)); self.selected.add(len(self.boxes)-1); self.confirmed = False
        self.status.config(text=f'{self.path.name}: {len(self.selected)} selected of {len(self.boxes)}. Confirm to apply.')
        self.render()
    def find(self, *, area=None):
        if self.image is None: return
        executable = find_tesseract()
        if not executable:
            messagebox.showinfo('Local OCR needed', 'Install Tesseract OCR locally and add it to PATH, then try again. No images are uploaded. See README.md.')
            return
        try:
            confidence = self.confidence.get()
            if not 0 <= confidence <= 100: raise ValueError('OCR confidence must be between 0 and 100.')
            custom = self.custom_pattern.get().strip()
            if custom: re.compile(custom)
            categories = {name for name, variable in self.category_vars.items() if variable.get()}
            settings = self.all_text.get(), categories, confidence, custom
            incomplete = []
            found = recognize_regions(self.image, executable, settings, self.enhanced_ocr.get(),
                                      color_assisted=self.color_ocr.get(), incomplete=incomplete, area=area)
            added = [box for box in found if box not in self.boxes]
            first_new = len(self.boxes)
            self.boxes.extend(added)
            self.selected.update(range(first_new, len(self.boxes)))
            if added: self.confirmed = False
            self.render()
            detail = f' Incomplete OCR passes: {", ".join(incomplete)}.' if incomplete else ''
            self.status.config(text=f'{len(added)} selected suggestions added.{detail} Review the entire image.')
            messagebox.showinfo('Review required', f'Added {len(added)} selected boxes.{detail} Review the image before confirming.')
        except (ValueError, re.error, tk.TclError) as e:
            messagebox.showerror('Invalid detection settings', str(e))
        except (OSError, subprocess.SubprocessError) as e:
            messagebox.showerror('Local OCR failed', f'Text recognition failed: {e}')

    def selected_boxes(self):
        return [box for i, box in enumerate(self.boxes) if i in self.selected]

    def confirm_selection(self):
        if self.image is None: return
        self.confirmed = True
        self.render()
        self.status.config(text=f'{len(self.selected)} areas applied in preview. Save, or click to change your selection.')

    def undo(self):
        if self.boxes:
            self.selected.discard(len(self.boxes)-1)
            self.boxes.pop(); self.confirmed = False; self.render()
        if self.image: self.status.config(text=f'{len(self.selected)} selected of {len(self.boxes)}. Confirm to apply.')
    def save(self):
        if self.image is None: return
        if not self.confirmed:
            messagebox.showinfo('Confirm selection', 'Select the areas to redact and click Confirm selection before saving.')
            return
        if not self.selected and not messagebox.askyesno('No redactions', 'No areas are selected. Save an unredacted copy?'): return
        output = filedialog.asksaveasfilename(defaultextension='.png', initialfile=self.path.stem+'_redacted.png', filetypes=[('PNG image', '*.png')])
        if not output: return
        if Path(output).resolve() == self.path.resolve():
            messagebox.showerror('Choose a different file', 'The original image cannot be overwritten.'); return
        try:
            out = apply_redactions(self.image, self.selected_boxes(), self.method.get())
            out.info.clear()  # Do not copy camera metadata into the output.
            out.save(output, format='PNG')
            log = {'source_filename': self.path.name, 'output_filename': Path(output).name, 'image_dimensions': list(self.image.size), 'redaction_rectangles_xyxy': self.selected_boxes(), 'created_local_time': datetime.now().isoformat(timespec='seconds'), 'method': self.method.get(), 'note': 'Automated suggestions can miss identifiers; manual review required. Pixelation may not fully conceal sensitive content.'}
            Path(output).with_suffix('.redactions.json').write_text(json.dumps(log, indent=2), encoding='utf-8')
            messagebox.showinfo('Saved', 'Saved the redacted PNG and coordinate log. Review before sharing; pixelated text can sometimes be recovered.')
        except Exception as e: messagebox.showerror('Save failed', str(e))


IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}


@dataclass
class FolderImage:
    path: Path
    boxes: list = field(default_factory=list)
    selected: set = field(default_factory=set)
    scanned: bool = False
    incomplete_ocr: tuple = ()
    reviewed: bool = False
    saved: bool = False
    error: str = ''
    stamp: tuple | None = None
    method: str = 'Pixelate'

    @property
    def status(self):
        if self.error:
            return self.error
        if self.saved:
            return 'Saved'
        if self.reviewed:
            return 'Reviewed'
        if self.incomplete_ocr:
            return 'Partial scan · review needed'
        if self.scanned:
            return 'Scanned · review needed'
        if self.boxes:
            return 'Boxes added · review needed'
        return 'Not checked'

    def add_shared_boxes(self, boxes):
        indices = {box: index for index, box in enumerate(self.boxes)}
        changed = False
        for box in boxes:
            index = indices.get(box)
            if index is None:
                index = len(self.boxes)
                self.boxes.append(box)
                indices[box] = index
            if index not in self.selected:
                self.selected.add(index)
                changed = True
        if changed:
            self.reviewed = self.saved = False
        return changed

    def add_suggestions(self, found, incomplete=()):
        known = set(self.boxes)
        for box in found:
            if box not in known:
                self.selected.add(len(self.boxes))
                self.boxes.append(box)
                known.add(box)
        self.scanned = True
        self.incomplete_ocr = tuple(incomplete)
        self.reviewed = self.saved = False
        self.error = ''


def file_stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def read_folder_image(path, expected=None):
    stamp = file_stamp(path)
    if expected is not None and stamp != expected:
        raise ValueError('Source changed. Reopen the folder and review the new image.')
    with Image.open(path) as source:
        image = source.convert('RGB')
    if file_stamp(path) != stamp:
        raise ValueError('Source changed while reading.')
    return image, stamp


def output_path(directory, template, source, index):
    name = template.format(stem=source.stem, ext=source.suffix[1:].lower(), index=index)
    if not name.lower().endswith('.png'):
        name += '.png'
    if (not name[:-4].strip(' .') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.startswith(' ') or re.fullmatch(r'(?i)(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])', name.split('.')[0].rstrip(' '))):
        raise ValueError('Enter a valid filename template without folders.')
    return directory / name


def write_folder_copy(entry, target, include_log):
    image, _ = read_folder_image(entry.path, entry.stamp)
    boxes = [box for index, box in enumerate(entry.boxes) if index in entry.selected]
    copy = apply_redactions(image, boxes, entry.method)
    copy.info.clear()
    log_path = target.with_suffix('.redactions.json')
    log = {
        'source_filename': entry.path.name,
        'output_filename': target.name,
        'image_dimensions': list(image.size),
        'redaction_rectangles_xyxy': boxes,
        'method': entry.method,
        'created_local_time': datetime.now().isoformat(timespec='seconds'),
    }
    created = []
    try:
        with target.open('xb') as stream:
            created.append(target)
            copy.save(stream, format='PNG')
        if include_log:
            with log_path.open('x', encoding='utf-8') as stream:
                created.append(log_path)
                json.dump(log, stream, indent=2)
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


class ScanCancelled(Exception):
    """The user stopped a folder scan before this image finished."""


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


def recognize_regions(image, executable, settings, enhanced=False, cancel=None, *,
                      color_assisted=False, incomplete=None, area=None, area_layout=None):
    if area is not None:
        left, top, right, bottom = area
        crop = image.crop(area)
        factor = min(4, 2400 / max(crop.size))
        enlarged = crop.resize((max(1, round(crop.width*factor)), max(1, round(crop.height*factor))), Image.Resampling.LANCZOS)
        boxes = recognize_regions(enlarged, executable, settings, enhanced, cancel,
                                  color_assisted=color_assisted, incomplete=incomplete,
                                  area_layout='7' if crop.width >= 6*crop.height else '6')
        sx, sy = crop.width/enlarged.width, crop.height/enlarged.height
        return [(left+math.floor(x1*sx), top+math.floor(y1*sy),
                 min(right, left+math.ceil(x2*sx)), min(bottom, top+math.ceil(y2*sy)))
                for x1, y1, x2, y2 in boxes]
    # Tesseract processes run serially. Limiting OpenMP threads avoids
    # oversubscription on machines where parallel OCR runs slower.
    environment = {**os.environ, 'OMP_THREAD_LIMIT': '1'}

    def check_cancel():
        if cancel is not None and cancel.is_set():
            raise ScanCancelled

    def run(source, extra_options=(), timeout=120):
        check_cancel()
        data = io.BytesIO()
        source.save(data, format='PNG')
        command = [executable, 'stdin', 'stdout', *extra_options, 'tsv']
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        if cancel is None:
            result = subprocess.run(command, input=data.getvalue(), capture_output=True,
                                    timeout=timeout, check=True, creationflags=flags, env=environment)
            stdout = result.stdout
        else:
            stdout = cancellable_ocr(command, data.getvalue(), flags, cancel, timeout=timeout, env=environment)
        return detect_regions(stdout.decode('utf-8', errors='replace'), source.size, *settings)

    try:
        boxes = run(image, ('--psm', area_layout) if area_layout else ())
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('Standard OCR timed out. Try a smaller photo or mark redactions manually.') from error

    if not (enhanced or color_assisted):
        return boxes

    check_cancel()
    working = image.copy()
    working.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    scale_x = image.width / working.width
    scale_y = image.height / working.height
    enhancement_deadline = monotonic() + 35

    def note_incomplete(reason):
        if incomplete is not None:
            incomplete.append(reason)

    def add_pass(source, name):
        check_cancel()
        remaining = enhancement_deadline - monotonic()
        if remaining <= 0:
            note_incomplete('remaining enhancement passes skipped')
            return False
        try:
            found = run(source, ('--psm', area_layout or '11'), timeout=min(15, remaining))
        except subprocess.TimeoutExpired:
            note_incomplete(f'{name} timed out')
            return True
        except subprocess.CalledProcessError:
            note_incomplete(f'{name} failed')
            return True
        for x1, y1, x2, y2 in found:
            candidate = (math.floor(x1*scale_x), math.floor(y1*scale_y),
                         min(image.width, math.ceil(x2*scale_x)), min(image.height, math.ceil(y2*scale_y)))
            if not any(same_region(candidate, existing) for existing in boxes):
                boxes.append(candidate)
        return True

    if enhanced:
        contrast = ImageOps.autocontrast(ImageOps.grayscale(working).filter(ImageFilter.MedianFilter(3)), cutoff=1)
        if not add_pass(contrast, 'enhanced OCR'):
            return boxes
    if color_assisted:
        check_cancel()
        from ocr_preprocess import color_ocr_variants
        for index, variant in enumerate(color_ocr_variants(working), 1):
            if not add_pass(variant, f'color pass {index}'):
                break
    return boxes


def same_region(first, second):
    overlap = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1]))
    return all(overlap >= 0.75 * (box[2] - box[0]) * (box[3] - box[1]) for box in (first, second))


def scan_folder_image(path, expected, executable, settings, enhanced=False, cancel=None, *, color_assisted=False, area=None):
    image, stamp = read_folder_image(path, expected)
    incomplete = []
    boxes = recognize_regions(image, executable, settings, enhanced, cancel,
                              color_assisted=color_assisted, incomplete=incomplete, area=area)
    return stamp, boxes, incomplete


class FolderRedactor(Redactor):
    def __init__(self, root):
        super().__init__(root)
        self.entries = []
        self.active = None
        self.anchor_capture = False
        self.scan_area_capture = False
        self.busy = False
        self.scan_cancel = None
        self.folder = None
        self.output_directory = None
        self.output_directory_override = None
        self.filename_template = '{stem}_redacted'
        self.include_log = True
        self.load_preferences()
        tk.Button(self.toolbar, text='Open folder', command=self.open_folder).pack(side='left', padx=4)
        ttk.Button(self.toolbar, text='Scan area', command=self.begin_scan_area).pack(side='left', padx=4)
        self.sidebar = ttk.Frame(self.workspace, padding=6)
        actions = ttk.Frame(self.sidebar)
        actions.pack(fill='x', pady=(0, 5))
        self.scan_button = ttk.Button(actions, text='Scan all', command=lambda: self.start_scan(self.entries, follow=True))
        self.scan_button.pack(side='left')
        self.rescan_button = ttk.Button(self.sidebar, text='Rescan all (keep boxes)', command=self.rescan_all)
        self.rescan_button.pack(fill='x', pady=(0, 5))
        self.copy_boxes_button = ttk.Button(
            self.sidebar, text='Copy selected boxes to folder', command=self.copy_boxes_to_folder)
        self.copy_boxes_button.pack(fill='x', pady=(0, 5))
        self.match_boxes_button = ttk.Button(
            self.sidebar, text='Match boxes by visual anchor', command=self.begin_anchor_capture)
        self.match_boxes_button.pack(fill='x', pady=(0, 5))
        self.canvas.bind('<Escape>', self.cancel_anchor_capture)
        ttk.Button(self.sidebar, text='Confirm all', command=self.confirm_all).pack(fill='x', pady=(0, 5))
        ttk.Button(self.sidebar, text='Save reviewed images', command=self.save_reviewed).pack(fill='x', pady=(0, 5))
        self.progress = ttk.Label(self.sidebar, anchor='w', text='Ready')
        self.progress.pack(fill='x')
        self.progress_bar = ttk.Progressbar(self.sidebar, mode='determinate')
        self.progress_bar.pack(fill='x', pady=(3, 2))
        self.cancel_scan_button = ttk.Button(self.sidebar, text='Cancel scan', command=self.cancel_scan)
        self.cancel_scan_button.pack(fill='x', pady=(0, 3))
        self.cancel_scan_button.state(['disabled'])
        self.progress_detail = ttk.Label(self.sidebar, anchor='w', wraplength=300)
        self.progress_detail.pack(fill='x')
        self.folder_counts = ttk.Label(self.sidebar, anchor='w', wraplength=300)
        self.folder_counts.pack(fill='x', pady=(3, 5))
        self.files = ttk.Treeview(self.sidebar, columns=('status',), selectmode='browse')
        self.files.heading('#0', text='Image')
        self.files.heading('status', text='Status')
        self.files.column('#0', width=170, minwidth=100)
        self.files.column('status', width=150, minwidth=100)
        scroll = ttk.Scrollbar(self.sidebar, orient='vertical', command=self.files.yview)
        self.files.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.files.pack(side='left', fill='both', expand=True)
        self.files.bind('<<TreeviewSelect>>', self.select_image)

    def can_leave(self):
        self.store_active()
        if not self.entries:
            return True
        pending = any(not entry.saved and (entry.boxes or entry.reviewed) for entry in self.entries)
        return not pending or messagebox.askyesno(
            'Leave folder?', 'Some images have unsaved review work. Leave this folder?')

    def open(self):
        if self.busy or not self.can_leave():
            return
        self.cancel_anchor_capture()
        previous = self.image
        if self.entries:
            self.image = None
            boxes, self.boxes = self.boxes, []
            active, self.active = self.active, None
            super().open()
            if self.image is None:
                self.image, self.boxes, self.active = previous, boxes, active
                return
            self.entries = []
            self.active = None
            self.sidebar.pack_forget()
        else:
            super().open()

    def open_folder(self):
        if self.busy:
            return
        chosen = filedialog.askdirectory(title='Open image folder')
        if not chosen or not self.can_leave():
            return
        folder = Path(chosen)
        try:
            paths = sorted(
                (path for path in folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file()),
                key=lambda path: (path.name.casefold(), path.name),
            )
        except OSError as error:
            messagebox.showerror('Cannot open folder', str(error))
            return
        if not paths:
            messagebox.showinfo('No images', 'Choose a folder containing PNG, JPEG, BMP or TIFF images.')
            return
        if not self.entries and self.boxes and not messagebox.askyesno('Open folder?', 'Discard the current image markings?'):
            return
        self.cancel_anchor_capture()
        self.folder = folder
        self.progress.config(text='Ready')
        self.progress_bar.configure(value=0, maximum=1)
        self.progress_detail.config(text='')
        self.output_directory = self.output_directory_override or folder / 'redacted'
        self.entries = [FolderImage(path, method=self.default_method) for path in paths]
        self.active = None
        self.sidebar.pack(side='left', fill='y', before=self.canvas)
        self.files.delete(*self.files.get_children())
        for index, entry in enumerate(self.entries):
            self.files.insert('', 'end', iid=str(index), text=entry.path.name, values=(entry.status,))
        self.files.selection_set('0')
        self.select_image()
        self.refresh_files()

    def store_active(self):
        if self.active is None or self.image is None:
            return
        entry = self.entries[self.active]
        if entry.reviewed and not self.confirmed:
            entry.saved = False
        entry.reviewed = self.confirmed
        entry.boxes = self.boxes
        entry.selected = self.selected

    def select_image(self, event=None):
        selection = self.files.selection()
        if not selection or not self.entries:
            return
        index = int(selection[0])
        if self.active == index:
            return
        self.cancel_anchor_capture()
        self.store_active()
        self.active = index
        entry = self.entries[index]
        self.path = entry.path
        self.boxes, self.selected = entry.boxes, entry.selected
        self.confirmed = entry.reviewed
        self.zoom = 1.0
        self.offset_x = self.offset_y = 0.0
        self.start = self.pan_start = None
        self.canvas.configure(cursor='crosshair')
        try:
            self.image, entry.stamp = read_folder_image(entry.path, entry.stamp)
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            self.image = None
            self.canvas.delete('all')
            entry.error = 'Open failed'
            self.status.config(text=f'{entry.path.name} · {error}')
        else:
            self.render()
            self.status.config(text=f'{entry.path.name} · {entry.status} · {len(entry.selected)} boxes selected')
        self.refresh_files()

    def refresh_files(self):
        for index, entry in enumerate(self.entries):
            self.files.set(str(index), 'status', entry.status)
        self.update_folder_counts()

    def update_folder_counts(self):
        scanned = sum(entry.scanned for entry in self.entries)
        reviewed = sum(entry.reviewed for entry in self.entries)
        saved = sum(entry.saved for entry in self.entries)
        self.folder_counts.config(text=f'{len(self.entries)} images · {scanned} scanned · {reviewed} reviewed · {saved} saved')

    def render(self):
        super().render()
        if self.active is not None and self.image is not None:
            self.store_active()
            self.files.set(str(self.active), 'status', self.entries[self.active].status)
            self.update_folder_counts()

    def method_changed(self, event=None):
        if not self.entries:
            super().method_changed(event)
            return
        method = self.method.get()
        for entry in self.entries:
            if entry.method != method:
                entry.method = method
                entry.reviewed = entry.saved = False
        self.confirmed = False
        self.render()
        self.refresh_files()
        self.status.config(text=f'{method} will be used across the folder. Confirm the updated redactions before saving.')

    def find(self):
        if self.active is None:
            super().find()
        else:
            self.start_scan([self.entries[self.active]], rescan=True)

    def begin_scan_area(self):
        if self.busy or self.image is None:
            return
        self.cancel_anchor_capture()
        self.scan_area_capture = True
        self.canvas.focus_set()
        self.status.config(text='Drag around the text to scan. For small labels, draw a tight box around a single row. Esc cancels.')

    def begin_anchor_capture(self):
        if self.busy or self.active is None or self.image is None:
            return
        if not self.selected or len(self.entries) < 2:
            messagebox.showinfo('Match by visual anchor', 'Select redaction boxes on one image in a folder with at least two images.')
            return
        self.cancel_anchor_capture()
        self.edit_boxes()
        self.anchor_capture = True
        self.canvas.focus_set()
        self.status.config(text='Drag around a distinctive logo or label near the boxes. Esc cancels.')

    def cancel_anchor_capture(self, event=None):
        if self.anchor_capture or self.scan_area_capture:
            self.anchor_capture = self.scan_area_capture = False
            self.start = None
            self.canvas.delete('drag')
            if event is not None:
                self.status.config(text='Area selection canceled.')

    def down(self, event):
        if (self.anchor_capture or self.scan_area_capture) and self.pan_start is None:
            self.start = (event.x, event.y)
            return 'break'
        return super().down(event)

    def up(self, event):
        if not (self.anchor_capture or self.scan_area_capture):
            return super().up(event)
        if self.start is None:
            return
        sx, sy = self.start
        scan_area = self.scan_area_capture
        self.cancel_anchor_capture()
        if self.busy or self.image is None:
            return
        width, height = self.image.size
        left, right = sorted((sx, event.x))
        top, bottom = sorted((sy, event.y))
        anchor = (
            max(0, int((left-self.offset_x)/self.scale)),
            max(0, int((top-self.offset_y)/self.scale)),
            min(width, int((right-self.offset_x)/self.scale)),
            min(height, int((bottom-self.offset_y)/self.scale)),
        )
        if scan_area:
            if anchor[2]-anchor[0] < 4 or anchor[3]-anchor[1] < 4:
                self.status.config(text='Area too small. Click Scan area and draw around the text again.')
            elif self.active is None:
                super().find(area=anchor)
            else:
                self.start_scan([self.entries[self.active]], rescan=True, area=anchor)
        else:
            self.match_boxes_to_folder(anchor)
        return 'break'

    def match_boxes_to_folder(self, anchor):
        try:
            from visual_anchor import locate_anchor, prepare_anchor, relocate_boxes
        except ImportError:
            messagebox.showerror('Visual matching unavailable', 'Install the project dependencies from requirements.txt and restart.')
            return
        boxes = self.selected_boxes()
        if not boxes:
            self.status.config(text='Select boxes to match across the folder.')
            return
        left, top, right, bottom = anchor
        if right-left < 20 or bottom-top < 20:
            self.status.config(text='Anchor too small. Click Match boxes by visual anchor and drag around a larger area.')
            return
        try:
            patch = prepare_anchor(self.image, anchor)
        except ValueError as error:
            self.status.config(text=str(error))
            return

        targets = [entry for index, entry in enumerate(self.entries) if index != self.active]
        matched = skipped = 0

        def operation(job):
            path, expected = job
            image, stamp = read_folder_image(path, expected)
            match = locate_anchor(image, patch)
            placed = relocate_boxes(boxes, anchor, match, image.size) if match else []
            return stamp, placed

        def accept(index, result, error):
            nonlocal matched, skipped
            entry = targets[index]
            if error:
                return
            stamp, placed = result
            if not placed or (entry.stamp is not None and entry.stamp != stamp):
                skipped += 1
                return
            entry.stamp = stamp
            matched += 1
            if entry.add_shared_boxes(placed) and self.active is not None and self.entries[self.active] is entry:
                self.confirmed = False
                self.render()

        def finish():
            return f'{matched} matched · {skipped} skipped (no reliable placement)'

        self.run_jobs('Matching visual anchor', [(entry.path, entry.stamp) for entry in targets],
                      operation, accept, finish)

    def copy_boxes_to_folder(self):
        if self.busy or self.active is None or self.image is None:
            return
        boxes = self.selected_boxes()
        if not boxes:
            messagebox.showinfo('Copy selected boxes', 'Select or draw the boxes you want to copy first.')
            return
        targets = [entry for index, entry in enumerate(self.entries) if index != self.active]
        if not targets:
            messagebox.showinfo('Copy selected boxes', 'Open a folder with at least two images.')
            return
        if not messagebox.askyesno(
                'Copy selected boxes?',
                f'Copy {len(boxes)} selected box(es) to the same positions on other images of the same size? '
                'Check that the content lines up before confirming and saving.'):
            return
        size = self.image.size
        applied = skipped = unchanged = 0

        def operation(job):
            path, expected = job
            stamp = file_stamp(path)
            if expected is not None and stamp != expected:
                raise ValueError(f'{path.name} changed. Reopen the folder before copying boxes.')
            with Image.open(path) as image:
                matches = image.size == size
            if file_stamp(path) != stamp:
                raise ValueError(f'{path.name} changed while reading.')
            return stamp, matches

        def accept(index, result, error):
            nonlocal applied, skipped, unchanged
            if error:
                return
            entry = targets[index]
            stamp, matches = result
            if not matches or (entry.stamp is not None and entry.stamp != stamp):
                skipped += 1
                return
            entry.stamp = stamp
            if not entry.add_shared_boxes(boxes):
                unchanged += 1
                return
            applied += 1
            if self.active is not None and self.entries[self.active] is entry and self.image is not None:
                self.confirmed = False
                self.render()

        def finish():
            return f'{applied} updated · {skipped} skipped (size or source changed) · {unchanged} already selected'

        self.run_jobs('Copying boxes', [(entry.path, entry.stamp) for entry in targets],
                      operation, accept, finish)

    def rescan_all(self):
        if not self.busy and self.entries and messagebox.askyesno(
                'Rescan all images?', 'Keep existing boxes and add new suggestions. All rescanned images will need review again.'):
            self.start_scan(self.entries, rescan=True, follow=True)

    def start_scan(self, entries, rescan=False, *, follow=False, area=None):
        if self.busy:
            return
        self.store_active()
        pending = [entry for entry in entries if rescan or not (entry.scanned or entry.reviewed)]
        if not pending:
            messagebox.showinfo('Folder scan', 'Every image has been scanned or manually reviewed. Use Find likely identifiers to rescan an image.')
            return
        executable = find_tesseract()
        if not executable:
            messagebox.showerror('Local OCR needed', 'Restore Tesseract in tools/tesseract or add it to PATH.')
            return
        try:
            confidence = self.confidence.get()
            if not 0 <= confidence <= 100:
                raise ValueError('OCR confidence must be between 0 and 100.')
            custom = self.custom_pattern.get().strip()
            re.compile(custom)
        except (ValueError, re.error, tk.TclError) as error:
            messagebox.showerror('Invalid detection settings', str(error))
            return
        categories = {name for name, variable in self.category_vars.items() if variable.get()}
        settings = self.all_text.get(), categories, confidence, custom
        enhanced = self.enhanced_ocr.get()
        color_assisted = self.color_ocr.get()
        jobs = [(entry.path, entry.stamp) for entry in pending]
        cancel = Event()
        rows = {entry.path: str(index) for index, entry in enumerate(self.entries)}

        def show_image(index):
            row = rows[pending[index].path]
            if self.files.selection() != (row,):
                self.files.selection_set(row)
            self.files.see(row)
            self.select_image()

        def operation(job):
            path, stamp = job
            return scan_folder_image(path, stamp, executable, settings, enhanced, cancel,
                                     color_assisted=color_assisted, area=area)

        area_completed = False

        def accept(index, result, error):
            nonlocal area_completed
            entry = pending[index]
            if error:
                if area is None:
                    entry.error = 'Scan failed'
                self.status.config(text=f'{entry.path.name} · {error}')
                return
            stamp, found, incomplete = result
            if entry.stamp is not None and entry.stamp != stamp:
                entry.error = 'Source changed'
                return
            area_completed = area is not None
            if follow:
                show_image(index)
            entry.stamp = stamp
            if area is None:
                entry.add_suggestions(found, incomplete)
                changed = True
            else:
                changed = entry.add_shared_boxes([box for box in found if box not in entry.boxes])
            if self.active is not None and entry is self.entries[self.active] and self.image is not None:
                if changed:
                    self.confirmed = False
                    self.render()
                count = len(set(found))
                detail = f' Partial scan: {", ".join(incomplete)}.' if incomplete else ''
                self.status.config(text=f'{entry.path.name} · {count} OCR suggestions.{detail} Review before confirming.')

        def finish():
            if area is not None:
                return 'Area scan finished · review suggested boxes' if processed and area_completed else 'No area results'
            complete = sum(entry.scanned and not entry.incomplete_ocr and not entry.error for entry in processed)
            partial = sum(bool(entry.incomplete_ocr) and not entry.error for entry in processed)
            return f'{complete} succeeded' + (f' · {partial} partial' if partial else '')

        processed = []
        def track_result(index, result, error):
            accept(index, result, error)
            processed.append(pending[index])

        self.run_jobs('Scanning area' if area is not None else 'Scanning', jobs, operation, track_result, finish, cancel=cancel,
                      show_image=show_image if follow else None)

    def cancel_scan(self):
        if self.scan_cancel is not None:
            self.scan_cancel.set()
            self.cancel_scan_button.state(['disabled'])
            self.progress.config(text='Canceling scan…')

    def run_jobs(self, label, jobs, operation, accept, finish=None, *, cancel=None, show_image=None):
        if not jobs or self.busy:
            return
        self.cancel_anchor_capture()
        self.busy = True
        self.scan_cancel = cancel
        if cancel is not None:
            self.cancel_scan_button.state(['!disabled'])
        self.match_boxes_button.state(['disabled'])
        self.scan_button.state(['disabled'])
        self.rescan_button.state(['disabled'])
        self.copy_boxes_button.state(['disabled'])
        results = Queue()
        failures = []
        completed = 0
        total = len(jobs)
        advance = Event() if show_image is not None else None
        self.progress_bar.configure(value=0, maximum=total)

        def show_progress():
            percent = completed * 100 // total
            self.progress_bar.configure(value=completed)
            self.progress.config(text=f'{label} · {completed}/{total} processed ({percent}%)')
            target = jobs[completed][0]
            name = target.path.name if isinstance(target, FolderImage) else target.name
            self.progress_detail.config(text=f'Current image: {name}')

        def show_next_image():
            if cancel is not None and cancel.is_set():
                return
            show_image(completed)
            show_progress()
            advance.set()

        def worker():
            try:
                for index, job in enumerate(jobs):
                    if advance is not None:
                        while not advance.wait(0.1):
                            if cancel is not None and cancel.is_set():
                                return
                        advance.clear()
                    if cancel is not None and cancel.is_set():
                        break
                    try:
                        results.put((index, operation(job), None))
                    except ScanCancelled:
                        break
                    except Exception as error:
                        results.put((index, None, str(error)))
            finally:
                results.put(None)

        def poll():
            nonlocal completed
            previous = completed
            finished = False
            while True:
                try:
                    item = results.get_nowait()
                except Empty:
                    break
                if item is None:
                    finished = True
                    break
                index, result, error = item
                accept(index, result, error)
                if error is not None:
                    failures.append(error or 'Unknown error')
                completed += 1
            if not finished:
                if completed != previous:
                    self.refresh_files()
                    if completed < total and (cancel is None or not cancel.is_set()):
                        if show_image is None:
                            show_progress()
                        else:
                            self.progress_bar.configure(value=completed)
                            self.progress.config(text=f'{label} · {completed}/{total} processed ({completed*100//total}%)')
                            # Leave the detected boxes visible briefly before starting the next photo.
                            self.root.after(250, show_next_image)
                self.root.after(100, poll)
            else:
                self.busy = False
                self.scan_cancel = None
                self.cancel_scan_button.state(['disabled'])
                self.match_boxes_button.state(['!disabled'])
                self.scan_button.state(['!disabled'])
                self.rescan_button.state(['!disabled'])
                self.copy_boxes_button.state(['!disabled'])
                self.refresh_files()
                self.progress_bar.configure(value=completed)
                canceled = cancel is not None and cancel.is_set() and completed < total
                outcome = 'Scan canceled' if canceled else f'{label} finished'
                self.progress.config(text=f'{outcome} · {completed}/{total} processed')
                detail = finish() if finish is not None else f'{completed-len(failures)} succeeded'
                if canceled:
                    detail += f' · {total-completed} remaining'
                if failures:
                    detail += f' · {len(failures)} failed'
                self.progress_detail.config(text=detail)
                if failures:
                    messagebox.showwarning(label, f'{len(failures)} of {len(jobs)} failed. First error:\n{failures[0]}')

        if show_image is None:
            show_progress()
        else:
            show_next_image()
        Thread(target=worker, daemon=True).start()
        self.root.after(100, poll)

    def build_output_settings(self, notebook):
        form = ttk.Frame(notebook, padding=12)
        notebook.add(form, text='Folder output')
        directory = tk.StringVar(form, value=str(self.output_directory_override or ''))
        template = tk.StringVar(form, value=self.filename_template)
        include_log = tk.BooleanVar(form, value=self.include_log)

        def browse():
            chosen = filedialog.askdirectory(parent=form.winfo_toplevel(), title='Choose output folder')
            if chosen:
                directory.set(chosen)

        def prepare():
            text = directory.get().strip()
            chosen = Path(text) if text else None
            if chosen is not None and not chosen.is_absolute():
                raise ValueError('Choose an absolute output folder.')
            name = template.get().strip()
            if not name:
                raise ValueError('Enter a filename template.')
            source = self.entries[0].path if self.entries else Path('example.png')
            output_path(chosen or Path('.'), name, source, 1)

            return {
                'output_directory': str(chosen) if chosen is not None else '',
                'filename_template': name,
                'include_log': include_log.get(),
            }

        ttk.Label(form, text='Output folder').grid(row=0, column=0, sticky='w')
        ttk.Entry(form, textvariable=directory, width=36).grid(row=1, column=0, sticky='ew')
        ttk.Button(form, text='Browse…', command=browse).grid(row=1, column=1, padx=(6, 0))
        ttk.Label(form, text='Leave blank to save in the source folder’s redacted subfolder.',
                  wraplength=350).grid(row=2, column=0, columnspan=2, sticky='w', pady=(4, 10))
        ttk.Label(form, text='Filename template').grid(row=3, column=0, sticky='w')
        ttk.Entry(form, textvariable=template).grid(row=4, column=0, columnspan=2, sticky='ew')
        ttk.Label(form, text='{stem} original name · {ext} original extension · {index} folder position',
                  wraplength=350).grid(row=5, column=0, columnspan=2, sticky='w', pady=(4, 10))
        ttk.Checkbutton(form, text='Save a coordinate log with each PNG', variable=include_log).grid(
            row=6, column=0, columnspan=2, sticky='w')
        form.columnconfigure(0, weight=1)
        return prepare

    def restore_output_preferences(self, saved):
        directory = saved.get('output_directory')
        if isinstance(directory, str):
            path = Path(directory) if directory else None
            if path is None or path.is_absolute():
                self.output_directory_override = path
                self.output_directory = path or (self.folder / 'redacted' if self.folder else None)
        template = saved.get('filename_template')
        if isinstance(template, str) and template.strip():
            try:
                output_path(Path('.'), template, Path('example.png'), 1)
            except (ValueError, KeyError, IndexError, AttributeError):
                pass
            else:
                self.filename_template = template
        if isinstance(saved.get('include_log'), bool):
            self.include_log = saved['include_log']

    def save(self):
        if self.active is None:
            super().save()
        elif not self.busy:
            self.store_active()
            entry = self.entries[self.active]
            if self.image is None or not entry.reviewed:
                messagebox.showinfo('Review image', 'Review this image and confirm the selection before saving.')
                return
            self.export_entries([(self.active, entry)], individual=True)

    def confirm_all(self):
        if self.busy or not self.entries:
            return
        self.store_active()
        pending = [entry for entry in self.entries if entry.selected and not entry.error and not entry.incomplete_ocr and not entry.reviewed]
        if not pending:
            messagebox.showinfo('Confirm all', 'No images with selected boxes are awaiting confirmation.')
            return
        if not messagebox.askyesno(
                'Confirm all?',
                f'Apply {self.method.get()} to the selected boxes on {len(pending)} image(s)? '
                'Images without selected boxes, with partial scans, or with errors will be skipped.'):
            return
        for entry in pending:
            entry.reviewed = True
        if self.active is not None and self.image is not None:
            self.confirmed = self.entries[self.active].reviewed
            self.render()
        self.refresh_files()
        self.status.config(text=f'Confirmed {len(pending)} image(s). Use Save reviewed images to export them.')

    def save_reviewed(self):
        if self.busy:
            return
        self.store_active()
        pending = [(index, entry) for index, entry in enumerate(self.entries) if entry.reviewed and not entry.saved]
        if not pending:
            messagebox.showinfo('Save reviewed images', 'Confirm the selection on each image you want to save.')
            return
        self.export_entries(pending)

    def export_entries(self, pending, individual=False):
        jobs = []
        targets = set()
        try:
            for index, entry in pending:
                target = output_path(self.output_directory, self.filename_template, entry.path, index + 1)
                if individual:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    chosen = filedialog.asksaveasfilename(
                        initialdir=str(target.parent),
                        initialfile=target.name, defaultextension='.png', filetypes=[('PNG image', '*.png')],
                    )
                    if not chosen:
                        return
                    target = Path(chosen)
                    if target.suffix.lower() != '.png':
                        raise ValueError('Choose a filename ending in .png.')
                outputs = [target]
                if self.include_log:
                    outputs.append(target.with_suffix('.redactions.json'))
                for path in outputs:
                    key = str(path.resolve()).casefold()
                    if key in targets or path.exists():
                        raise ValueError(f'{path.name} already exists or would be written twice. Choose another name or folder.')
                    targets.add(key)
                jobs.append((entry, target))
        except (ValueError, KeyError, IndexError, AttributeError, OSError) as error:
            messagebox.showerror('Cannot save images', str(error))
            return

        unredacted = sum(not entry.selected for _, entry in pending)
        if unredacted and not messagebox.askyesno(
            'Save unredacted copies?', f'{unredacted} reviewed image(s) have no selected boxes. Save them as unredacted PNG copies?'):
            return

        include_log = self.include_log
        snapshots = [(FolderImage(entry.path, boxes=entry.boxes.copy(), selected=entry.selected.copy(),
                                  stamp=entry.stamp, method=entry.method), target) for entry, target in jobs]

        def operation(job):
            snapshot, target = job
            target.parent.mkdir(parents=True, exist_ok=True)
            write_folder_copy(snapshot, target, include_log)

        def accept(index, result, error):
            entry, target = jobs[index]
            snapshot, _ = snapshots[index]
            if error:
                self.status.config(text=f'{entry.path.name} · {error}')
            elif entry.reviewed and (entry.boxes, entry.selected, entry.method) == (
                    snapshot.boxes, snapshot.selected, snapshot.method):
                entry.saved = True
                entry.error = ''
                self.status.config(text=f'Saved {target.name} to {target.parent}')

        self.run_jobs('Saving', snapshots, operation, accept)


if __name__ == '__main__':
    root = tk.Tk()
    FolderRedactor(root)
    root.mainloop()
