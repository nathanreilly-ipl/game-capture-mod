#!/bin/sh
# Runs the capture command line (python -m capture) with this project's Python via uv, on Linux
# (capture.ps1 is the same for Windows).
#   ./capture.sh host status
#   ./capture.sh install cyberpunk --mods out/mods/capture-mods-cyberpunk.zip
#   ./capture.sh verify cyberpunk --launch
#   ./capture.sh --help
here=$(cd "$(dirname "$0")" && pwd)
uv=$(command -v uv || echo "$HOME/.local/bin/uv")
export PYTHONPATH="$here" PYTHONUNBUFFERED=1
exec "$uv" run --quiet --project "$here" python -m capture "$@"
