#!/bin/bash
# check_plugin.sh — syntax-check the LENS Lightroom plugin against Lua 5.1.
#
# Why this exists: Lightroom runs Lua 5.1, and a syntax error there surfaces as
# the wildly misleading "No script by the name <file>.lua". We lost a full debug
# cycle to exactly that (a `//` floor division, which is 5.3+ syntax).
#
# Plain `luac -p` is NOT sufficient — Homebrew's lua is 5.5 and happily accepts
# `//`, bitwise operators, and integer division. LuaJIT implements the 5.1
# dialect, so it rejects them like Lightroom does. The grep pass covers the
# remaining constructs LuaJIT tolerates but Lightroom does not.
#
# Usage:  bash lightroom/check_plugin.sh
# Exit 0 = safe to load in Lightroom.

set -uo pipefail
DIR="$(cd "$(dirname "$0")/LENS.lrplugin" && pwd)"
fail=0

echo "Checking $DIR against Lua 5.1 (LuaJIT)"
echo

for f in "$DIR"/*.lua; do
    name="$(basename "$f")"
    if err=$(luajit -bl "$f" /dev/null 2>&1); then
        printf '  OK    %s\n' "$name"
    else
        printf '  FAIL  %s\n' "$name"
        printf '        %s\n' "$err"
        fail=1
    fi
done

echo
echo "Scanning for constructs LuaJIT allows but Lightroom 5.1 does not:"
# goto/::label:: are 5.2+, which LuaJIT adopted but Lightroom never did.
# utf8.* is 5.3+.
#
# Comments MUST be stripped first: these same files document the rule in prose
# ("no goto, no bitwise"), and a naive grep flags its own documentation.
if hits=$(python3 - "$DIR" <<'PY'
import re, sys, pathlib

BANNED = [
    (re.compile(r'(?:^|[^\w.])goto\s'), "goto (Lua 5.2+)"),
    (re.compile(r'::[A-Za-z_]\w*::'),   "::label:: (Lua 5.2+)"),
    (re.compile(r'\butf8\.'),           "utf8 library (Lua 5.3+)"),
]

def strip_comments(src: str) -> str:
    """Blank out block and line comments, preserving line numbers."""
    src = re.sub(r'--\[(=*)\[.*?\]\1\]',
                 lambda m: re.sub(r'[^\n]', ' ', m.group(0)), src, flags=re.S)
    return re.sub(r'--[^\n]*', '', src)

found = False
for path in sorted(pathlib.Path(sys.argv[1]).glob("*.lua")):
    for n, line in enumerate(strip_comments(path.read_text()).splitlines(), 1):
        for pattern, label in BANNED:
            if pattern.search(line):
                print(f"{path.name}:{n}: {label}: {line.strip()[:70]}")
                found = True
sys.exit(1 if found else 0)
PY
); then
    echo "  none found"
else
    echo "$hits" | sed 's/^/  BANNED  /'
    fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
    echo "PASS — safe to load in Lightroom."
else
    echo "FAIL — fix before loading, or Lightroom will report"
    echo "       'No script by the name <file>.lua' instead of the real error."
fi
exit "$fail"
