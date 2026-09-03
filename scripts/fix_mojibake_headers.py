"""Fix mojibake CSV headers in 古道导出.

Problem: 281/294 CSV files have double-UTF-8 mojibake headers. Original Chinese
chars (e.g. 日 = 0xe6 0x97 0xa5) were misread as Latin-1 chars (æ\x97¥) and
re-encoded as UTF-8 (0xc3 0xa6 0xc2 0x97 0xc2 0xa5). Some bytes don't survive
clean inverse roundtrip.

Fix: overwrite line 1 with canonical header (defined in fetch_one.js),
preserve BOM and all data lines untouched.
"""
from pathlib import Path

OUT_DIR = Path(r'C:\Users\PC\Downloads\古道导出')
LOG_FILE = Path(r'C:\tmp\dbg_mojibake_fix.log')
CANONICAL_HEADER = '日期时间,涉及股票,涉及决策,,消息总结,消息里面包含的时间,消息里面有说的盈利或者亏损,消息内容'


def log(msg: str) -> None:
    import time
    ts = time.strftime('%Y-%m-%d %H:%M:%S')
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(f'[{ts}] {msg}\n')


def is_mojibake_header(header_bytes: bytes) -> bool:
    """Detect double-UTF-8 mojibake: presence of 0xc3 followed by 0xa6/0xa9/0xa7 (æ/é/ç)."""
    return b'\xc3\xa6' in header_bytes[:30] or b'\xc3\xa9' in header_bytes[:30]


def fix_file(csv_path: Path) -> str:
    raw = csv_path.read_bytes()
    has_bom = raw[:3] == b'\xef\xbb\xbf'
    body = raw[3:] if has_bom else raw

    if b'\r\n' in body:
        idx = body.index(b'\r\n')
        sep = b'\r\n'
    elif b'\n' in body:
        idx = body.index(b'\n')
        sep = b'\n'
    else:
        return 'no-newline'

    header_bytes = body[:idx]
    rest = body[idx:]

    if not is_mojibake_header(header_bytes):
        return 'skip-clean'

    new_header = CANONICAL_HEADER.encode('utf-8')
    new_body = new_header + sep + rest[2:] if sep == b'\r\n' else new_header + sep + rest[1:]
    new_raw = (b'\xef\xbb\xbf' if has_bom else b'') + new_body
    csv_path.write_bytes(new_raw)
    return 'fixed'


def main() -> int:
    LOG_FILE.write_text('', encoding='utf-8')
    log('=== Fix mojibake headers start ===')

    csvs = sorted([p for p in OUT_DIR.glob('*.csv') if not p.name.startswith('【空】')])
    log(f'Found {len(csvs)} CSV files (excluding 【空】)')

    counts = {'fixed': 0, 'skip-clean': 0, 'no-newline': 0}
    for csv in csvs:
        result = fix_file(csv)
        counts[result] = counts.get(result, 0) + 1
        if result == 'fixed':
            log(f'FIXED: {csv.name}')
        elif result == 'no-newline':
            log(f'WARN no-newline: {csv.name}')

    log(f'=== Done. {counts} ===')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())