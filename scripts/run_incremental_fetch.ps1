# Cron wrapper for incremental gudao fetch.
# Scheduled by Windows Task Scheduler (default: 11:30, 16:00 daily).
#
# Configuration via env vars (all optional):
#   GUDAO_WORK_DIR       — script/data dir (default: directory of this .ps1)
#   GUDAO_WRAPPER_LOG    — wrapper diagnostic log path (default: <work_dir>/dbg_cron_wrapper.log)
#   GUDAO_PYTHON         — python executable (default: auto-detect py/python3/python)

$ErrorActionPreference = 'Continue'

# Resolve work dir from this script's location
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if ($env:GUDAO_WORK_DIR) { $workDir = $env:GUDAO_WORK_DIR } else { $workDir = $ScriptDir }
Set-Location $workDir

$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
if ($env:GUDAO_WRAPPER_LOG) { $wrapperLog = $env:GUDAO_WRAPPER_LOG } else { $wrapperLog = Join-Path $workDir 'dbg_cron_wrapper.log' }
"[$stamp] cron fetch starting" | Out-File -Append $wrapperLog -Encoding utf8
"[$stamp] cwd: $PWD" | Out-File -Append $wrapperLog -Encoding utf8
"[$stamp] USER: $env:USERNAME  SESSION: $env:SESSIONNAME" | Out-File -Append $wrapperLog -Encoding utf8

# Pick a Python interpreter
if ($env:GUDAO_PYTHON) {
    $pythonExe = $env:GUDAO_PYTHON
} else {
    $candidates = @('py', 'python', 'python3', "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")
    $pythonExe = $null
    foreach ($c in $candidates) {
        try {
            $cmd = Get-Command $c -ErrorAction Stop
            $pythonExe = $cmd.Source
            break
        } catch { }
    }
}

if (-not $pythonExe) {
    "[$stamp] FATAL: no python executable found (set GUDAO_PYTHON)" | Out-File -Append $wrapperLog -Encoding utf8
    exit 2
}
"[$stamp] using python: $pythonExe" | Out-File -Append $wrapperLog -Encoding utf8

$scriptPath = Join-Path $workDir 'incremental_fetch.py'
if (-not (Test-Path $scriptPath)) {
    "[$stamp] FATAL: $scriptPath not found" | Out-File -Append $wrapperLog -Encoding utf8
    exit 3
}

try {
    & $pythonExe $scriptPath 2>&1 | Out-File -Append $wrapperLog -Encoding utf8
    $rc = $LASTEXITCODE
} catch {
    "[$stamp] python exec error: $_" | Out-File -Append $wrapperLog -Encoding utf8
    $rc = 1
}

$endStamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
if ($rc -eq 0) {
    "[$endStamp] cron fetch OK (rc=$rc)" | Out-File -Append $wrapperLog -Encoding utf8
} else {
    "[$endStamp] cron fetch FAILED (rc=$rc)" | Out-File -Append $wrapperLog -Encoding utf8
}
exit $rc