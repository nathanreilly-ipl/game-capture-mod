# Closes the game, starts it again through Steam, gets through the menus into
# story mode, and waits until capture_loader.lua is running (its heartbeat).
#
# It presses Enter in the game window every few seconds until the heartbeat
# appears. Keys are only sent while the game is the foreground window, so leave
# the game in front while this runs (roughly two to four minutes).
param(
	[string]$GameDir = 'C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2',
	[string]$CaptureDir = (Join-Path $env:USERPROFILE 'Documents\RDR2Modding\captures'),
	[string]$SteamAppId = '1174180',
	[int]$TimeoutSec = 420,
	[int]$KeyIntervalSec = 5,
	[string]$SnapshotDir = ''      # if set, saves a picture of the game window every 15 s (for debugging the menus)
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'game_input.ps1')
$started = Get-Date

$running = Get-Process RDR2 -ErrorAction SilentlyContinue
if ($running) {
	Write-Host 'Closing the game'
	$running | Stop-Process -Force
	$running | Wait-Process -Timeout 60 -ErrorAction SilentlyContinue
	Start-Sleep -Seconds 3
}
# Steam counts the game as running while its launch stub (PlayRDR2.exe) and the Rockstar launcher
# live on, which they do after a forced close; a new start then fails with "Game already running".
$stub = Get-Process -Name 'PlayRDR2', 'Launcher', 'RockstarErrorHandler', 'RockstarSteamHelper', 'SocialClubHelper' -ErrorAction SilentlyContinue
if ($stub) {
	Write-Host 'Closing the Rockstar launcher'
	$stub | Stop-Process -Force -ErrorAction SilentlyContinue
}
$t = Get-Date
while (((Get-ItemProperty 'HKCU:\Software\Valve\Steam' -Name RunningAppID -ErrorAction SilentlyContinue).RunningAppID -eq [int]$SteamAppId) -and ((Get-Date) - $t).TotalSeconds -lt 60) {
	Start-Sleep -Seconds 1
}
if (((Get-ItemProperty 'HKCU:\Software\Valve\Steam' -Name RunningAppID -ErrorAction SilentlyContinue).RunningAppID) -eq [int]$SteamAppId) {
	Write-Warning 'Steam still lists the game as running; the start may fail with "Game already running"'
}

# With the game closed, nothing can overwrite these.
$dev = Join-Path $GameDir 'ScriptHookRDR2.dev'
if (-not (Test-Path -LiteralPath $dev)) { New-Item -ItemType File -Path $dev | Out-Null }
if (-not (Enable-RedLuaAutorun $GameDir)) { Write-Warning 'Could not turn on RedLua Autorun; the loader will not load by itself.' }
Remove-Item -LiteralPath (Join-Path $CaptureDir 'heartbeat.txt') -ErrorAction SilentlyContinue
if ($SnapshotDir) { New-Item -ItemType Directory -Force -Path $SnapshotDir | Out-Null }

Write-Host 'Starting the game through Steam'
Start-Process "steam://rungameid/$SteamAppId"

$deadline = $started.AddSeconds($TimeoutSec)
$lastKey = Get-Date
$lastShot = Get-Date
$shots = 0
$windowSeen = $null
while ((Get-HeartbeatAge $CaptureDir) -gt 3) {
	if ((Get-Date) -gt $deadline) {
		throw "No loader heartbeat after $TimeoutSec s. Is the game in story mode with RedLua Autorun on?"
	}
	$hwnd = Get-GameWindow
	if ($hwnd -ne [IntPtr]::Zero) {
		if (-not $windowSeen) {
			$windowSeen = Get-Date
			Write-Host ("Game window appeared after {0:N0} s" -f ($windowSeen - $started).TotalSeconds)
		}
		# Give the window a few seconds before the first key press.
		if (((Get-Date) - $windowSeen).TotalSeconds -gt 8 -and ((Get-Date) - $lastKey).TotalSeconds -ge $KeyIntervalSec) {
			if ([GameInput]::Focus($hwnd)) {
				[void][GameInput]::SendChord($hwnd, [uint16[]]@($Scan.Enter), 80)
			}
			$lastKey = Get-Date
		}
		if ($SnapshotDir -and ((Get-Date) - $lastShot).TotalSeconds -ge 15) {
			$file = Join-Path $SnapshotDir ('{0:D2}_{1:D3}s.png' -f $shots, [int]((Get-Date) - $started).TotalSeconds)
			if ([GameInput]::Snapshot($hwnd, $file)) { $shots++ }
			$lastShot = Get-Date
		}
	}
	Start-Sleep -Milliseconds 500
}
Write-Host ("Loader heartbeat is up after {0:N0} s" -f ((Get-Date) - $started).TotalSeconds)
