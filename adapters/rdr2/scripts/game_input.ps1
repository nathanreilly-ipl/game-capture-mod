# Shared helpers for driving the game window from outside. Dot-source this file.
# Keys are only ever sent while the game window is the foreground window, so a
# key press can never land in another application.

$script:GameDirDefault = 'C:\Program Files (x86)\Steam\steamapps\common\Red Dead Redemption 2'
$script:CaptureDirDefault = Join-Path $env:USERPROFILE 'Documents\RDR2Modding\captures'

if (-not ('GameInput' -as [type])) {
	Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public static class GameInput
{
    delegate bool EnumProc(IntPtr hwnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr hwnd, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int cmd);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr hwnd);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr hwnd, out RECT r);
    [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);

    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT { public int dx, dy; public uint mouseData, dwFlags, time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort wVk, wScan; public uint dwFlags, time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Explicit)] struct InputUnion { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public InputUnion u; }

    const uint INPUT_KEYBOARD = 1, KEYEVENTF_KEYUP = 2, KEYEVENTF_SCANCODE = 8;

    // The game's own window (class "sgaWindow"), not RedLua's console.
    public static IntPtr FindGameWindow(int pid)
    {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr hwnd, IntPtr l) {
            uint owner; GetWindowThreadProcessId(hwnd, out owner);
            if (owner != (uint)pid || !IsWindowVisible(hwnd)) return true;
            var sb = new StringBuilder(64); GetClassName(hwnd, sb, 64);
            if (sb.ToString() == "sgaWindow") { found = hwnd; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static bool IsForeground(IntPtr hwnd) { return hwnd != IntPtr.Zero && GetForegroundWindow() == hwnd; }

    public static bool Focus(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero) return false;
        if (IsForeground(hwnd)) return true;
        if (IsIconic(hwnd)) ShowWindow(hwnd, 9);
        uint pid; uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), out pid);
        uint me = GetCurrentThreadId();
        AttachThreadInput(me, fgThread, true);
        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
        AttachThreadInput(me, fgThread, false);
        Thread.Sleep(400);
        return IsForeground(hwnd);
    }

    static INPUT Key(ushort scan, bool up)
    {
        var i = new INPUT(); i.type = INPUT_KEYBOARD;
        i.u.ki.wScan = scan; i.u.ki.dwFlags = KEYEVENTF_SCANCODE | (up ? KEYEVENTF_KEYUP : 0);
        return i;
    }

    // Presses the scan codes in order, holds them, releases in reverse order.
    // Does nothing and returns false unless hwnd is the foreground window.
    public static bool SendChord(IntPtr hwnd, ushort[] scans, int holdMs)
    {
        if (!IsForeground(hwnd)) return false;
        int size = Marshal.SizeOf(typeof(INPUT));
        foreach (ushort s in scans) { SendInput(1, new[] { Key(s, false) }, size); Thread.Sleep(30); }
        Thread.Sleep(holdMs);
        for (int k = scans.Length - 1; k >= 0; k--) { SendInput(1, new[] { Key(scans[k], true) }, size); Thread.Sleep(30); }
        return true;
    }

    // Saves a picture of the game window. Refuses unless it is the foreground window.
    public static bool Snapshot(IntPtr hwnd, string path)
    {
        RECT r;
        if (!IsForeground(hwnd) || !GetWindowRect(hwnd, out r)) return false;
        int w = r.Right - r.Left, h = r.Bottom - r.Top;
        if (w <= 0 || h <= 0) return false;
        using (var bmp = new Bitmap(w, h))
        {
            using (var g = Graphics.FromImage(bmp)) g.CopyFromScreen(r.Left, r.Top, 0, 0, new Size(w, h));
            bmp.Save(path, ImageFormat.Png);
        }
        return true;
    }
}
'@
}

# Scan codes used by the scripts.
$script:Scan = @{ Ctrl = [uint16]0x1D; R = [uint16]0x13; Enter = [uint16]0x1C; Space = [uint16]0x39; Esc = [uint16]0x01 }

function Get-GameWindow {
	$p = Get-Process RDR2 -ErrorAction SilentlyContinue | Select-Object -First 1
	if (-not $p) { return [IntPtr]::Zero }
	return [GameInput]::FindGameWindow($p.Id)
}

function Get-HeartbeatAge([string]$CaptureDir = $script:CaptureDirDefault) {
	$hb = Join-Path $CaptureDir 'heartbeat.txt'
	if (-not (Test-Path -LiteralPath $hb)) { return [double]::PositiveInfinity }
	return ((Get-Date) - (Get-Item -LiteralPath $hb).LastWriteTime).TotalSeconds
}

# Turns on RedLua's Autorun so capture_loader.lua loads without the F7 menu.
function Enable-RedLuaAutorun([string]$GameDir = $script:GameDirDefault) {
	$path = Join-Path $GameDir 'RedLua\Settings.json'
	if (-not (Test-Path -LiteralPath $path)) { return $false }
	$text = [IO.File]::ReadAllText($path)
	$new = $text -replace '("autorun"\s*:\s*)false', '${1}true'
	if ($new -ne $text) {
		[IO.File]::WriteAllText($path, $new, (New-Object System.Text.UTF8Encoding($false)))
	}
	return ($new -match '"autorun"\s*:\s*true')
}
