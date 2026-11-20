# Reloads every Script Hook plugin (RedLua included) in the running game, without
# restarting it, using Script Hook's CTRL+R feature. Use it after a RedLua
# exception. Needs the empty file ScriptHookRDR2.dev in the game folder (created
# here if missing; Script Hook may only notice it at the next game start).
#
# The game window is brought to the front and receives CTRL+R twice.
param(
	[string]$GameDir = 'C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2',
	[string]$CaptureDir = (Join-Path $env:USERPROFILE 'Documents\RDR2Modding\captures'),
	[int]$TimeoutSec = 60
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'game_input.ps1')

$dev = Join-Path $GameDir 'ScriptHookRDR2.dev'
if (-not (Test-Path -LiteralPath $dev)) {
	New-Item -ItemType File -Path $dev | Out-Null
	Write-Host "Created $dev"
}

$hwnd = Get-GameWindow
if ($hwnd -eq [IntPtr]::Zero) { throw 'The game window was not found. Is the game running?' }
if (-not [GameInput]::Focus($hwnd)) { throw 'Could not bring the game window to the front.' }

$chord = [uint16[]]@($Scan.Ctrl, $Scan.R)

# First CTRL+R unloads all scripts. The loader's heartbeat stops (or its file is removed).
if (-not [GameInput]::SendChord($hwnd, $chord, 120)) { throw 'The game lost focus before the key press.' }
Write-Host 'Sent CTRL+R (unload)'

# If the loader was running, its heartbeat must stop; otherwise nothing was unloaded.
$wasAlive = (Get-HeartbeatAge $CaptureDir) -lt 3
Start-Sleep -Seconds 6
if ($wasAlive -and (Get-HeartbeatAge $CaptureDir) -lt 3) {
	throw 'CTRL+R had no effect: the loader is still running. Script Hook probably reads ScriptHookRDR2.dev only when the game starts, so restart the game once (scripts\restart_game.ps1).'
}

# Scripts are unloaded now, so RedLua cannot overwrite its settings file.
if (Enable-RedLuaAutorun $GameDir) { Write-Host 'RedLua Autorun is on' }

if (-not [GameInput]::Focus($hwnd)) { throw 'Could not bring the game window to the front.' }
if (-not [GameInput]::SendChord($hwnd, $chord, 120)) { throw 'The game lost focus before the key press.' }
Write-Host 'Sent CTRL+R (load)'

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-HeartbeatAge $CaptureDir) -gt 3) {
	if ((Get-Date) -gt $deadline) {
		throw "No loader heartbeat $TimeoutSec s after reloading. Check ScriptHookRDR2.log; a full restart may be needed (scripts\restart_game.ps1)."
	}
	Start-Sleep -Milliseconds 500
}
Write-Host 'Loader heartbeat is back'
