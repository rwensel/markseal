# Packaging

Builds the standalone MarkSeal desktop app with PyInstaller. The bundle includes
the QML shell and the bundled RapidOCR models, so the installed app needs no
Python, pip, or network access.

## Prerequisites

```
.venv\Scripts\python.exe -m pip install -e ".[build]"
```

Regenerate `THIRD_PARTY_NOTICES.txt` after dependency changes:

```
.venv\Scripts\python.exe packaging\generate_notices.py
```

## Windows (primary target)

```
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

Produces `dist\Markseal\Markseal.exe`. If Inno Setup (`ISCC.exe`) is on `PATH`,
it also produces `dist\Markseal-Setup.exe` from `markseal.iss`.

## macOS

```
sh packaging/build-macos.sh
```

Produces `dist/Markseal.app`. The spec adds the `BUNDLE` step when run on macOS.

## Linux

```
sh packaging/build-linux.sh
```

Produces `dist/Markseal/`. Wrap that directory as an AppImage with `appimagetool`
if a single-file artifact is wanted.

## Verifying a build

Launch the built app and complete one scan offline; the bundled RapidOCR models
mean no download is needed.
