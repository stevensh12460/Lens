# LENS — Handoff Document

**For: next conversation / future Claude session**
**Last update: 2026-04-29**
**Owner: Steven Howard**

---

## Quick context

LENS is a fully local photography business OS on a Mac Studio M1 Max at `~/lens/`. FastAPI on port 8600, dashboard on 8800, SQLite at `~/lens/data/lens.db`.

The **two existing reference docs** to read first:
- `~/lens/LENS_FULL_BREAKDOWN.md` — complete system overview (architecture, services, pipeline, scoring, DB, endpoints, calendar, IG)
- `~/lens/CALENDAR_AND_INSTAGRAM.md` — calendar tab + IG integration specifics

This file is the delta on top of those — what's changed and what's pending **as of today**.

---

## Current state at a glance

| Component | Status |
|---|---|
| Pipeline (pass0-3) | ✅ Working, paused (mode `off` for Photoshop work) |
| Pass 1 | ✅ 353,799 complete, 46,282 errored, 0 queued |
| Pass 2 | ⏳ 100,310 queued (waiting on mode=auto to drain) |
| Pass 3 | ⏳ 23,508 queued |
| Calendar UI | ✅ Day/Week/Month + Prints-style candidate pool, click-and-click flow |
| Auto-fill | ⛔ **DISABLED by user policy** — never re-enable |
| Caption generation | ✅ Working with 32b text model (slow ~5-8 min/caption) |
| Cloudflare Tunnel | ✅ Running as `com.lens.tunnel` launchd service |
| IG account auth | ✅ Token valid, 60-day long-lived, scoped to `moodyvalleystills` |
| **IG publish (real)** | 🔴 **BLOCKED — account too new, no organic posts** |

---

## The big in-progress thing: IG publish blocker

### What happened today
1. Set up the full publish flow with three-tier safety: offline preview → dry-run container → real publish
2. Token is valid, all 5 scopes granted (`instagram_content_publish` confirmed scoped to `17841433141998115`)
3. Cloudflare Tunnel installed and running, public URL working
4. **Dry-run fails with error code 9004 / subcode 2207052** ("Only photo or video can be accepted as media type" / "Media download has failed")
5. **Even Wikipedia's URL fails identically** — proving it's not a tunnel/URL issue
6. Diagnosis: `moodyvalleystills` IG account has `media_count: 0`. Meta restricts new IG Business accounts with no organic activity from using the publish API.

### What user is doing
Posting 2-3 photos manually through the IG mobile app to warm up the account. Today's planned IG post (post #59, image 60514, "Misty solitude on the Hudson river" caption) was marked posted manually — they'll AirDrop the file to phone and post via IG app directly.

### What's needed when user returns
- They've manually posted 2-3 things
- Wait ~30 min for Meta's trust check
- Pick a NEW image, schedule it on calendar, run dry-run
- If dry-run succeeds: real publish with `?dry_run=false`
- If dry-run still fails: switch app to Live mode (developers.facebook.com → LENS app → toggle Development → Live)

---

## Cloudflare Tunnel (NEW today)

### Why it exists
Instagram needs a public HTTPS URL to fetch images. Local file paths and `localhost` don't work.

### Current setup
- Service: `com.lens.tunnel` (launchd, KeepAlive=true, RunAtLoad=true)
- Plist: `~/lens/launchd/com.lens.tunnel.plist`
- Logs: `~/lens/logs/tunnel.log`, `~/lens/logs/tunnel.error.log`
- Type: **Quick tunnel** (no Cloudflare account needed)
- Current URL: `https://mechanical-prospective-looking-admission.trycloudflare.com` (in `.env` as `PUBLIC_IMAGE_BASE_URL`)
- Forwards to: `http://localhost:8600`

### ⚠️ Known fragility
- Quick tunnels generate a **new random URL on every restart**
- If the tunnel service restarts, `.env` becomes stale and IG publish breaks
- For permanent solution, user needs to set up a **named tunnel** with a domain they own (or pick up a $10/yr domain on Cloudflare). One-time 5-min setup.

### How to refresh the URL after a tunnel restart
```bash
# 1. Get the new URL from tunnel logs
grep -oE "https://[a-zA-Z0-9-]+\.trycloudflare\.com" ~/lens/logs/tunnel.error.log | head -1

# 2. Update .env (replace PUBLIC_IMAGE_BASE_URL value)
# 3. Restart core
launchctl kickstart -k gui/$(id -u)/com.lens.core
```

---

## Auto-fill is OFF (do not undo)

### Why
User reported inappropriate photos (boudoir/wedding) auto-filled into IG calendar. Found a real bug where calendar slots auto-populated without genre filtering. User said "never ever auto fills with random photos into calendar please."

### What was disabled
1. **Backend** `POST /social/queue/fill` — now returns 403 with explanatory message
2. **Frontend buttons** "Fill 7d" / "Fill 14d" — replaced with disabled-state hint text
3. **JS function** `fillCalendarDays()` — no-op alert directing user to manual pool

### Calendar is now manual-pick only
Workflow: Calendar tab → scroll to **📷 Post Candidate Pool** → filter → click image → schedule modal OR click empty slot first then image (instant assign).

---

## Calendar tab improvements (NEW)

### Click flows
- **Click empty slot** → cell highlights blue, pool scrolls into view
- **Click image with slot pre-selected** → instant assign (no modal)
- **Click filled slot** → highlight + click image = swap
- **Click image with nothing pre-selected** → Schedule modal opens (date/slot/pillar)
- **X on filled cell** → delete entire post (blocked if `posted`)
- **Double-click filled cell** → preview/edit modal

### Post Candidate Pool filters
genre, subject_type, tag (substring), sort (grid_fit/nima/random/recent), min_nima, hide_scheduled, hide_posted, limit ≤ 10000

### New endpoints
- `GET /social/post-candidates` — rich filter pool (mirrors `/print/candidates` pattern)
- `GET /social/publish/{id}/preview` — offline preview, no API calls
- `POST /social/publish/{id}?dry_run=true|false` — three-layer safety publish

---

## Pipeline issue caught and fixed today

### What was wrong
- Pipeline had **130 ghost pass1 jobs** stuck in `queued` (AppleDouble `._*` macOS metadata files on `/Volumes/Storage/`)
- Strict waterfall blocked pass2 because pass1 wasn't "done"
- **100,411 images that passed pass1 never got pass2 jobs enqueued** (broken promotion)
- Mode was `off`, so workers weren't running

### What was done
1. Marked `._*` AppleDouble jobs errored (130)
2. Marked remaining 80 stuck Storage drive PNGs errored
3. Bulk-enqueued 100,410 missing pass2 jobs via direct INSERT
4. Switched mode to `auto` to resume workers
5. Pass 2 started draining at ~70 jobs/min

### Then user paused for Photoshop
Mode set back to `off`. To resume: `curl -X POST http://localhost:8600/social/mode/auto`

---

## File-level changes today

| File | Change |
|---|---|
| `api/routes/social.py` | Disabled `/queue/fill` (returns 403). Added `/post-candidates`. Added `/publish/{id}/preview`. Updated `/calendar` POST to accept `post_time` slot, reject double-bookings. |
| `api/routes/intelligence.py` | `/api/v1/images/{id}/thumb` and `/thumb.jpg` now accept HEAD method (IG fetcher requires this). |
| `services/post_scheduler.py` | Full rewrite. Three-step Graph API publish flow. `dry_run=True` default. URL generator uses `PUBLIC_IMAGE_BASE_URL` + `/api/v1/images/{id}/thumb.jpg`. |
| `dashboard/ui/index.html` | Removed old candidate pool from week subtab. Added Prints-style pool below all 3 views. Added Schedule modal. Killed Fill 7d/14d buttons. New JS: `loadPostCandidates`, `pickCandidate`, `openSchedModal`, `submitSchedule`, `selectCandidateSlot` repurposed. |
| `core/config.py` | Added `public_image_base_url: str = ""`. |
| `core/ollama.py` | Bumped `_TIMEOUT_LONG` from 360s → 900s (15 min) for slow 32b captions. |
| `.env` | Added `META_*`, `INSTAGRAM_*`, `PUBLIC_IMAGE_BASE_URL`. |
| `launchd/com.lens.tunnel.plist` | NEW — Cloudflare tunnel as launchd service. |

---

## Caption generation notes

- Currently uses `qwen2.5:32b` (text model, 25GB VRAM)
- Per-caption time: 30s-8min depending on prompt complexity
- Q4_K_M quantization (the "real 32b", just compressed weights — ~97% quality of FP16)
- Switching to `qwen2.5:14b` would be 5-10x faster with marginal quality loss (FP16 14b would fit in 28GB VRAM if user wants top-tier 14b speed/quality)
- Empty error string `Caption generation failed: ` was an `httpx.ReadTimeout('')` — fixed by bumping timeout

---

## Backups

- `com.lens.backup` runs nightly at 3:30 AM
- Script: `~/lens/scripts/backup_db.sh`
- Path: `~/lens/backups/lens-YYYYMMDD-HHMMSS.db`
- Keeps last 14 daily, prunes older
- Verifies each via `PRAGMA integrity_check`
- Last successful: 2026-04-27 03:30 (432 MB)

---

## Open todo (priority order)

1. **User posts 2-3 manually on IG** to warm up `moodyvalleystills` account
2. **Re-attempt dry-run** on a fresh post (not #59 — that's marked posted)
3. **If dry-run still fails**: switch Meta app from Development → Live mode
4. **First real publish** with `?dry_run=false`
5. **Set up named Cloudflare tunnel** (replace quick tunnel for stable URL)
6. **Auto-refresh access token** via launchd job (current token expires ~2026-06-25)
7. **Pixieset store config** — user is sorting out (auto-attach to all collections issue)
8. **32b re-tag pass** — when user is ready to upgrade pass3 quality. Switch `.env` to `qwen2.5vl:32b`, hit `/pipeline/pass3/retag-7b?print_worthy_only=true` overnight.

---

## User preferences (sticky context)

- **No auto-fill ever.** This is non-negotiable. Inappropriate photos surfaced before.
- **Strict sequential waterfall** for pipeline (all pass1 → all pass2 → all pass3). Don't allow overlap.
- **Eastern US time** for all timestamps in conversation.
- **Listen literally** — don't approximate or "close enough" interpretations.
- **Don't waste tokens searching** — read `LENS_OPERATIONS.md` and existing wiki memory before exploring filesystem.
- **`/Volumes/8TB` is off-limits** — user's personal drive, never read/scan/list.
- **Background shells make user nervous** — avoid `until`-loop bash calls that don't return promptly. They show up in the UI as "running" and cause anxiety.

---

## Quick command reference

```bash
# Pipeline mode
curl -X POST http://localhost:8600/social/mode/auto       # resume
curl -X POST http://localhost:8600/social/mode/off        # pause + free RAM

# Pipeline status
curl -s http://localhost:8600/intelligence/pipeline-health | python3 -m json.tool

# Restart any service
launchctl kickstart -k gui/$(id -u)/com.lens.<core|pipeline|watcher|dashboard|tunnel|backup>

# Tunnel current URL
grep -oE "https://[a-zA-Z0-9-]+\.trycloudflare\.com" ~/lens/logs/tunnel.error.log | head -1

# Token health
TOKEN=$(grep "^INSTAGRAM_ACCESS_TOKEN" ~/lens/.env | cut -d= -f2)
APP_ID=$(grep "^META_APP_ID" ~/lens/.env | cut -d= -f2)
APP_SECRET=$(grep "^META_APP_SECRET" ~/lens/.env | cut -d= -f2)
curl -s "https://graph.facebook.com/v19.0/debug_token?input_token=$TOKEN&access_token=$APP_ID|$APP_SECRET" | python3 -m json.tool

# Preview a post
curl -s http://localhost:8600/social/publish/<POST_ID>/preview | python3 -m json.tool

# Dry-run (safe — creates IG container only, doesn't publish)
curl -s -X POST http://localhost:8600/social/publish/<POST_ID>

# Real publish (LIVE — only after dry-run passes)
curl -s -X POST "http://localhost:8600/social/publish/<POST_ID>?dry_run=false"

# Latest planned post
sqlite3 ~/lens/data/lens.db "SELECT id, post_date, post_time, status FROM calendar_posts WHERE status='planned' ORDER BY post_date LIMIT 5;"
```

---

## Files to reference (in order of importance)

1. `~/lens/LENS_FULL_BREAKDOWN.md` — full system reference
2. `~/lens/CALENDAR_AND_INSTAGRAM.md` — IG-specific
3. `~/lens/HANDOFF.md` — this file
4. `~/lens/LENS_OPERATIONS.md` — operational runbook (older, may be stale on calendar)
5. `~/lens/PRICING.md` — print pricing strategy
