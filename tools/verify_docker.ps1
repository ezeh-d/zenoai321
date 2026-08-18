# Post-reboot check: did WSL and the Docker engine actually come up?
#
# Run this AFTER the restart. It answers one question -- can ZENO's gateway
# image be built on this machine -- and says which step failed if not.
#
#   powershell -ExecutionPolicy Bypass -File tools\verify_docker.ps1

$ErrorActionPreference = 'Continue'
$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"

Write-Host "1. WSL" -ForegroundColor Cyan
$status = (& wsl.exe --status 2>&1 | Out-String) -replace "`0", ""
if ($status -match 'WSL_E_WSL_OPTIONAL_COMPONENT_REQUIRED') {
    Write-Host "   FAILED - the optional component still is not active." -ForegroundColor Red
    Write-Host "   The reboot may not have happened. Restart and run this again."
    exit 1
}
Write-Host "   ok" -ForegroundColor Green
Write-Host ($status.Trim())

Write-Host "`n2. Docker Desktop" -ForegroundColor Cyan
if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
    Write-Host "   not running; starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe" -ErrorAction SilentlyContinue
}

Write-Host "`n3. Waiting for the engine (up to 4 minutes)" -ForegroundColor Cyan
$up = $false
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 10
    $version = & $docker version --format '{{.Server.Version}}' 2>$null
    if ($LASTEXITCODE -eq 0 -and $version) {
        Write-Host "   engine up after $((($i + 1) * 10))s - server $version" -ForegroundColor Green
        $up = $true
        break
    }
    Write-Host "   ...$((($i + 1) * 10))s"
}
if (-not $up) {
    Write-Host "   FAILED - the engine did not start." -ForegroundColor Red
    Write-Host "   Open Docker Desktop and read what it reports; 8 GB RAM is tight for it."
    exit 1
}

Write-Host "`n4. Building the ZENO gateway image" -ForegroundColor Cyan
Push-Location (Split-Path $PSScriptRoot -Parent)
& $docker build -f Dockerfile.anywhere -t zeno-anywhere .
$built = $LASTEXITCODE
Pop-Location
if ($built -ne 0) {
    Write-Host "   FAILED - the build did not complete." -ForegroundColor Red
    exit 1
}

Write-Host "`n5. Running it, and asking it whether it is alive" -ForegroundColor Cyan
# A container is not "working" because it started. It is working when it
# answers, so this asks /health and reads the reply.
& $docker rm -f zeno-anywhere-check 2>$null | Out-Null
& $docker run -d --name zeno-anywhere-check -p 8091:8080 zeno-anywhere | Out-Null
Start-Sleep -Seconds 12
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8091/health" -TimeoutSec 10
    Write-Host "   /health -> $($health.state) ($($health.service) $($health.version))" -ForegroundColor Green
    Write-Host "`nBUILT AND VERIFIED." -ForegroundColor Green
} catch {
    Write-Host "   the container started but did not answer /health" -ForegroundColor Red
    & $docker logs --tail 30 zeno-anywhere-check
    exit 1
} finally {
    & $docker rm -f zeno-anywhere-check 2>$null | Out-Null
}
