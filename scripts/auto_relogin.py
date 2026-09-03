"""Auto-relogin to gudao when appToken has expired.

Detects session expiry via `localStorage.getItem('appToken') == null`,
navigates to the login page, extracts the captcha image, prompts for the
4-digit captcha via stdin, and verifies a new token is written.

Designed to be called by an LLM agent (Claude etc.) that can read PNG images
via the Read tool. The agent is expected to:

  1. Run this script and read its printed captcha PNG path.
  2. Read the PNG (multimodal vision), extract the 4 digits.
  3. Send the digits back to this script's stdin, ending with EOF (Ctrl-Z /
     Ctrl-D depending on platform).

Configuration via env vars:
- GUDAO_BIN:           bb-browser binary (default: 'bb-browser')
- GUDAO_CAPTCHA_OUT:   where to write the captcha PNG (default: <tmp>/gudao_captcha.png)
- GUDAO_USERNAME:      login username (default: empty — agent must provide via -u)
- GUDAO_PASSWORD:      login password (default: empty — agent must provide via -p)
"""
import argparse
import base64
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BB_BROWSER = os.environ.get('GUDAO_BIN', 'bb-browser')


def bb_eval(js: str, timeout: int = 15) -> tuple[int, str]:
    """Run a JS expression via bb-browser eval. Returns (rc, stdout_text)."""
    r = subprocess.run(
        [BB_BROWSER, 'eval', js],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout or '').strip()


def probe_token() -> str | None:
    """Return current appToken or None if missing/empty."""
    rc, out = bb_eval("localStorage.getItem('appToken')")
    if rc != 0 or not out or '"value":null' in out or '"value":""' in out:
        return None
    # bb-browser eval returns JSON like {"type":"string","value":"eyJ..."}
    try:
        import json
        j = json.loads(out)
        v = j.get('value')
        return v if isinstance(v, str) and v else None
    except Exception:
        return None


def navigate_to_login() -> bool:
    """Force-reload the page so it's on /login. Returns True if URL is /login."""
    bb_eval("location.reload()", timeout=20)
    time.sleep(1.5)
    rc, url = bb_eval("window.location.href")
    return '/login' in (url or '')


def extract_captcha_png(out_path: Path) -> bool:
    """Pull the captcha PNG (base64) out of the page and decode to disk."""
    rc, src = bb_eval("document.querySelector('.captcha-image').src")
    if rc != 0 or not src or 'base64,' not in src:
        return False
    b64 = src.split('base64,', 1)[1].strip().strip('"')
    try:
        out_path.write_bytes(base64.b64decode(b64))
        return True
    except Exception as e:
        print(f'decode failed: {e}', file=sys.stderr)
        return False


def fill_and_submit(username: str, password: str, captcha: str) -> bool:
    """Fill the 3 login inputs and click submit."""
    js = (
        "(()=>{"
        "const ins=document.querySelectorAll('input');"
        f"ins[0].value={username!r};"
        "ins[0].dispatchEvent(new Event('input',{bubbles:true}));"
        f"ins[1].value={password!r};"
        "ins[1].dispatchEvent(new Event('input',{bubbles:true}));"
        f"ins[2].value={captcha!r};"
        "ins[2].dispatchEvent(new Event('input',{bubbles:true}));"
        "document.querySelector('.submit-btn').click();"
        "return 'submitted';})()"
    )
    rc, out = bb_eval(js)
    return rc == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('-u', '--username', default=os.environ.get('GUDAO_USERNAME', ''))
    ap.add_argument('-p', '--password', default=os.environ.get('GUDAO_PASSWORD', ''))
    ap.add_argument('-c', '--captcha', help='if provided, skip interactive prompt')
    ap.add_argument('--captcha-out', default=os.environ.get(
        'GUDAO_CAPTCHA_OUT',
        str(Path(tempfile.gettempdir()) / 'gudao_captcha.png'),
    ))
    args = ap.parse_args()

    if not args.username or not args.password:
        print('ERROR: username and password required (use -u/-p or env vars)', file=sys.stderr)
        return 2

    # 1. Check current token
    tok = probe_token()
    if tok:
        print(f'appToken already present (prefix={tok[:20]}...) — nothing to do')
        return 0

    # 2. Navigate to /login
    print('token missing — navigating to login page...')
    if not navigate_to_login():
        print('ERROR: failed to reach /login', file=sys.stderr)
        return 3

    # 3. Extract captcha
    captcha_png = Path(args.captcha_out)
    print(f'extracting captcha to {captcha_png} ...')
    if not extract_captcha_png(captcha_png):
        print('ERROR: failed to extract captcha image', file=sys.stderr)
        return 4

    # 4. Get captcha text
    if args.captcha:
        captcha = args.captcha
    else:
        print(f'CAPTCHA_READY: {captcha_png}')
        print('please read the PNG (vision OCR) and type the 4 digits, then press Enter:')
        captcha = input().strip()

    if not (captcha and captcha.isdigit() and len(captcha) >= 4):
        print(f'ERROR: invalid captcha input: {captcha!r}', file=sys.stderr)
        return 5

    # 5. Submit
    print(f'submitting with captcha={captcha} ...')
    if not fill_and_submit(args.username, args.password, captcha):
        print('ERROR: submit failed', file=sys.stderr)
        return 6

    # 6. Verify
    time.sleep(2)
    tok = probe_token()
    if tok:
        print(f'SUCCESS: appToken refreshed (prefix={tok[:20]}...)')
        return 0
    else:
        print('ERROR: token still missing after submit', file=sys.stderr)
        return 7


if __name__ == '__main__':
    sys.exit(main())