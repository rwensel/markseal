# Packaging

Builds the standalone Markseal desktop app with PyInstaller. The bundle includes
the QML shell and the bundled RapidOCR models, so the installed app needs no
Python, pip, or network access.

## Prerequisites

```
.venv\Scripts\python.exe -m pip install -e ".[build]"
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

## Publishing an update

Install the release extra, then provide R2 credentials (`R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) and optionally `R2_BUCKET`
(default `markseal-releases`):

```
.venv\Scripts\python.exe -m pip install -e ".[release]"
.venv\Scripts\python.exe packaging\publish_release.py --version 2.1.0 `
    --notes-file RELEASE-NOTES.md --page-url https://markseal.staginglane.app `
    --artifact windows-x64=dist\Markseal-Setup-2.1.0.exe --dry-run
```

Artifacts go to `releases/<version>/<platform>/<file>` with an immutable cache
policy; the manifest is written to `stable/latest.json` with a 60-second cache so
a release appears quickly. Drop `--dry-run` to upload. Both are served from the
`updates.staginglane.app` custom domain on the bucket; no server runs.

Instead of exporting `R2_*` variables, pass `--vault-path secret/prod/markseal/r2`
to read them from Vault KV v2. Set `VAULT_ADDR`, then authenticate with
`VAULT_TOKEN` or AppRole (`VAULT_ROLE_ID` + `VAULT_SECRET_ID`); use `VAULT_CACERT`
for a private CA, or `VAULT_SKIP_VERIFY=1` for an internal endpoint.

## One command

Copy `packaging\.release.env.example` to `packaging\.release.env` and fill in
`VAULT_ADDR`, `VAULT_ROLE_ID`, and `VAULT_SECRET_ID`. The file is gitignored.

```
powershell -ExecutionPolicy Bypass -File packaging\release.ps1 -Notes "Initial release."
```

It reads the version from `markseal/__init__.py`, runs the tests and the PyInstaller +
Inno build, publishes the installer and manifest to R2 through Vault AppRole, and prints
the manifest URL. `-DryRun` prints the upload plan without contacting Vault or R2, and
`-SkipBuild` reuses an existing `dist\Markseal-Setup.exe`.

## Verifying a build

Launch the built app and complete one scan offline; the bundled RapidOCR models
mean no download is needed.
