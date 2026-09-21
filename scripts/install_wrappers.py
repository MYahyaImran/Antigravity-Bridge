import os
import sys
from pathlib import Path

# Resolve repository root dynamically at runtime
REPO_ROOT = Path(__file__).resolve().parent.parent
BRIDGE_PY = REPO_ROOT / "bridge.py"

cmd_content = f"""@echo off
if exist "%LOCALAPPDATA%\\Python\\pythoncore-3.14-64\\python.exe" (
    "%LOCALAPPDATA%\\Python\\pythoncore-3.14-64\\python.exe" "{BRIDGE_PY}" %*
) else if exist "%LOCALAPPDATA%\\Python\\bin\\python.exe" (
    "%LOCALAPPDATA%\\Python\\bin\\python.exe" "{BRIDGE_PY}" %*
) else (
    python "{BRIDGE_PY}" %*
)
"""

ps1_content = f"""$py = "$env:LOCALAPPDATA\\Python\\pythoncore-3.14-64\\python.exe"
if (-not (Test-Path $py)) {{
    $py = "$env:LOCALAPPDATA\\Python\\bin\\python.exe"
}}
if (-not (Test-Path $py)) {{
    $py = "python"
}}
& $py "{BRIDGE_PY}" @args
"""

# POSIX representation of BRIDGE_PY
bridge_py_posix = str(BRIDGE_PY).replace("\\", "/")
if len(bridge_py_posix) > 2 and bridge_py_posix[1] == ":":
    drive_letter = bridge_py_posix[0].lower()
    bridge_py_posix = f"/{drive_letter}" + bridge_py_posix[2:]

sh_content = f"""#!/bin/sh
if [ -f "$LOCALAPPDATA/Python/pythoncore-3.14-64/python.exe" ]; then
    PY="$LOCALAPPDATA/Python/pythoncore-3.14-64/python.exe"
elif [ -f "$LOCALAPPDATA/Python/bin/python.exe" ]; then
    PY="$LOCALAPPDATA/Python/bin/python.exe"
else
    PY="python"
fi
"$PY" "{bridge_py_posix}" "$@"
"""

local_app_data = os.environ.get("LOCALAPPDATA", "")
app_data = os.environ.get("APPDATA", "")

targets = []
if local_app_data:
    targets.extend([
        Path(local_app_data) / "agy" / "bin",
        Path(local_app_data) / "hermes" / "bin",
    ])
if app_data:
    targets.append(Path(app_data) / "npm")

if Path(r"C:\nvm4w\nodejs").exists():
    targets.append(Path(r"C:\nvm4w\nodejs"))

for target in targets:
    if target.exists():
        for name in ["apx", "bridge"]:
            (target / f"{name}.cmd").write_text(cmd_content, encoding="utf-8")
            (target / f"{name}.ps1").write_text(ps1_content, encoding="utf-8")
            (target / f"{name}").write_text(sh_content, encoding="utf-8")
            print(f"Installed {name} wrappers in {target}")
