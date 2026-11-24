# Building from source

MarkSeal is a Python 3.10+ / PySide6 application packaged with PyInstaller. The bundle includes the QML shell, the bundled RapidOCR models, the local PII NER model, and the PDFium renderer, so the installed app needs no Python, pip, external PDF tool, or network access.

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

## PII model

The personal-data categories use a pinned GLiNER PII Small ONNX artifact. It is not committed. The build scripts run `packaging/fetch_ner_model.py`, which downloads three pinned files, verifies their SHA-256 values, and writes `markseal/models/ner/` plus a manifest. Source runs need the same step:

```powershell
.venv\Scripts\python.exe packaging\fetch_ner_model.py
```

Without the model, the personal categories produce no suggestions and the real-model integration test is skipped. The app never downloads the model at runtime. The artifact adds about 86 MB to the installed app and installer.

## Tests

```powershell
.venv\Scripts\python.exe -m unittest
```

CI runs the suite on Windows; the Linux and macOS release builds are produced without running tests. `tests/test_ner_integration.py` runs when the PII model is present and skips otherwise; the release gate runs it with the model fetched. The PDF renderer uses pypdfium2, so the freeze must include its bundled PDFium binary; the spec's `collect_all('pypdfium2')` entry does that.

## Third-party notices

Regenerate `THIRD_PARTY_NOTICES.txt` after dependency changes:

```powershell
.venv\Scripts\python.exe packaging\generate_notices.py
```

The generator reads the installed runtime packages and their license files, including pypdfium2/PDFium, and adds the GLiNER PII model, GLiNER runtime, Ettin encoder, and tokenizers entries. The resulting file is bundled by the spec and copied beside the executable by the installer.

## Versioning and releases

Classify a release before publishing it:

- **Patch**: fixes only, with no new capability and no change to saved settings, exports, or workflow.
- **Minor**: a backward-compatible capability. Existing settings, exports, and workflow keep working.
- **Major**: a breaking change to saved settings, exports, or workflow.

The version is written in `markseal/__init__.py`, `packaging/markseal.iss`, and the Windows line of the README download table. Change all three together, update any other page that names the current version (today `docs/getting-started.md`), commit, and tag the release.

Watched folders is a minor release and targets 2.1.0. The bump happens when the release is published, not on the feature branch.

## Manual builds

The GitHub Actions **build** workflow (`.github/workflows/build.yml`) can be started manually. It builds the Windows installer, a Linux x64 tarball, and a macOS arm64 zip, and uploads them as workflow artifacts.
