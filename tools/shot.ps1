param(
  [Parameter(Mandatory=$true)][string]$Exe,
  [string[]]$Args = @(),
  [Parameter(Mandatory=$true)][string]$Out,
  [int]$WaitMs = 6000,
  [int]$ShotDelayMs = 1500,
  [string]$WorkingDirectory = "",
  [switch]$KeepAlive
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
# 关键：截图进程必须是 DPI 感知的，否则 GetWindowRect 返回"虚拟化"坐标（高 DPI 下会截到半张图）
if (-not ('Win32Dpi' -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32Dpi {
  [DllImport("shcore.dll")] public static extern int SetProcessDpiAwareness(int value);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
}
try { [void][Win32Dpi]::SetProcessDpiAwareness(2) } catch { try { [void][Win32Dpi]::SetProcessDPIAware() } catch {} }
if (-not ('Win32Shot' -as [type])) {
  Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Win32Shot {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT r);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
}
"@
}
$env:GUIT_INSTANCE_PORT = if ($env:GUIT_INSTANCE_PORT) { $env:GUIT_INSTANCE_PORT } else { '47903' }
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$procName = [System.IO.Path]::GetFileNameWithoutExtension($Exe)
$preExisting = @(Get-Process -Name $procName -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$spArgs = @{ FilePath = $Exe; PassThru = $true }
if ($Args -and @($Args).Count -gt 0 -and @($Args)[0]) { $spArgs['ArgumentList'] = @($Args) }
if ($WorkingDirectory) { $spArgs['WorkingDirectory'] = $WorkingDirectory }
$p = Start-Process @spArgs
try {
  $deadline = (Get-Date).AddMilliseconds($WaitMs)
  $hwnd = [IntPtr]::Zero
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
    $cands = @(Get-Process -Name $procName -ErrorAction SilentlyContinue)
    foreach ($c in $cands) {
      if ($preExisting -contains $c.Id) { continue }
      $raw = 0
      try { $raw = [int64]$c.MainWindowHandle } catch { $raw = 0 }
      if ($raw -eq 0) { continue }
      $cand = [IntPtr]$raw
      $vis = $false
      try { $vis = [Win32Shot]::IsWindowVisible($cand) } catch { $vis = $false }
      if ($vis) { $hwnd = $cand; break }
    }
    if ($hwnd -ne [IntPtr]::Zero) { break }
  }
  if ($hwnd -eq [IntPtr]::Zero) { Write-Output "NO_WINDOW pid=$($p.Id)"; exit 2 }
  Start-Sleep -Milliseconds $ShotDelayMs
  $r = New-Object Win32Shot+RECT
  [void][Win32Shot]::GetWindowRect($hwnd, [ref]$r)
  $w = $r.Right - $r.Left; $h = $r.Bottom - $r.Top
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  $ok = [Win32Shot]::PrintWindow($hwnd, $hdc, 2)
  $g.ReleaseHdc($hdc)
  $g.Dispose()
  $bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output "SHOT ok=$ok pid=$($p.Id) size=${w}x${h} time_to_window_ms=$($sw.ElapsedMilliseconds) out=$Out"
} finally {
  if (-not $KeepAlive) {
    Start-Sleep -Milliseconds 300
    if (-not $p.HasExited) { $p.CloseMainWindow() | Out-Null; Start-Sleep -Milliseconds 800 }
    foreach ($c in @(Get-Process -Name $procName -ErrorAction SilentlyContinue)) {
      if ($preExisting -contains $c.Id) { continue }
      try { if (-not $c.HasExited) { $c.Kill() } } catch {}
    }
    Start-Sleep -Milliseconds 400
    foreach ($c in @(Get-Process -Name $procName -ErrorAction SilentlyContinue)) {
      if ($preExisting -contains $c.Id) { continue }
      try { $c.Kill() } catch {}
    }
  }
}
