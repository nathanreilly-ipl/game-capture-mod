# Builds addon\ into build\<Config>\capture_mod.addon64.
# Needs Visual Studio (or Build Tools) with the "Desktop development with C++" workload.
param(
	[ValidateSet('Release', 'Debug', 'RelWithDebInfo')]
	[string]$Config = 'Release'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path -LiteralPath (Join-Path $root 'deps\reshade\include\reshade.hpp'))) {
	throw 'ReShade headers are missing. Run scripts\fetch_deps.ps1 first.'
}

# Prefer cmake on PATH, otherwise use the copy bundled with Visual Studio.
$cmake = (Get-Command cmake -ErrorAction SilentlyContinue).Source
if (-not $cmake) {
	$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
	if (Test-Path -LiteralPath $vswhere) {
		$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
		if ($vsPath) {
			$candidate = Join-Path $vsPath 'Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe'
			if (Test-Path -LiteralPath $candidate) { $cmake = $candidate }
		}
	}
}
if (-not $cmake) {
	throw 'cmake not found. Install Visual Studio Build Tools with the C++ workload (it includes CMake).'
}

$buildDir = Join-Path $root 'build'
# A build folder configured at another path (e.g. before the folder moved) cannot be reused.
$cache = Join-Path $buildDir 'CMakeCache.txt'
if (Test-Path -LiteralPath $cache) {
	$home_ = (Select-String -LiteralPath $cache -Pattern '^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$').Matches.Groups[1].Value
	if ($home_ -and ((Resolve-Path -LiteralPath $home_ -ErrorAction SilentlyContinue).Path -ne (Resolve-Path (Join-Path $root 'addon')).Path)) {
		Write-Host "Build folder was configured for $home_; reconfiguring"
		Remove-Item -LiteralPath $cache -Force
		Remove-Item -LiteralPath (Join-Path $buildDir 'CMakeFiles') -Recurse -Force -ErrorAction SilentlyContinue
	}
}
& $cmake -S (Join-Path $root 'addon') -B $buildDir -A x64
if ($LASTEXITCODE -ne 0) { throw "cmake configure failed with exit code $LASTEXITCODE" }

& $cmake --build $buildDir --config $Config
if ($LASTEXITCODE -ne 0) { throw "build failed with exit code $LASTEXITCODE" }

Write-Host "Built $(Join-Path $buildDir "$Config\capture_mod.addon64")"
