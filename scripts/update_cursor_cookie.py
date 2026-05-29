from pathlib import Path
import re
import sys

raw = sys.stdin.read()

patterns = [
    # Windows Chrome / Edge: -b ^"...^"
    r'-b\s+\^"(?P<cookie>.+?)\^"',
    # normal curl: -b "..."
    r'-b\s+"(?P<cookie>.+?)"',
    # normal curl: -b '...'
    r"-b\s+'(?P<cookie>.+?)'",
    # fallback: -H "cookie: ..."
    r'-H\s+\^?"cookie:\s*(?P<cookie>.+?)\^?"',
    r'-H\s+"cookie:\s*(?P<cookie>.+?)"',
    r"-H\s+'cookie:\s*(?P<cookie>.+?)'",
]

cookie = None
for pat in patterns:
    m = re.search(pat, raw, re.I | re.S)
    if m:
        cookie = m.group("cookie")
        break

if not cookie:
    raise SystemExit("ERROR: Cookie block was not found. Copy as cURL output must include -b or cookie header.")

# Windows cmd escaping cleanup
cookie = cookie.replace("^", "").strip()

# 余計な外側 quote が残った場合だけ剥がす
if (cookie.startswith('"') and cookie.endswith('"')) or (cookie.startswith("'") and cookie.endswith("'")):
    cookie = cookie[1:-1].strip()

# 軽い検証。値は表示しない。
checks = {
    "contains_caret": "^" in cookie,
    "contains_cookie_prefix": "Cookie:" in cookie,
    "contains_workos": "WorkosCursorSessionToken" in cookie,
    "contains_semicolon": ";" in cookie,
}

config_dir = Path.home() / ".config" / "zcounter"
config_dir.mkdir(parents=True, exist_ok=True)
config_dir.chmod(0o700)

path = config_dir / "cursor.toml"
path.write_text(
    "[cursor]\n"
    "enabled = true\n"
    f"cookie_header = '''{cookie}'''\n",
    encoding="utf-8",
)
path.chmod(0o600)

print("wrote:", path)
print("length:", len(cookie))
for k, v in checks.items():
    print(f"{k}:", v)

if checks["contains_caret"]:
    print("WARN: caret remains in cookie. Extraction may be wrong.")
if checks["contains_cookie_prefix"]:
    print("WARN: Cookie: prefix remains. Extraction may be wrong.")
if not checks["contains_workos"]:
    print("WARN: WorkosCursorSessionToken not found. Auth may fail.")
