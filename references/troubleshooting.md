# Troubleshooting

Diagnostic tree for the most common failure shapes.

## Quick triage

```bash
# 1. Is the daemon alive?
bb-browser tab list
# expected: "标签页列表（共 N 个，当前 #X）: <url>"

# 2. Is the page responsive (not just the daemon)?
bb-browser eval "2*3"
# expected: "6". Timeout = page JS context is hung.

# 3. Is the token present?
bb-browser eval "localStorage.getItem('appToken')"
# expected: JSON with a non-null "value" field.
```

| Step 1 | Step 2 | Step 3 | Verdict |
|---|---|---|---|
| OK | OK | OK | healthy |
| OK | OK | null | **session expired** — relogin via `auto_relogin.py` |
| OK | timeout | — | **page hang** — daemon reset (see below) |
| 503 / not connected | — | — | daemon crashed — `bb-browser daemon shutdown && bb-browser tab list` |

## Page hang recovery

bb-browser's CDP WebSocket can drop after long idles, system sleep, or
lock-screen events. Recovery steps, in order of destructiveness:

```bash
# Level 1 — daemon reset (preserves Chrome & tabs):
bb-browser daemon shutdown
bb-browser tab list           # forces daemon restart + attach

# Level 2 — kill Chrome and restart with --user-data-dir (preserves session):
bb-browser daemon stop
taskkill //F //IM chrome.exe
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --remote-debugging-port=19825 ^
    --user-data-dir="C:\Users\<user>\AppData\Local\Google\Chrome\User Data" ^
    --no-first-run --no-default-browser-check
bb-browser tab list           # tabs and login session restore automatically
```

Level 2 is destructive to Chrome state but `localStorage.appToken` and
cookies survive in the user-data-dir — gudao remains logged in.

## Session-expired recovery

If `localStorage.getItem('appToken')` returns null but `eval "2*3"` works, the
page itself is fine — only the gudao token is gone (the React/Vue client
detected expiry, redirected to `/login`, and cleared `localStorage`). Do
**not** kill Chrome.

```bash
python auto_relogin.py -u <username> -p <password>
# script prints CAPTCHA_READY: <path> and waits on stdin
# agent: read PNG via vision OCR, send 4 digits + Enter
```

Captcha recognition tips:

- The PNG is 4 digits over a sinusoidal noise line. Tesseract scores 0%.
- Vision-LLM OCR (Read tool on Claude etc.) scores ~100%.
- One captcha is good for exactly one submit attempt — `auto_relogin.py`
  extracts a fresh image on each invocation.

## Last-run state

`last_run.json` is the cutoff that gates which messages are considered new.
It only advances on success (exit 0). If a run fails (hang, relogin, etc.)
the cutoff stays put, so the next successful run covers the gap.

If you ever want to force a full re-fetch from scratch, delete
`last_run.json` (next run will use "today 00:00" as the cutoff — be aware
this may pull a large amount of history).

## Wrapper log vs Python log

Two log files, two purposes:

- `dbg_incr.log` — written by Python as it works, one line per room. Use
  this to see progress in real-time during a long run.
- `dbg_cron_wrapper.log` — written by the PS wrapper at start and end of
  the run, plus the full Python stdout/stderr. Task Scheduler does NOT
  capture child stdout by default, so this is your only view into what
  the wrapper did.

If a run appears hung for 10+ minutes with no new lines in `dbg_incr.log`
and no `cron fetch OK/FAILED` in `dbg_cron_wrapper.log`, the Python process
itself has crashed (rare; usually a TimeoutExpired becomes visible in the
wrapper log as `FAILED (rc=1)` first).