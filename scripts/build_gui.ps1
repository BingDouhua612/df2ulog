# Build the df2ulog GUI as a Windows onedir PyInstaller application and smoke-test it.
#
# Usage:
#   .\scripts\build_gui.ps1
#   .\scripts\build_gui.ps1 -SmokeLog D:\logs\flight_01.BIN
#
# NOTE: Start-Process -Wait is required for GUI-subsystem exes; a bare `& exe`
# call does not wait, so the smoke checks would race the running process.
param(
    [string]$SmokeLog = ""
)

$ErrorActionPreference = 'Stop'
$R = Split-Path -Parent $PSScriptRoot
Set-Location $R
$PY = Join-Path $R '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PY)) {
    $PY = 'python'
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
New-Item -ItemType Directory -Force out | Out-Null

Write-Host "=== PyInstaller build (onedir) ==="
& $PY -m PyInstaller `
    --noconfirm --clean --onedir --windowed `
    --name df2ulog-gui `
    --collect-all pymavlink `
    --collect-all pyulog `
    --hidden-import pymavlink.DFReader `
    --icon "$R\src\df2ulog\gui\assets\df2ulog.ico" `
    --add-data "$R\src\df2ulog\gui\assets;df2ulog/gui/assets" `
    --paths "$R\src" `
    "$R\packaging\gui_launcher.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed: exit $LASTEXITCODE" }

$exe = "$R\dist\df2ulog-gui\df2ulog-gui.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "build failed: $exe not found" }
$distSize = (Get-ChildItem -LiteralPath "$R\dist\df2ulog-gui" -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("built: {0} ({1:N1} MB onedir)" -f $exe, ($distSize / 1MB))

function Invoke-Packaged([string]$argLine, [int]$timeoutSeconds = 180) {
    $proc = Start-Process -FilePath $exe -ArgumentList $argLine -PassThru -WindowStyle Hidden
    if (-not $proc.WaitForExit($timeoutSeconds * 1000)) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        throw "packaged process timed out after $timeoutSeconds s: $argLine"
    }
    return $proc.ExitCode
}

Write-Host "=== smoke: --version ==="
$code = Invoke-Packaged '--version' 60
Write-Host "version exit=$code"
if ($code -ne 0) { throw "packaged --version failed: exit $code" }

if ($SmokeLog) {
    if (-not (Test-Path -LiteralPath $SmokeLog)) { throw "SmokeLog not found: $SmokeLog" }
    Write-Host "=== smoke: --selftest on $SmokeLog (first run can take a while) ==="
    $smokeOut = Join-Path $R 'out\packaged_smoke'
    New-Item -ItemType Directory -Force $smokeOut | Out-Null
    Get-ChildItem -LiteralPath $smokeOut -File -ErrorAction SilentlyContinue | Remove-Item -Force
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $code = Invoke-Packaged ("--selftest `"$SmokeLog`" -o `"$smokeOut`"") 600
    $sw.Stop()
    Write-Host ("selftest exit={0} elapsed={1:N1}s" -f $code, $sw.Elapsed.TotalSeconds)
    if ($code -ne 0) { throw "packaged --selftest failed: exit $code" }
    $expected = Join-Path $smokeOut ([System.IO.Path]::GetFileNameWithoutExtension($SmokeLog) + '.ulg')
    if (-not (Test-Path -LiteralPath $expected)) { throw "packaged selftest produced no .ulg at $expected" }
    $producedInfo = Get-Item -LiteralPath $expected
    Write-Host "produced: $($producedInfo.Name) $($producedInfo.Length) B"
} else {
    Write-Host "=== smoke: --selftest skipped (pass -SmokeLog <path to a real .BIN/.log> to enable) ==="
}

Write-Host "=== smoke: packaged GUI starts (offscreen, 8 s then terminated) ==="
$env:QT_QPA_PLATFORM = 'offscreen'
$guiProc = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 8
$alive = -not $guiProc.HasExited
if ($alive) { Stop-Process -Id $guiProc.Id -Force -ErrorAction SilentlyContinue }
Remove-Item Env:\QT_QPA_PLATFORM -ErrorAction SilentlyContinue
if (-not $alive) { throw "packaged GUI exited unexpectedly (code $($guiProc.ExitCode))" }
Write-Host "GUI process started and stayed alive for 8 s"

Write-Host "PACKAGING SMOKE PASS: $exe"
exit 0
