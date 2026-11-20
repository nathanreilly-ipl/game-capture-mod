# Runs a Lua job inside the game through capture_loader.lua and prints the result.
#   .\scripts\run_job.ps1 smoke
#   .\scripts\run_job.ps1 time_probe -TimeoutSec 120 -JobArgs @{ scale = '0' }
# The game must be in story mode with capture_loader.lua loaded in RedLua.
param(
	[Parameter(Mandatory = $true)]
	[string]$Job,                  # a name in lua\jobs (without .lua) or a path to a .lua file
	[int]$TimeoutSec = 60,
	[hashtable]$JobArgs = @{},
	[string]$OutDir = (Join-Path $env:USERPROFILE 'Documents\RDR2Modding\captures')
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$jobFile = $Job
if (-not (Test-Path -LiteralPath $jobFile)) {
	$jobFile = Join-Path $root "lua\jobs\$Job.lua"
}
if (-not (Test-Path -LiteralPath $jobFile)) {
	throw "Job not found: $Job"
}
$jobFile = (Resolve-Path -LiteralPath $jobFile).Path

# The loader rewrites heartbeat.txt about once a second while it is running.
$heartbeat = Join-Path $OutDir 'heartbeat.txt'
if (-not (Test-Path -LiteralPath $heartbeat)) {
	throw "No heartbeat in $OutDir. Load capture_loader.lua from the RedLua menu (F7)."
}
$age = ((Get-Date) - (Get-Item -LiteralPath $heartbeat).LastWriteTime).TotalSeconds
if ($age -gt 5) {
	throw ("The loader's heartbeat is {0:N0} s old. Is the game running, in the foreground and not paused?" -f $age)
}

$stem = [IO.Path]::GetFileNameWithoutExtension($jobFile) -replace '[^A-Za-z0-9_-]', '_'
$id = '{0}_{1}' -f $stem, (Get-Date -Format 'yyyyMMdd_HHmmss')

$lines = @("id=$id", "file=$jobFile", "timeout_s=$TimeoutSec")
foreach ($key in $JobArgs.Keys) {
	if ($key -notmatch '^[A-Za-z0-9_]+$') { throw "Invalid argument name: $key" }
	$lines += "$key=$($JobArgs[$key])"
}

# No byte order mark, and published by rename so the loader never reads half a file.
$noBom = New-Object System.Text.UTF8Encoding($false)
$tmp = Join-Path $OutDir 'command.tmp'
$cmd = Join-Path $OutDir 'command.txt'
[IO.File]::WriteAllText($tmp, (($lines -join "`n") + "`n"), $noBom)
Move-Item -LiteralPath $tmp -Destination $cmd -Force

$result = Join-Path $OutDir "jobs\$id\result.txt"
$deadline = (Get-Date).AddSeconds($TimeoutSec + 10)
while (-not (Test-Path -LiteralPath $result)) {
	if ((Get-Date) -gt $deadline) {
		throw "No result for $id after $($TimeoutSec + 10) s. See $OutDir\loader.log."
	}
	Start-Sleep -Milliseconds 250
}

Write-Host "--- result ($id)"
Get-Content -LiteralPath $result
$log = Join-Path $OutDir "jobs\$id\job.log"
if (Test-Path -LiteralPath $log) {
	Write-Host '--- job.log'
	Get-Content -LiteralPath $log
}
Write-Host "--- files in $OutDir\jobs\$id"
Get-ChildItem -LiteralPath (Join-Path $OutDir "jobs\$id") | ForEach-Object { '{0,12}  {1}' -f $_.Length, $_.Name }

if ((Get-Content -LiteralPath $result -Raw) -notmatch '(?m)^status=ok\s*$') { exit 1 }
