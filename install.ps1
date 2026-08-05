# ============================================================
# REYES portable installer.
#
# Run this FIRST after copying/extracting the REYES folder onto
# a new machine -- it won't set anything up until the correct
# password is entered.
#
# Usage (from a PowerShell prompt, inside this folder):
#   powershell -ExecutionPolicy Bypass -File install.ps1
#
# Forgot the password? Run instead:
#   powershell -ExecutionPolicy Bypass -File install.ps1 -ForgotPassword
# That sends it to your Telegram (via the REYES bot, @Reyes3_boss_bot)
# instead of running the install -- needs .env with the Telegram bot
# token/chat ID to be present in this same folder.
#
# Honest limits, worth reading before relying on this:
# - This is a soft gate, not real security. The password check
#   lives in this plaintext script; anyone who opens the file in
#   a text editor can read the logic (though not reverse the
#   SHA-256 hash back into the password itself). It stops someone
#   from casually finishing setup, it does not stop someone
#   willing to edit this script. -ForgotPassword also means the
#   plaintext password lives in this file (further down) so it can
#   be recovered -- same trust level as everything else here.
# - .env (if you copied it alongside this folder) holds real API
#   keys in plaintext. Treat the whole folder/zip as sensitive,
#   the same as you would any file with passwords in it.
# ============================================================

param(
    [switch]$ForgotPassword
)

$ErrorActionPreference = "Stop"
$RootDir = $PSScriptRoot

function Get-Sha256Hash([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $hashBytes = $sha.ComputeHash($bytes)
    -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
}

# SHA-256 of the install password -- not stored in plaintext in the
# normal (compare-only) path below. The plaintext only appears in the
# -ForgotPassword branch, where it has to, to be recoverable at all.
$ExpectedHash = "6782b7879be449bea086dfef26c85b0fe7d6cda3709085ff3fd3bd5ecb9ed9a4"
$PlaintextPassword = "DIVINE"

function Read-DotEnvValue([string]$EnvPath, [string]$Key) {
    if (-not (Test-Path $EnvPath)) { return $null }
    $line = Get-Content $EnvPath | Where-Object { $_ -match "^$Key=" } | Select-Object -First 1
    if (-not $line) { return $null }
    return $line.Substring($Key.Length + 1).Trim()
}

if ($ForgotPassword) {
    $envPath = Join-Path $RootDir ".env"
    $botToken = Read-DotEnvValue $envPath "TELEGRAM_BOT_TOKEN"
    $chatId = Read-DotEnvValue $envPath "TELEGRAM_NOTIFY_CHAT_ID"

    if (-not $botToken -or -not $chatId) {
        Write-Host "Can't send a reminder -- .env is missing TELEGRAM_BOT_TOKEN or TELEGRAM_NOTIFY_CHAT_ID." -ForegroundColor Red
        Write-Host "Make sure .env was copied into this same folder." -ForegroundColor Yellow
        exit 1
    }

    $body = @{ chat_id = $chatId; text = "REYES install password: $PlaintextPassword" } | ConvertTo-Json
    try {
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$botToken/sendMessage" -Method Post -Body $body -ContentType "application/json" | Out-Null
        Write-Host "Password reminder sent via Telegram." -ForegroundColor Green
    } catch {
        Write-Host "Couldn't reach Telegram: $_" -ForegroundColor Red
        exit 1
    }
    exit 0
}

Write-Host ""
Write-Host "=== REYES portable install ===" -ForegroundColor Cyan
Write-Host "This will set up REYES on this machine." -ForegroundColor Cyan
Write-Host ""

$verified = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    $secure = Read-Host "Enter the install password" -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $plain = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)

    if ((Get-Sha256Hash $plain) -eq $ExpectedHash) {
        $verified = $true
        break
    }
    Write-Host "Wrong password. $(3 - $attempt) attempt(s) left." -ForegroundColor Red
}

if (-not $verified) {
    Write-Host ""
    Write-Host "Install aborted -- password not verified." -ForegroundColor Red
    exit 1
}

Write-Host "Password accepted. Setting up REYES..." -ForegroundColor Green
Write-Host ""

# --- Find Python ---
$pythonCmd = $null
try {
    & py -3 --version | Out-Null
    if ($?) { $pythonCmd = "py -3" }
} catch {}
if (-not $pythonCmd) {
    try {
        & python --version | Out-Null
        if ($?) { $pythonCmd = "python" }
    } catch {}
}
if (-not $pythonCmd) {
    Write-Host "No Python install found on this machine." -ForegroundColor Red
    Write-Host "Install Python 3.11+ from https://python.org first, then re-run this script." -ForegroundColor Yellow
    exit 1
}
Write-Host "Found Python via '$pythonCmd'." -ForegroundColor Green

# --- Create the virtual environment ---
$venvPath = Join-Path $RootDir ".venv"
if (-not (Test-Path $venvPath)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    if ($pythonCmd -eq "py -3") {
        & py -3 -m venv $venvPath
    } else {
        & python -m venv $venvPath
    }
} else {
    Write-Host "Virtual environment already exists -- reusing it." -ForegroundColor Yellow
}

$venvPython = Join-Path $venvPath "Scripts\python.exe"

# --- Install dependencies ---
# A brand-new venv's pip has no fix yet for a corporate/AV/VPN network
# that intercepts TLS (a real issue hit during REYES's own dev setup --
# see AGENT.md's SSL section) -- if the plain install fails on a
# certificate error, retry once trusting the standard PyPI hosts
# directly rather than leaving the install dead on a fixable error.
Write-Host "Installing dependencies (this can take a few minutes)..." -ForegroundColor Cyan
$reqFile = Join-Path $RootDir "reyes_requirements.txt"
$trustedHosts = @("--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org", "--trusted-host", "pypi.python.org")

& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "Standard pip upgrade hit an error (possibly a TLS-intercepting network) -- retrying with trusted PyPI hosts..." -ForegroundColor Yellow
    & $venvPython -m pip install --upgrade pip --quiet @trustedHosts
}

& $venvPython -m pip install -r $reqFile
if ($LASTEXITCODE -ne 0) {
    Write-Host "Standard install hit an error (possibly a TLS-intercepting network) -- retrying with trusted PyPI hosts..." -ForegroundColor Yellow
    & $venvPython -m pip install -r $reqFile @trustedHosts
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Dependency install still failed -- see the output above for the real error." -ForegroundColor Red
        exit 1
    }
}

# --- Check for .env ---
$envPath = Join-Path $RootDir ".env"
if (-not (Test-Path $envPath)) {
    Write-Host ""
    Write-Host "No .env found -- REYES needs one with your API keys to actually run." -ForegroundColor Yellow
    Write-Host "Copy your .env from the original machine into this folder, or create" -ForegroundColor Yellow
    Write-Host "one based on .env.example, before launching REYES." -ForegroundColor Yellow
} else {
    Write-Host ".env found -- your settings carried over." -ForegroundColor Green
}

# --- Desktop shortcut ---
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "REYES.lnk"
    $targetBat = Join-Path $RootDir "Open REYES.bat"
    $iconPath = Join-Path $RootDir "reyes_agent\static\reyes_icon.ico"

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $targetBat
    $shortcut.WorkingDirectory = $RootDir
    if (Test-Path $iconPath) {
        $shortcut.IconLocation = $iconPath
    }
    $shortcut.Save()
    Write-Host "Desktop shortcut created: $shortcutPath" -ForegroundColor Green
} catch {
    Write-Host "Couldn't create the desktop shortcut automatically -- you can still launch REYES via 'Open REYES.bat'." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Install complete ===" -ForegroundColor Cyan
Write-Host "Launch REYES from the new Desktop shortcut, or by double-clicking 'Open REYES.bat'." -ForegroundColor Cyan
