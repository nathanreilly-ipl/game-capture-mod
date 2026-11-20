# Runs the capture command line (python -m capture) with this project's Python via uv.
#   .\capture.ps1 scout --name lakeshore
#   .\capture.ps1 submit --rig <rig.json> --location rdr2-lakeshore-001
#   .\capture.ps1 worker --once
#   .\capture.ps1 --help
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $env:USERPROFILE '.local\bin\uv.exe' }
# On this machine uv's default Python folder holds a broken link; use the working one if present.
$pyDir = Join-Path $env:USERPROFILE '.local\share\uv\python'
if (-not $env:UV_PYTHON_INSTALL_DIR -and (Test-Path -LiteralPath $pyDir)) { $env:UV_PYTHON_INSTALL_DIR = $pyDir }
$env:PYTHONPATH = $PSScriptRoot
$env:PYTHONUNBUFFERED = '1'  # progress lines appear as they happen
& $uv run --quiet --project $PSScriptRoot python -m capture @args
exit $LASTEXITCODE
