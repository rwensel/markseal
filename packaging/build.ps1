param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $SkipTests) {
    & .venv\Scripts\python.exe -m unittest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; fix them before building.' }
}
& .venv\Scripts\python.exe packaging\fetch_ner_model.py
if ($LASTEXITCODE -ne 0) { throw 'PII model fetch failed.' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging\markseal.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Write-Host 'Built dist\Markseal\Markseal.exe'
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    $iscc = Get-ChildItem -Path @("$env:LOCALAPPDATA\Programs\Inno Setup*\ISCC.exe",
        'C:\Program Files*\Inno Setup*\ISCC.exe') -ErrorAction SilentlyContinue |
        Select-Object -First 1
}
if ($iscc) {
    $isccPath = if ($iscc -is [System.Management.Automation.ApplicationInfo]) { $iscc.Source } else { $iscc.FullName }
    & $isccPath packaging\markseal.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }
    Write-Host 'Built dist\Markseal-Setup.exe'
} else {
    Write-Host 'Inno Setup (ISCC.exe) not found; skipped the installer wrapper. The app is in dist\Markseal\.'
}
