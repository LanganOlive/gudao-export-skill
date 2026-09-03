"""Incremental gudao fetch for cron (11:30 / 16:00 daily by default).

For each active room (latest_message_id > 0):
1. Set __fetchId, __cutoffDate (last_run), __roomInfo in localStorage
2. Eval fetchOnePage() — first page only (200 msgs)
3. Filter date > cutoff (already done in JS)
4. Prepend new rows to existing CSV (or create new if not exists)

Updates last_run.json with the time of this run for next cron.

Configuration via env vars (all optional, with sensible defaults):
- GUDAO_WORK_DIR:    runtime data dir (last_run.json, room_id_map.json). Default: <script_dir>
- GUDAO_OUT_DIR:     CSV output directory. Default: <script_dir>/data
- GUDAO_LOG_FILE:    append log file path. Default: <script_dir>/dbg_incr.log
- GUDAO_BIN:         path to bb-browser binary. Default: 'bb-browser' (PATH)
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

CSV_DATE_SUFFIX = re.compile(r'^(.*?)_(\d{8})-(\d{8})\.csv$')

_SCRIPT_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get('GUDAO_WORK_DIR', _SCRIPT_DIR))
OUT_DIR = Path(os.environ.get('GUDAO_OUT_DIR', _SCRIPT_DIR / 'data'))
LAST_RUN_FILE = Path(os.environ.get('GUDAO_LAST_RUN', WORK_DIR / 'last_run.json'))
LOG_FILE = Path(os.environ.get('GUDAO_LOG_FILE', WORK_DIR / 'dbg_incr.log'))
BB_BROWSER = os.environ.get('GUDAO_BIN', 'bb-browser')
ROOM_ID_MAP_FILE = WORK_DIR / 'room_id_map.json'


def log(msg: str) -> None:
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(f'[{ts}] {msg}\n')


def run_browser(js: str, timeout: int = 30) -> tuple[int, bytes, bytes]:
    r = subprocess.run(
        [BB_BROWSER, 'eval', js],
        capture_output=True, shell=True, timeout=timeout,
    )
    return r.returncode, r.stdout, r.stderr


def chunked_inject(prefix: str, b64: str, chunk_size: int = 1500) -> bool:
    chunks = [b64[i:i + chunk_size] for i in range(0, len(b64), chunk_size)]
    for i, chunk in enumerate(chunks):
        js = f"localStorage.setItem('{prefix}_{i}', '{chunk}'); 'c{i}'"
        rc, out, _ = run_browser(js, timeout=10)
        if rc != 0:
            log(f'  chunk {i} rc={rc}')
            return False
    n = len(chunks)
    concat = (f"(()=>{{var s='';for(var i=0;i<{n};i++)"
              f"s+=localStorage.getItem('{prefix}_'+i);"
              f"localStorage.setItem('{prefix}', s);"
              f"return s.length;}})()")
    rc, _, _ = run_browser(concat, timeout=10)
    return rc == 0


def get_cutoff() -> str:
    """Get ISO cutoff date for fetching."""
    now = datetime.now()
    if LAST_RUN_FILE.exists():
        try:
            data = json.loads(LAST_RUN_FILE.read_text(encoding='utf-8'))
            last_run = data.get('last_run')
            if last_run:
                # Subtract 60s buffer to avoid missing in-flight messages
                return (datetime.fromisoformat(last_run) - timedelta(seconds=60)).isoformat(sep=' ')
        except Exception as e:
            log(f'last_run parse err: {e}, falling back to today 00:00')
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(sep=' ')


def get_active_rooms() -> list[dict]:
    """Fetch all rooms from gudao API; skip empty ones (latest_message_id=0).

    As of 2026-08-31 the API returns 329 rooms total (294 active, 35 empty).
    Empty rooms already have placeholder CSVs (【空】 prefix) and won't grow.
    """
    js = (
        "fetch('https://gudao.gonm2.cn/api/rooms?limit=500', "
        "{headers: {'Authorization': 'Bearer ' + localStorage.getItem('appToken')}})"
        ".then(r => r.json())"
        ".then(d => d.filter(r => (r.latest_message_id || 0) > 0))"
        ".then(d => d.map(r => ({id: r.id, name: r.name, note: r.note || '', tags: r.tags || [], latest_message_id: r.latest_message_id})))"
        ".then(d => JSON.stringify(d))"
    )
    rc, out, err = run_browser(js, timeout=30)
    if rc != 0:
        log(f'get rooms API failed rc={rc} err={err[:200]!r}')
        return []
    text = out.decode('utf-8', errors='replace').strip()
    try:
        rooms = json.loads(text)
        log(f'API returned {len(rooms)} active rooms (skipping empty)')
        return rooms
    except json.JSONDecodeError as e:
        log(f'parse rooms API err: {e} text: {text[:200]}')
        return []


def _clean(s: str) -> str:
    return str(s).replace('\\', '_').replace('/', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')


def _style_for_room(room: dict) -> str:
    tags = [t for t in (room.get('tags') or []) if t]
    return _clean(''.join(tags)) if tags else '未分类'


def _load_room_id_map() -> dict:
    p = WORK_DIR / 'room_id_map.json'
    if p.exists():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except Exception as e:
            log(f'room_id_map parse err: {e}, starting fresh')
    return {}


def _save_room_id_map(m: dict) -> None:
    (WORK_DIR / 'room_id_map.json').write_text(
        json.dumps(m, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _rename_basename(csv_path: Path, new_basename: str) -> Path:
    """Rename CSV preserving the _YYYYMMDD-YYYYMMDD.csv suffix.

    Used when a room's name (or tag-derived style) changes: the historical
    CSV must be re-anchored to the new basename so future prepends land on it.
    Returns the final Path. Skips if target already exists (no clobber).
    """
    m = CSV_DATE_SUFFIX.match(csv_path.name)
    if not m:
        return csv_path
    _, start, end = m.group(1), m.group(2), m.group(3)
    new_name = f'{new_basename}_{start}-{end}.csv'
    new_path = csv_path.parent / new_name
    if new_path == csv_path:
        return csv_path
    if new_path.exists():
        log(f'  WARN: rename target {new_name} already exists, skipping')
        return csv_path
    csv_path.rename(new_path)
    return new_path


def csv_path_for_room(room: dict, id_map: dict) -> Path:
    """Find this room's CSV, handling renames.

    The basename first part is the channel's `note` (user-set 频道备注 on the
    gudao web UI). If note is empty/whitespace, fall back to `name` so the
    88% of rooms without a note still resolve.

    Resolution order:
    1. Glob with current `note_style` or `name_style` — direct hit
    2. If miss, fall back to id_map[room_id] historical basename
       (covers: room renamed, OR user added/cleared a note after first run)
    3. If miss, fall back to `name_style` (raw name, no note)
       (covers: legacy CSVs from before note-based naming was introduced;
       rename to note-based basename if found)
    4. No match anywhere — create new CSV with today's date

    Always updates id_map[room_id] = current basename.
    """
    rid = str(room['id'])
    note_raw = (room.get('note') or '').strip()
    note = _clean(note_raw) if note_raw else ''
    name = _clean(room['name'])
    style = _style_for_room(room)
    # note takes priority, falls back to name if empty
    head = note if note else name
    full_clean = f'{head}_{style}'
    name_based = f'{name}_{style}'

    def _glob_for(basename: str) -> list[Path]:
        return [
            f for f in sorted(OUT_DIR.glob(f'{basename}_*-*.csv'))
            if not f.name.startswith('【空】')
        ]

    # 1. Direct hit on current note-or-name based basename
    matches = _glob_for(full_clean)
    if matches:
        id_map[rid] = full_clean
        return matches[0]

    # 2. id_map historical (room renamed or note changed since last run)
    historical = id_map.get(rid)
    if historical and historical != full_clean:
        hist_matches = _glob_for(historical)
        if hist_matches:
            csv_path = hist_matches[0]
            new_path = _rename_basename(csv_path, full_clean)
            log(f'  room renamed: {historical} -> {full_clean} ({csv_path.name} -> {new_path.name})')
            id_map[rid] = full_clean
            return new_path

    # 3. Raw name-based fallback (legacy CSV from before note-based naming)
    #    Uses loose glob `{name}_*-*.csv` because legacy CSVs may have been
    #    generated by an older version that joined tags differently (e.g.
    #    with `_` separators vs current `''`). The exact style in the glob
    #    would miss these.
    #    Only triggers when current is note-based AND id_map is empty for this id.
    if note and name_based != full_clean and rid not in id_map:
        loose_glob = list(OUT_DIR.glob(f'{name}_*-*.csv'))
        loose_matches = [
            f for f in sorted(loose_glob)
            if not f.name.startswith('【空】') and f.name.startswith(f'{name}_')
        ]
        if loose_matches:
            csv_path = loose_matches[0]
            new_path = _rename_basename(csv_path, full_clean)
            log(f'  legacy rename (name->note): {csv_path.name} -> {new_path.name}')
            id_map[rid] = full_clean
            return new_path

    # 4. Brand new CSV
    today = datetime.now().strftime('%Y%m%d')
    id_map[rid] = full_clean
    return OUT_DIR / f'{full_clean}_{today}-{today}.csv'


def prepend_to_csv(csv_path: Path, new_b64_csv: str) -> int:
    """Prepend new rows to existing CSV (skip header of existing)."""
    new_csv_bytes = base64.b64decode(new_b64_csv)
    new_text = new_csv_bytes.decode('utf-8', errors='replace')
    # Strip BOM that JS-side CSV builder prepends — otherwise it ends up
    # embedded in the first prepended row.
    if new_text.startswith('\ufeff'):
        new_text = new_text[1:]
    new_lines = [line for line in new_text.split('\r\n') if line]
    if not new_lines:
        return 0

    if not csv_path.exists():
        # Write new file with header + data
        header = '"日期时间","涉及股票","涉及决策","","消息总结","消息里面包含的时间","消息里面有说的盈利或者亏损","消息内容"'
        content = header + '\r\n' + '\r\n'.join(new_lines) + '\r\n'
        csv_path.write_bytes(('\ufeff' + content).encode('utf-8'))
        return len(new_lines)

    # Read existing
    existing = csv_path.read_text(encoding='utf-8-sig')
    existing_lines = [line for line in existing.splitlines() if line]
    if not existing_lines:
        return 0

    # Existing: [header, data1, data2, ...] (newest first)
    header = existing_lines[0]
    # Insert new lines after header (keeping newest-first order)
    merged = [header] + new_lines + existing_lines[1:]
    content = '\r\n'.join(merged) + '\r\n'
    csv_path.write_bytes(('\ufeff' + content).encode('utf-8'))
    return len(new_lines)


def rename_csv_for_newer_end(csv_path: Path, newest_iso: str) -> Path:
    """If the newest message date is later than the CSV filename's end-date,
    rename the file so the end-date reflects reality.

    Filename pattern: {name}_{style}_{YYYYMMDD}-{YYYYMMDD}.csv
    Only the trailing end-date is updated; start-date stays anchored to the
    earliest known message in the file (which is the original creation date
    unless a one-shot export had a different range).

    Returns the final Path (may equal csv_path if no rename was needed).
    Atomic on the same filesystem (uses Path.rename).
    """
    if not newest_iso or len(newest_iso) < 10:
        return csv_path
    m = CSV_DATE_SUFFIX.match(csv_path.name)
    if not m:
        return csv_path
    prefix, start_str, end_str = m.group(1), m.group(2), m.group(3)
    newest_date_str = newest_iso[:10].replace('-', '')
    if not (len(newest_date_str) == 8 and newest_date_str.isdigit()):
        return csv_path
    if newest_date_str <= end_str:
        return csv_path  # filename already covers the newest message
    new_name = f'{prefix}_{start_str}-{newest_date_str}.csv'
    new_path = csv_path.parent / new_name
    if new_path.exists() and new_path != csv_path:
        # Avoid clobbering an existing file (shouldn't happen in normal cron)
        log(f'  WARN: rename target {new_name} already exists, skipping')
        return csv_path
    csv_path.rename(new_path)
    return new_path


def main() -> int:
    LOG_FILE.write_text('', encoding='utf-8')
    log('=== Incremental fetch start ===')

    id_map = _load_room_id_map()
    log(f'room_id_map loaded ({len(id_map)} entries)')

    cutoff = get_cutoff()
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    log(f'Cutoff: {cutoff}, now: {now}')

    # Pre-check: verify appToken is in localStorage before doing any work
    token_probe_js = (
        "(()=>{const t=localStorage.getItem('appToken');"
        "return t?'OK:'+t.slice(0,20):'NULL';})()"
    )
    token_rc, token_out, _ = run_browser(token_probe_js, timeout=10)
    token_val = token_out.decode('utf-8', errors='replace').strip() if token_out else ''
    if token_rc != 0 or not token_val.startswith('OK:'):
        log(f'PRECHECK FAILED: appToken missing in localStorage (rc={token_rc}, val={token_val[:80]!r})')
        log('ACTION NEEDED: gudao session expired — user must re-login at https://gudao.gonm2.cn/login')
        log('STEPS: 1) ensure current tab is gudao.gonm2.cn/login, 2) Chrome auto-fills username+password,')
        log('       3) enter captcha manually, 4) submit, 5) next cron will retry automatically')
        log('TIP: do NOT kill Chrome — daemon/page are healthy, only the gudao token is gone')
        return 2
    log(f'Token OK (prefix: {token_val[3:]}...)')

    # Inject fetchOnePage function
    js_bytes = (WORK_DIR / 'incremental_fetch.js').read_bytes()
    log(f'Injecting incremental_fetch.js ({len(js_bytes)} bytes, b64={len(base64.b64encode(js_bytes))})')
    if not chunked_inject('__onePage', base64.b64encode(js_bytes).decode('ascii')):
        log('FAILED to inject script')
        return 1

    n_chunks = (len(base64.b64encode(js_bytes).decode('ascii')) + 1499) // 1500

    # Get active rooms
    rooms = get_active_rooms()
    log(f'Active rooms (pinned with messages): {len(rooms)}')

    total_new_rows = 0
    success_count = 0
    skip_count = 0
    err_count = 0
    for idx, room in enumerate(rooms, 1):
        rid = room['id']
        name = room['name']

        # Set localStorage
        room_json = json.dumps(room, ensure_ascii=False)
        setup_js = (
            f"localStorage.setItem('__fetchId','{rid}');"
            f"localStorage.setItem('__cutoffDate','{cutoff}');"
            f"localStorage.setItem('__roomInfo', JSON.stringify({room_json}));"
            f"'setup ok'"
        )
        rc, _, _ = run_browser(setup_js, timeout=10)
        if rc != 0:
            log(f'[{idx}/{len(rooms)}] {rid} {name}: setup failed rc={rc}')
            err_count += 1
            continue

        # Eval fetchOnePage() — load + run
        eval_js = (
            f"(()=>{{var s='';for(var i=0;i<{n_chunks};i++)"
            f"s+=localStorage.getItem('__onePage_'+i);"
            f"return eval(atob(s));}})()"
        )
        try:
            rc, out, _ = run_browser(eval_js, timeout=30)
        except subprocess.TimeoutExpired:
            log(f'[{idx}/{len(rooms)}] {rid} {name}: TIMEOUT')
            err_count += 1
            continue

        if rc != 0:
            log(f'[{idx}/{len(rooms)}] {rid} {name}: eval rc={rc}')
            err_count += 1
            continue

        text = out.decode('utf-8', errors='replace').strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            log(f'[{idx}/{len(rooms)}] {rid} {name}: parse err: {text[:200]}')
            err_count += 1
            continue

        if not result.get('ok'):
            reason = result.get('reason', 'unknown')
            log(f'[{idx}/{len(rooms)}] {rid} {name}: SKIP ({reason})')
            skip_count += 1
            # Still resolve CSV path so note-based rename happens even when
            # the room has no new data (id_map update + legacy rename).
            csv_path_for_room(room, id_map)
            continue

        # Prepend to CSV
        csv_path = csv_path_for_room(room, id_map)
        added = prepend_to_csv(csv_path, result['b64'])
        final_path = rename_csv_for_newer_end(csv_path, result.get('newest', ''))
        renamed = final_path.name != csv_path.name
        log(f'[{idx}/{len(rooms)}] {rid} {name}: +{added} rows -> {final_path.name} (newest: {result.get("newest")})' + (' [renamed]' if renamed else ''))
        total_new_rows += added
        success_count += 1

    log(f'=== Done. Success: {success_count}, Skip: {skip_count}, Err: {err_count}, Total new rows: {total_new_rows} ===')
    _save_room_id_map(id_map)
    log(f'room_id_map saved ({len(id_map)} entries)')

    # Update last_run
    LAST_RUN_FILE.write_text(
        json.dumps({'last_run': now}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    log(f'Updated last_run to {now}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
