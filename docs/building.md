# Building from source

MarkSeal is a Python 3.10+ / PySide6 application packaged with PyInstaller. The bundle includes the QML shell and the bundled RapidOCR models, so the installed app needs no Python, pip, or network access.

## Prerequisites

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[build]"
```

On Linux or macOS, use `.venv/bin/python`.

## Windows (primary target)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Produces `dist\Markseal\Markseal.exe`. If Inno Setup (`ISCC.exe`) is on `PATH`, it also produces `dist\Markseal-Setup.exe` from `packaging\markseal.iss`. Pass `-SkipTests` to skip the suite.

## Linux

```sh
sh packaging/build-linux.sh
```

Produces `dist/Markseal/`. Wrap that directory as an AppImage with `appimagetool` if a single-file artifact is wanted. Set `SKIP_TESTS=1` to skip the suite.

## macOS

```sh
sh packaging/build-macos.sh
```

Produces `dist/Markseal.app`. The spec adds the `BUNDLE` step on macOS. The app is unsigned and not notarized by default. Set `SKIP_TESTS=1` to skip the suite.

## Tests

```powershell
.venv\Scripts\python.exe -m unittest
```

CI runs the suite on Windows; the Linux and macOS release builds are produced without running tests.

## Third-party notices

Regenerate `THIRD_PARTY_NOTICES.txt` after dependency changes:

```powershell
.venv\Scripts\python.exe packaging\generate_notices.py
```

The generator reads the installed runtime packages and their license files. The resulting file is bundled by the spec and copied beside the executable by the installer.

## Manual builds

The GitHub Actions **build** workflow (`.github/workflows/build.yml`) can be started manually. It builds the Windows installer, a Linux x64 tarball, and a macOS arm64 zip, and uploads them as workflow artifacts.
