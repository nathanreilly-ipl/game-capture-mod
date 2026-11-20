# Clones the ReShade repository (for its header-only add-on API) into deps\reshade.
# The tag should match the ReShade version installed for the game.
param(
	[string]$ReShadeTag = 'v6.8.0'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root 'deps\reshade'

if (Test-Path -LiteralPath (Join-Path $target 'include\reshade.hpp')) {
	Write-Host "ReShade headers already present in $target"
	exit 0
}

New-Item -ItemType Directory -Force -Path (Join-Path $root 'deps') | Out-Null
git clone --depth 1 --branch $ReShadeTag https://github.com/crosire/reshade.git $target
if ($LASTEXITCODE -ne 0) { throw "git clone failed with exit code $LASTEXITCODE" }
Write-Host "ReShade $ReShadeTag headers are in $target\include"
