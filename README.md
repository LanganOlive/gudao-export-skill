# gudao-export

Incremental CSV scraper for the gudao.gonm2.cn stock-advisory rooms, packaged
as a Claude Code skill. Runs unattended under Windows Task Scheduler and
auto-recovers from common failure modes (Chrome hang, session expiry).

## Layout

```
gudao-export-skill/
├── SKILL.md                       # entry point — agent reads this first
├── README.md                      # this file
├── scripts/
│   ├── incremental_fetch.py       # main fetcher (called by cron)
│   ├── incremental_fetch.js       # injected into Chrome page (fetchOnePage)
│   ├── run_incremental_fetch.ps1  # PowerShell wrapper for Task Scheduler
│   ├── auto_relogin.py            # relogin when appToken has expired
│   ├── fix_csv_corruption.py      # one-shot BOM/CRLF repair
│   └── fix_mojibake_headers.py    # one-shot double-UTF-8 header repair
└── references/
    ├── cron-setup.md              # Task Scheduler registration
    ├── troubleshooting.md         # diagnostic tree
    └── csv-schema.md              # column layout + filename rules
```

## Quick start (Windows)

1. Install **bb-browser** (`npm i -g bb-browser`) and ensure Chrome is
   running with `--remote-debugging-port=19825`.
2. Manually log into gudao once in that Chrome so `appToken` is written to
   `localStorage`:
   `bb-browser open https://gudao.gonm2.cn && bb-browser eval "localStorage.getItem('appToken')"`
3. (Optional) Set environment variables to override defaults — see
   `SKILL.md` table.
5. Run a one-off fetch:
   `python scripts\incremental_fetch.py`
6. Register the cron schedules: see `references/cron-setup.md`.

## How agent invocation works

This repo is structured to be loaded by Claude Code (or another LLM agent
that supports the `Skill` tool). When the user says anything matching the
trigger phrases in `SKILL.md`'s `description:` frontmatter, the agent reads
`SKILL.md`, follows the configuration table, and runs the scripts in the
documented order.

The `auto_relogin.py` script intentionally relies on an external vision
step — it writes a PNG captcha and waits on stdin for the 4-digit answer,
which the agent provides after reading the PNG via the Read tool. This
keeps the script dependency-free and works with any multimodal LLM.

## License

MIT.