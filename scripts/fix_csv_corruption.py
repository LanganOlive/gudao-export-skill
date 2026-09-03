"""One-shot fix for pre-existing CSV corruption:
- Strip embedded BOMs (one per prepended block, mid-file)
- Strip stray \r (some files have \r\r\n between header and data instead of \r\n)

After this runs, incremental_fetch.py needs to be updated to not re-introduce these.
"""
from pathlib import Path

OUT_DIR = Path(r'C:\Users\PC\Downloads\古道导出')
LOG_FILE = Path(r'C:\tmp\dbg_corruption_fix.log')


def log(msg: str) -> None:
    import time
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(f'[{ts}] {msg}\n')


def fix_file(csv_path: Path) -> dict[str, int]:
    """Strip embedded BOMs (keep only leading) and stray \\r\\r\\n → \\r\\n.

    Returns dict of {issue: count_fixed}.
    """
    raw = csv_path.read_bytes()
    if not raw:
        return {}

    bom_count = raw.count(b'\xef\xbb\xbf')
    embedded_bom_fixed = 0
    stray_cr_fixed = 0

    # 1. Strip embedded BOMs (keep only the very first one)
    if bom_count > 1:
        # Keep first BOM, remove all subsequent ones
        head = b'\xef\xbb\xbf'
        rest = raw[3:] if raw[:3] == head else raw
        rest_clean = rest.replace(head, b'')
        new_raw = head + rest_clean
        embedded_bom_fixed = bom_count - 1
        raw = new_raw

    # 2. Replace stray \r\r\n with \r\n (occurs only between header and data
    #    in 8 pre-existing files; mid-data \\r\\r\\n is unlikely but handled too)
    if b'\r\r\n' in raw:
        new_raw = raw.replace(b'\r\r\n', b'\r\n')
        stray_cr_fixed = raw.count(b'\r\r\n') - new_raw.count(b'\r\r\n')
        raw = new_raw

    if embedded_bom_fixed or stray_cr_fixed:
        csv_path.write_bytes(raw)

    return {'embedded_bom': embedded_bom_fixed, 'stray_cr': stray_cr_fixed}


def main() -> int:
    LOG_FILE.write_text('', encoding='utf-8')
    log('=== Fix CSV corruption start ===')

    csvs = sorted([p for p in OUT_DIR.glob('*.csv') if not p.name.startswith('【空】')])
    log(f'Found {len(csvs)} CSV files (excluding 【空】)')

    totals = {'embedded_bom': 0, 'stray_cr': 0, 'files_fixed': 0}
    for csv in csvs:
        result = fix_file(csv)
        if result:
            log(f'FIXED {csv.name}: {result}')
            totals['files_fixed'] += 1
            totals['embedded_bom'] += result.get('embedded_bom', 0)
            totals['stray_cr'] += result.get('stray_cr', 0)

    log(f'=== Done. Files fixed: {totals["files_fixed"]}, embedded BOMs stripped: {totals["embedded_bom"]}, stray CRs removed: {totals["stray_cr"]} ===')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())