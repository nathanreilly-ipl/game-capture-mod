# Copies the Lua script and the built add-on into the game folder.
#   .\scripts\deploy.ps1            copies both (the game must be closed for the add-on)
#   .\scripts\deploy.ps1 -LuaOnly   copies only the Lua script; then reload it from the RedLua menu (F7)
param(
	[string]$GameDir = 'C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2',
	[ValidateSet('Release', 'Debug', 'RelWithDebInfo')]
	[string]$Config = 'Release',
	[switch]$LuaOnly
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath (Join-Path $GameDir 'RDR2.exe'))) {
	throw "RDR2.exe not found in $GameDir. Pass -GameDir."
}

$scriptsDir = Join-Path $GameDir 'RedLua\Scripts'
if (-not (Test-Path -LiteralPath $scriptsDir)) {
	throw "$scriptsDir does not exist. Install RedLua first (see README.md)."
}

Get-ChildItem -LiteralPath (Join-Path $root 'lua') -Filter '*.lua' | ForEach-Object {
	Copy-Item -LiteralPath $_.FullName -Destination $scriptsDir -Force
	Write-Host "Copied $($_.Name) to $scriptsDir"
}

if (-not $LuaOnly) {
	$addon = Join-Path $root "build\$Config\capture_mod.addon64"
	if (-not (Test-Path -LiteralPath $addon)) {
		throw "$addon not found. Run scripts\build.ps1 first, or pass -LuaOnly."
	}
	try {
		Copy-Item -LiteralPath $addon -Destination $GameDir -Force
	}
	catch {
		throw "Could not copy the add-on (is the game running?): $($_.Exception.Message)"
	}
	Write-Host "Copied capture_mod.addon64 to $GameDir"
}
