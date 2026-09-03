# CSV schema and naming

The scraper writes one CSV per gudao room into `GUDAO_OUT_DIR`. Both schema
and naming have non-obvious rules that emerged from bug-fix iterations; this
file documents them so future readers don't have to re-discover them.

## Column layout

UTF-8 with BOM (`\ufeff` prefix on the first byte). 8 columns:

| # | Header | Source | Notes |
|---|---|---|---|
| 1 | 日期时间 | `m.created_at` | ISO8601 string from gudao API. The first 10 chars are the day key. |
| 2 | 涉及股票 | (always empty) | gudao's API doesn't populate this. |
| 3 | 涉及决策 | (always empty) | same. |
| 4 | (empty) | (always empty) | legacy column. |
| 5 | 消息总结 | first line of `m.full_content` (truncated to 180 chars) | AI-generated summary. |
| 6 | 消息里面包含的时间 | `|`-joined distinct date fragments extracted by regex `\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b` and `\b\d{1,2}[/-]\d{1,2}\b`. |
| 7 | 消息里面有说的盈利或者亏损 | (always empty) | gudao's API doesn't populate this. |
| 8 | 消息内容 | `m.full_content`, `\r\n` flattened to spaces, `"` doubled for CSV escape | The raw message body. |

The `涉及股票` and `涉及决策` columns are intentionally left blank by the
fetcher — they're not in gudao's API response. Downstream tooling must
extract tickers and decisions from columns 5/8 instead.

## Filename rules

`{name|note}_{style}_{YYYYMMDD}-{YYYYMMDD}.csv`

- `name|note` — the room's `name` field, falling back to its `note` field
  if set (gudao users can set a per-room note for the UI; the note is the
  preferred display name).
- `style` — the room's `tags` (comma-joined). Sanitized: illegal chars
  (`/`, `:`, `*`, `?`, `"`, `<`, `>`, `|`, `\`) stripped.
- Start/end dates are the earliest and latest message dates seen in the CSV.
  The end date auto-advances on every successful prepend.

Rooms with `latest_message_id = 0` (gudao's "empty" rooms) get a `【空】`
prefix on the filename as a visual marker that the file is expected to
remain a header-only stub until the room sees its first message.

## Renaming logic

Three layers run on every fetch:

1. **CSV path lookup** (`csv_path_for_room`):
   - Glob `name_style_*-*.csv` in OUT_DIR — exact match.
   - On miss, check `room_id_map.json` (historical basename registry) and
     rename the matching file (preserving date range) to the current
     `note-or-name_style`. Update map.
   - On full miss, create a new CSV.

2. **Prepend** (`prepend_to_csv`): decode the b64 payload from the fetcher,
 strip any embedded BOM (only the leading file BOM should survive), and
 prepend. Stray `\r\r\n` is normalized to `\r\n`.

3. **Rename on newer end** (`rename_csv_for_newer_end`): if the newest
 message date in the just-prepended batch is greater than the file's
 current end-date, atomically rename so the end-date tracks. The start
 date and the name/style portion stay put.

## Why the date suffix regex is non-greedy

`CSV_DATE_SUFFIX = re.compile(r'^(.*?)_(\d{8})-(\d{8})\.csv$')` uses `(.*?)`
non-greedy. A greedy `.*` will swallow the second `_YYYYMMDD` into the name,
producing wrong start/end splits. This is a foot-gun the v0.1 implementation
hit twice — see commit history.

## Embedded BOM caveat

`incremental_fetch.js` deliberately prepends `\ufeff` to the CSV bytes
before base64-encoding, so a fresh prepend block will *contain* an embedded
BOM at its line starts if the consumer treats the byte stream as already-
BOMed. The Python prepender strips embedded BOMs to prevent that. Legacy
files may still carry embedded BOMs — `fix_csv_corruption.py` cleans them.