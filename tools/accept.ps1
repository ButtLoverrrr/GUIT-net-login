# Final acceptance: gates + tests + e2e + screenshot + diff stat (ASCII-only to avoid PS 5.1 codepage issues)
param(
  [switch]$SkipShot,
  [switch]$SkipTests,
  [switch]$SkipE2E
)
$ErrorActionPreference = 'Continue'
$ROOT = '<本机路径>'
$PROJ = '<本机路径>'
$PY = Join-Path $ROOT 'tools\py313\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
$env:TCL_LIBRARY = Join-Path $ROOT 'tools\py313\_tcl_data'
$env:TK_LIBRARY = Join-Path $ROOT 'tools\py313\_tk_data'
$env:GUIT_INSTANCE_PORT = '47941'
$log = Join-Path $ROOT 'dis\accept.txt'
"=== ACCEPT $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Set-Content $log -Encoding UTF8

function Section($t) { "`n########## $t ##########" | Add-Content $log; "`n########## $t ##########" }

Section '1) FIDELITY (rebuilt source vs original bytecode in exe)'
$fid = & $PY (Join-Path $ROOT 'fidelity.py') 2>&1
$fid | Add-Content $log
$fid | Select-String -Pattern 'total|### ' -SimpleMatch:$false

if (-not $SkipTests) {
  Section '2) TESTS (backend + gui + layout + instance + silent + perf)'
  Push-Location $PROJ
  $t = & $PY 'tests\run_tests.py' 'all' 2>&1
  Pop-Location
  $t | Add-Content $log
  $t | Select-String -Pattern 'PASS|FAIL|perf|items'
}

if (-not $SkipE2E) {
  Section '3) E2E (real HTTP + real ddddocr + mock portal, in-process)'
  $e = & $PY (Join-Path $ROOT 'e2e_ocr.py') $PROJ '--lenient' 2>&1
  $e | Add-Content $log
  $e | Select-String -Pattern 'E2E '

  Section '3b) E2E (real frozen exe vs mock portal)'
  $e2 = & $PY (Join-Path $ROOT 'e2e_probe.py') 'exe' 'lenient' 2>&1
  $e2 | Add-Content $log
  $e2 | Select-String -Pattern 'exe result|SUMMARY|REQUESTS'
}

if (-not $SkipShot) {
  Section '4) UI SCREENSHOT (DPI-aware capture)'
  $shot = Join-Path $PROJ 'docs\ui_final.png'
  $r = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ROOT 'shot.ps1') `
        -Exe $PY -Args (Join-Path $PROJ 'app.py') -WorkingDirectory $PROJ `
        -Out $shot -WaitMs 25000 -ShotDelayMs 3000 2>&1
  $r | Add-Content $log
  $r
}

Section '5) DIFF STAT (vs as-decompiled baseline)'
Push-Location $PROJ
(git diff --stat HEAD) | Add-Content $log
(git diff --stat HEAD)
Pop-Location

"`nlog: $log" | Add-Content $log
Write-Output "`nlog: $log"
