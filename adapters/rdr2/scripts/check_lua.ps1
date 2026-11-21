# Compile-checks every Lua file under adapters\*\lua\ with the LuaJIT that RedLua ships
# (lua51.dll in the game folder). Files are compiled, not run.
param(
	[string]$GameDir = 'C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dll = Join-Path $GameDir 'lua51.dll'
if (-not (Test-Path -LiteralPath $dll)) {
	throw "$dll not found. Install RedLua first, or pass -GameDir."
}

$source = @'
using System;
using System.Runtime.InteropServices;
public static class LuaCheck {
    const string Dll = @"__DLL__";
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)] static extern IntPtr luaL_newstate();
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl, CharSet = CharSet.Ansi)] static extern int luaL_loadfile(IntPtr L, string filename);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)] static extern IntPtr lua_tolstring(IntPtr L, int idx, IntPtr len);
    [DllImport(Dll, CallingConvention = CallingConvention.Cdecl)] static extern void lua_close(IntPtr L);
    public static string Check(string path) {
        IntPtr L = luaL_newstate();
        int rc = luaL_loadfile(L, path);
        string msg = rc == 0 ? null : Marshal.PtrToStringAnsi(lua_tolstring(L, -1, IntPtr.Zero));
        lua_close(L);
        return msg;
    }
}
'@
Add-Type -TypeDefinition $source.Replace('__DLL__', $dll)

$failed = 0
# every adapter's Lua (RDR2's, the shared loader in adapters\common, other RedLua games)
$adapters = Split-Path -Parent $root
Get-ChildItem -LiteralPath $adapters -Directory | ForEach-Object { Join-Path $_.FullName 'lua' } | Where-Object { Test-Path -LiteralPath $_ } |
	ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter '*.lua' -Recurse } | ForEach-Object {
	$err = [LuaCheck]::Check($_.FullName)
	$rel = $_.FullName.Substring($adapters.Length + 1)
	if ($err) {
		$failed++
		Write-Host "FAIL  $rel"
		Write-Host "      $err"
	}
	else {
		Write-Host "ok    $rel"
	}
}
if ($failed -gt 0) { exit 1 }
