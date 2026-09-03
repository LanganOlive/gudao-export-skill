---
name: gudao-export
description: "Fetch & auto-maintain local CSV archives from gudao.gonm2.cn stock-advisory rooms via bb-browser. Trigger when user mentions gudao/古道 export, room CSV updates, token expiry, bb-browser hang, cron wrapper failures, or asks to run a one-off / scheduled incremental fetch."
---

# gudao-export

Incremental CSV scraper for the gudao.gonm2.cn stock-advisory rooms, designed to
run unattended under Windows Task Scheduler. Built on bb-browser (Playwright
wrapper that talks to a long-lived Chrome over the DevTools protocol at
127.0.0.1:19825).

Two scripts cooperate:

- `scripts/incremental_fetch.py` — main fetcher. For each active room, sets
  `__fetchId` / `__cutoffDate` / `__roomInfo` in `localStorage`, evals
  `fetchOnePage()` (the JS payload lives in `scripts/incremental_fetch.js`),
  prepends the new CSV rows, and auto-renames the file so its end-date tracks
  the latest message.
- `scripts/run_incremental_fetch.ps1` — PowerShell wrapper called by Task
  Scheduler. Detects Python, invokes the fetcher, captures stdout into a
  diagnostic log so cron failures are observable (Task Scheduler does NOT
  capture child stdout by default).
- `scripts/auto_relogin.py` — when when appToken has expired, navigates to the
  login page, extracts the captcha PNG, prompts (stdin) for the 4 digits,
  fills username + password + captcha and clicks submit. Designed to be
  driven by an LLM agent that can read PNG via the Read tool.
- `scripts/fix_csv_corruption.py` + `fix_mojibake_headers.py` — one-shot
  repair utilities for legacy CSVs (embedded BOMs, stray CRLFs, double-UTF-8
  headers).

## When to invoke

Trigger phrases (any of):

- "更新全部频道" / "跑一下增量抓取" / "fetch gudao now"
- "gudao token 过期了,登录一下" / "auto relogin"
- "fix the CSV header" / "fix mojibake"
- "set up the gudao cron job" / "register the task scheduler entries"

## Configuration

All paths and binaries are env-var configurable. Defaults are sensible for the
reference deployment (Windows + PowerShell + bb-browser on PATH).

| Env var | Default | Purpose |
|---|---|---|
| `GUDAO_WORK_DIR` | `<script_dir>` | runtime data dir (`last_run.json`, `room_id_map.json`) |
| `GUDAO_OUT_DIR` | `<script_dir>/data` | CSV output directory |
| `GUDAO_LOG_FILE` | `<work_dir>/dbg_incr.log` | append log written by fetcher |
| `GUDAO_WRAPPER_LOG` | `<work_dir>/dbg_cron_wrapper.log` | PS wrapper diagnostic log |
| `GUDAO_BIN` | `bb-browser` | bb-browser binary name or full path |
| `GUDAO_PYTHON` | auto-detect | python executable used by PS wrapper |
| `GUDAO_USERNAME` / `GUDAO_PASSWORD` | empty | creds for auto_relogin.py |
| `GUDAO_CAPTCHA_OUT` | `<tmp>/gudao_captcha.png` | where auto_relogin writes the captcha PNG |

## How a fetch runs

1. Wrapper script detects Python, calls `incremental_fetch.py`.
2. Fetcher runs a **pre-check**: `bb-browser eval "localStorage.getItem('appToken')"`.
   If token is missing, exit code 2 with a clear log line telling the operator
   how to relogin. last_run.json is NOT updated so the next successful run
   picks up where this run left off.
3. If token is present, inject `incremental_fetch.js` (base64-chunked into
   `localStorage` under `__onePage_0..N` then concatenated and `eval`'d).
4. API list of 329 rooms. Filter to 294 active (`latest_message_id > 0`).
5. For each active room: set `__fetchId/__cutoffDate/__roomInfo`, eval
   `fetchOnePage()`, prepend to CSV, rename file if newest date > current end.

A typical 294-room pass takes ~7–10 minutes on the reference machine.

## Failure modes & recovery

- **Exit 1 (`chunk N rc=1`)** — bb-browser eval timed out → Chrome render
  thread idle-hang. Fix: `bb-browser daemon shutdown && bb-browser tab list`;
  if eval still times out, `taskkill //F //IM chrome.exe` then restart Chrome
  with `--remote-debugging-port=19825 --user-data-dir=<user-data-dir>`.
- **Exit 2 (PRECHECK FAILED)** — appToken missing in localStorage. gudao
  cleared it after the session expired. Fix: run `python auto_relogin.py -u
  <user> -p <pass>` (the script extracts the captcha PNG; agent reads it via
  Read tool and types the 4 digits).
- **exit 2 (`FATAL: no python`)** — set `GUDAO_PYTHON=C:\path\to\python.exe`.
- **CSV append loops (`| | ` double-separator)** — should never happen on a
  fresh deployment; legacy CSVs may need `fix_csv_corruption.py` once.

## References

- `references/cron-setup.md` — Task Scheduler registration commands (the 6
  daily schedules used on the reference deployment: 11:30 / 13:00 / 14:40 /
  16:00 / 19:50 / 23:50).
- `references/troubleshooting.md` — full diagnostic tree for `dbg_incr.log`
  patterns, with the difference between "page hang" and "session expiry".
- `references/csv-schema.md` — column layout, naming conventions, and the
  rename-on-newer-end rule.

## License

MIT.