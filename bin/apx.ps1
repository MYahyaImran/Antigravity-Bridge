$scriptDir = $PSScriptRoot
$bridgePy = Join-Path (Split-Path $scriptDir -Parent) "bridge.py"

$py = "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe"
if (-not (Test-Path $py)) {
    $py = "$env:LOCALAPPDATA\Python\bin\python.exe"
}
if (-not (Test-Path $py)) {
    $py = "python"
}
& $py "$bridgePy" @args
