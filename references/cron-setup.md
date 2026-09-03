# Windows Task Scheduler registration

The reference deployment uses six daily schedules. All six run the same PS
wrapper, which uses `last_run.json` to know the only file cutoff, so multiple
runs in the same day are safe (later runs just produce SKIPs for already-
fetched data).

```powershell
# Task definition — 6 instances, one per cron time
$times = @('1130','1300','1440','1600','1950','2350')
$wrapper = 'C:\path\to\gudao-export-skill\scripts\run_incremental_fetch.ps1'
foreach ($t in $times) {
    $action = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wrapper`""
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.Substring(0,2) + ':' + $t.Substring(2,2)
    $principal = New-ScheduledTaskPrincipal `
        -LogonType Interactive -RunLevel Highest -UserId (whoami)
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask `
        -TaskName "GudaoIncrementalFetch_$t" `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Incremental gudao CSV fetch — slot $t"
}
```

The Interactive + Highest logon type is required so the daemon can reach
Chrome (Chrome refuses to accept CDP connections from Session 0).

## Verifying a run

After 12+ minutes (294 rooms × ~2 s/room = ~10 min), check:

```bash
tail -5 dbg_incr.log
# expect:
# === Done. Success: <N>, Skip: <M>, Err: 0, Total new rows: <K> ===

tail -3 dbg_cron_wrapper.log
# expect:
# [<ts>] cron fetch OK (rc=0)
```

If the wrapper log shows `FAILED (rc=1)` and the Python log shows
`chunk N rc=1`, see `troubleshooting.md#page-hang`.

If `rc=2` and `PRECHECK FAILED: appToken missing`, run
`python auto_relogin.py -u <user> -p <pass>` — the script writes the
captcha PNG to `%TEMP%\gudao_captcha.png`, prints `CAPTCHA_READY: <path>`,
and waits for the 4-digit answer on stdin.

## One-off run (outside cron)

```bash
cd C:\path\to\gudao-export-skill\scripts
python incremental_fetch.py        # ~7-10 min for 294 rooms
# or via the wrapper (matches the cron path exactly):
powershell -NoProfile -ExecutionPolicy Bypass -File run_incremental_fetch.ps1
```