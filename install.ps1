# Antigravity Bridge - One-Line Windows Installer
# Usage:
#   irm https://raw.githubusercontent.com/MYahyaImran/Antigravity-Bridge/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   Antigravity Multi-Account Bridge Installer (Windows)    " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Determine target repository
$DEFAULT_REPO = "https://github.com/MYahyaImran/Antigravity-Bridge"
$REPO_URL = if ($env:AG_BRIDGE_REPO) { $env:AG_BRIDGE_REPO } else { $DEFAULT_REPO }
Write-Host "[INFO] Target repository: $REPO_URL" -ForegroundColor Gray

# 1. Locate Python or uv
$PythonExe = $null
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Host "[INFO] Detected 'uv' package manager." -ForegroundColor Green
    Write-Host "[INFO] Installing Antigravity Bridge via uv tool..." -ForegroundColor Yellow
    uv tool install --force "git+$REPO_URL.git"
    Write-Host "[SUCCESS] Installed apx successfully via uv!" -ForegroundColor Green
    & apx status
    exit 0
}

if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PythonExe = "python"
} elseif (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PythonExe = "py"
} else {
    Write-Host "[ERROR] Python 3.9+ was not found on your system." -ForegroundColor Red
    Write-Host "Please install Python from https://www.python.org/downloads/ or via 'winget install Python.Python.3.12'" -ForegroundColor Yellow
    exit 1
}

Write-Host "[INFO] Using Python: $((Get-Command $PythonExe).Source)" -ForegroundColor Gray

# 2. Check if git is available
$hasGit = [bool](Get-Command "git" -ErrorAction SilentlyContinue)

if ($hasGit) {
    Write-Host "[INFO] Git detected. Installing package directly from repository..." -ForegroundColor Yellow
    & $PythonExe -m pip install --upgrade "git+$REPO_URL.git"
} else {
    Write-Host "[INFO] Git not found. Downloading repository archive directly..." -ForegroundColor Yellow
    $zipUrl = "$REPO_URL/archive/refs/heads/main.zip"
    $tempZip = Join-Path $env:TEMP "antigravity_bridge_install.zip"
    $tempDir = Join-Path $env:TEMP "antigravity_bridge_extracted"

    if (Test-Path $tempDir) { Remove-Item -Recurse -Force $tempDir }
    Invoke-WebRequest -Uri $zipUrl -OutFile $tempZip
    Expand-Archive -Path $tempZip -DestinationPath $tempDir -Force

    $subFolders = Get-ChildItem -Path $tempDir -Directory
    $pkgDir = if ($subFolders.Count -gt 0) { $subFolders[0].FullName } else { $tempDir }

    Write-Host "[INFO] Installing package via pip..." -ForegroundColor Yellow
    & $PythonExe -m pip install --upgrade $pkgDir

    # Clean up temp files
    Remove-Item -Force $tempZip -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
}

# 3. Verify Scripts directory in PATH
$scriptsPath = & $PythonExe -c "import sysconfig; print(sysconfig.get_path('scripts'))"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$scriptsPath*") {
    Write-Host "[INFO] Adding Python scripts to User PATH: $scriptsPath" -ForegroundColor Cyan
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$scriptsPath", "User")
    $env:Path = "$env:Path;$scriptsPath"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Antigravity Bridge ('apx') installed successfully!       " -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Quick Start Commands:" -ForegroundColor Cyan
Write-Host "  apx start -d     # Start bridge server in background (port 8090)"
Write-Host "  apx setup all    # 1-Click auto-configure Claude, Cursor, Hermes, Aider"
Write-Host "  apx status       # Check running bridge status and quotas"
Write-Host "  apx stop         # Stop running server"
Write-Host ""
