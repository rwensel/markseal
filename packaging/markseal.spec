import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

packaging_dir = Path(SPECPATH).resolve()
root = packaging_dir.parent

datas = list(collect_data_files('markseal'))
datas += collect_data_files('PySide6', subdir='qml')
binaries = []
hiddenimports = []
for package in ('rapidocr', 'onnxruntime'):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(packaging_dir / 'run_markseal.py')],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Markseal',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(packaging_dir / 'icons' / 'markseal.ico'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Markseal')
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Markseal.app',
        bundle_identifier='app.markseal',
        info_plist={'NSHighResolutionCapable': True},
    )
