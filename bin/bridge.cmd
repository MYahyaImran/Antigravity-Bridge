@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "BRIDGE_PY=%SCRIPT_DIR%..\bridge.py"

if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" (
    "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" "%BRIDGE_PY%" %*
) else if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    "%LOCALAPPDATA%\Python\bin\python.exe" "%BRIDGE_PY%" %*
) else (
    python "%BRIDGE_PY%" %*
)
endlocal
