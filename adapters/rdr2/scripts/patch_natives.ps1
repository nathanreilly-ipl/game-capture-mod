# Gives RedLua proper names and parameter types for natives its database only
# lists by hash. Run with the game closed (RedLua reads natives.json at start).
# Keeps natives.json.orig next to it the first time. Safe to run again.
param(
	[string]$GameDir = 'C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2'
)

$ErrorActionPreference = 'Stop'
$path = Join-Path $GameDir 'RedLua\natives.json'
$backup = "$path.orig"
if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $path -Destination $backup }

# hash -> name, parameter type, parameter name (names and types from alloc8or's rdr3-nativedb-data)
$patches = @(
	@{ Hash = '0x5CD6A2CCE5087161'; Name = '_SET_PHOTO_MODE_EXPOSURE_LOCKED'; Type = 'BOOL'; Param = 'locked' },
	@{ Hash = '0xC8D0611D9A0CF5D3'; Name = '_CHANGE_PHOTO_MODE_EXPOSURE'; Type = 'float'; Param = 'value' },
	@{ Hash = '0x9229ED770975BD9E'; Name = '_UPDATE_PHOTO_MODE_EXPOSURE'; Type = $null; Param = $null }
)

$text = [IO.File]::ReadAllText($path)
foreach ($p in $patches) {
	$text = $text.Replace('"name": "_' + $p.Hash + '"', '"name": "' + $p.Name + '"')
	if ($p.Type) {
		# Only inside this native's entry: its single Any p0 parameter.
		$i = $text.IndexOf('"' + $p.Hash + '"')
		$j = $text.IndexOf('"return_type"', $i)
		$entry = $text.Substring($i, $j - $i)
		$fixed = $entry.Replace('"type": "Any"', '"type": "' + $p.Type + '"').Replace('"name": "p0"', '"name": "' + $p.Param + '"')
		$text = $text.Substring(0, $i) + $fixed + $text.Substring($j)
	}
}

# Must still be valid JSON.
$null = $text | ConvertFrom-Json
[IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
foreach ($p in $patches) {
	$i = $text.IndexOf('"' + $p.Hash + '"')
	Write-Host ($text.Substring($i, $text.IndexOf('"return_type"', $i) - $i) -replace '\s+', ' ')
}
