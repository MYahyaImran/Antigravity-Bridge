#!/usr/bin/env bash
# Antigravity Bridge - One-Line Linux / macOS Installer
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/MYahyaImran/Antigravity-Bridge/main/install.sh | bash

set -e

DEFAULT_REPO="https://github.com/MYahyaImran/Antigravity-Bridge"
REPO_URL="${AG_BRIDGE_REPO:-$DEFAULT_REPO}"

echo ""
echo "============================================================"
echo "    Antigravity Multi-Account Bridge Installer (Unix)       "
echo "============================================================"
echo ""

if command -v uv >/dev/null 2>&1; then
    echo "[INFO] Detected 'uv' package manager. Installing via uv tool..."
    uv tool install --force "git+${REPO_URL}.git"
    echo "[SUCCESS] Installed apx successfully via uv!"
    apx status || true
    exit 0
fi

if command -v pipx >/dev/null 2>&1; then
    echo "[INFO] Detected 'pipx'. Installing via pipx..."
    pipx install --force "git+${REPO_URL}.git"
    echo "[SUCCESS] Installed apx successfully via pipx!"
    apx status || true
    exit 0
fi

if command -v python3 >/dev/null 2>&1; then
    echo "[INFO] Installing via python3 pip..."
    python3 -m pip install --upgrade --force-reinstall --no-cache-dir "git+${REPO_URL}.git"
    echo "[SUCCESS] Installed apx successfully via pip!"
    echo "Run 'apx start -d' to start the server."
    exit 0
fi

echo "[ERROR] Neither uv, pipx, nor python3 were found."
echo "Please install Python 3.9+ to continue."
exit 1
