"""
services/token_refresh.py — keep the Meta token healthy (weekly, via launchd).

LENS posts with a PAGE access token, which is PERMANENT (no expiry) as long as
it isn't revoked. So there's nothing to "refresh" on a schedule — re-exchanging a
long-lived token does NOT reset its clock (learned the hard way). What CAN break
it: the page owner changes their FB password, removes the app, or revokes
permissions. That makes the token silently invalid and posts start failing.

This monitor runs weekly and:
  1. Checks the live token is still valid (debug_token).
  2. If it ever shows an expiry or goes invalid, tries to RE-DERIVE a fresh
     permanent page token from the stashed user token (META_USER_TOKEN_BACKUP),
     while that's still usable.
  3. If it can't fix it, drops a loud flag file (~/lens/TOKEN_NEEDS_REAUTH) and
     logs an ALERT so the breakage is visible BEFORE every post fails.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENV = Path.home() / "lens" / ".env"
LOG = Path.home() / "lens" / "logs" / "token_refresh.log"
ALERT_FLAG = Path.home() / "lens" / "TOKEN_NEEDS_REAUTH"
TOKEN_KEYS = ("META_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN")
THRESHOLD_DAYS = 30


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M:%S %Z} {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def read_env() -> dict[str, str]:
    env = {}
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k, _, v = l.partition("="); env[k.strip()] = v.strip()
    return env


def _get(url: str):
    return json.load(urllib.request.urlopen(url, timeout=20))


def debug(token: str, app: str) -> dict | None:
    try:
        return _get(f"https://graph.facebook.com/debug_token?input_token={token}&access_token={app}").get("data", {})
    except Exception as e:
        log(f"debug_token call failed: {e}")
        return None


def derive_page_token(user_tok: str, page_id: str) -> str | None:
    try:
        return _get(f"https://graph.facebook.com/v19.0/{page_id}?fields=access_token&access_token={user_tok}").get("access_token")
    except Exception as e:
        log(f"page-token derivation failed: {e}")
        return None


def write_token(new: str) -> None:
    shutil.copy(ENV, ENV.with_name(f".env.bak-{int(time.time())}"))
    out = []
    for l in ENV.read_text().splitlines():
        k = l.partition("=")[0].strip()
        out.append(f"{k}={new}" if k in TOKEN_KEYS else l)
    ENV.write_text("\n".join(out) + "\n")
    log("wrote refreshed page token to .env")


def main() -> None:
    env = read_env()
    tok = env.get("META_ACCESS_TOKEN")
    app = f"{env.get('META_APP_ID')}|{env.get('META_APP_SECRET')}"
    if not tok or "None" in app:
        log("FAIL: missing token / app creds in .env"); sys.exit(1)

    data = debug(tok, app)
    if data and data.get("is_valid"):
        exp = data.get("expires_at", 0)
        if not exp:
            log(f"OK: token valid, type={data.get('type')}, PERMANENT — no action")
            ALERT_FLAG.unlink(missing_ok=True)
            return
        days = (exp - time.time()) / 86400
        log(f"token valid but has {days:.1f} days left (expected permanent page token)")
        if days >= THRESHOLD_DAYS:
            ALERT_FLAG.unlink(missing_ok=True); return
        log("token expiring — attempting to re-derive a permanent page token")
    else:
        log("ALERT: live token is INVALID — attempting re-derivation")

    # Try to re-mint a permanent page token from the stashed user token.
    user_tok = env.get("META_USER_TOKEN_BACKUP")
    page_id = env.get("META_FB_PAGE_ID")
    if user_tok and page_id and (debug(user_tok, app) or {}).get("is_valid"):
        new = derive_page_token(user_tok, page_id)
        if new and not (debug(new, app) or {}).get("expires_at", 1):
            write_token(new)
            log("recovered: fresh permanent page token installed")
            ALERT_FLAG.unlink(missing_ok=True)
            return

    ALERT_FLAG.write_text(f"Meta token needs manual re-auth as of {datetime.now().astimezone():%Y-%m-%d %H:%M}\n")
    log(f"ALERT: could not auto-recover. Flag dropped at {ALERT_FLAG}. Re-auth the Meta app by hand.")
    sys.exit(1)


if __name__ == "__main__":
    main()
