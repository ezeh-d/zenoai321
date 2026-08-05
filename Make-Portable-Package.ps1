# ============================================================
# Bundles REYES -- the real reyes_agent app, its vault (memory,
# notes, projects), and the installer -- into a single zip you
# can carry to another machine (USB drive, cloud folder, etc).
#
# Run this on the ORIGINAL machine:
#   powershell -ExecutionPolicy Bypass -File Make-Portable-Package.ps1
#
# On the new machine: extract the zip, then run install.ps1
# from inside it (that's what asks for the password).
#
# The zip includes .env and the vault -- real API keys and your
# actual memory/notes/projects. Treat the zip file itself as
# sensitive: don't upload it anywhere public, and delete it once
# you've moved it to the new machine if you don't need the copy.
# ============================================================

$ErrorActionPreference = "Stop"
$RootDir = $PSScriptRoot
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$stagingDir = Join-Path $env:TEMP "REYES-Portable-Staging-$stamp"
$outputZip = Join-Path ([Environment]::GetFolderPath("Desktop")) "REYES-Portable-$stamp.zip"

Write-Host ""
Write-Host "=== Building portable REYES package ===" -ForegroundColor Cyan

if (Test-Path $stagingDir) { Remove-Item $stagingDir -Recurse -Force }
New-Item -ItemType Directory -Path $stagingDir | Out-Null

$itemsToCopy = @(
    "reyes_agent",
    "REYES",
    "Open REYES.bat",
    "install.ps1",
    "reyes_requirements.txt",
    ".env"
)

foreach ($item in $itemsToCopy) {
    $src = Join-Path $RootDir $item
    if (Test-Path $src) {
        Write-Host "  including $item" -ForegroundColor DarkGray
        Copy-Item -Path $src -Destination (Join-Path $stagingDir $item) -Recurse -Force
    } else {
        Write-Host "  skipping $item (not found)" -ForegroundColor Yellow
    }
}

# Drop caches/venv artifacts that shouldn't travel or would just
# bloat the zip -- they get rebuilt fresh by install.ps1 anyway.
Get-ChildItem -Path $stagingDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if (Test-Path $outputZip) { Remove-Item $outputZip -Force }
Compress-Archive -Path (Join-Path $stagingDir "*") -DestinationPath $outputZip -CompressionLevel Optimal

Remove-Item $stagingDir -Recurse -Force

Write-Host ""
Write-Host "=== Package ready ===" -ForegroundColor Green
Write-Host $outputZip -ForegroundColor Green
Write-Host "Contains your real API keys (.env) and vault data -- keep it as private as you'd keep those." -ForegroundColor Yellow
Write-Host "On the new machine: extract, then run install.ps1 (it will ask for the password)." -ForegroundColor Cyan
