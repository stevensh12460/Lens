# LENS — Full System Breakdown

End-to-end documentation of the Local ENrichment & Selection system: a fully local photography business OS running on a Mac Studio M1 Max.

Last updated: **2026-04-25**

---

## TABLE OF CONTENTS

1. [Mission & Architecture](#1-mission--architecture)
2. [Hardware & Runtime](#2-hardware--runtime)
3. [Services (launchd jobs)](#3-services-launchd-jobs)
4. [The Pipeline (Pass 0 → Pass 3)](#4-the-pipeline-pass-0--pass-3)
5. [Scoring System](#5-scoring-system)
6. [Database](#6-database)
7. [Configuration](#7-configuration)
8. [Dashboard (port 8800)](#8-dashboard-port-8800)
9. [API (port 8600) — Endpoint Map](#9-api-port-8600--endpoint-map)
10. [Print Business](#10-print-business)
11. [Instagram / Social Calendar](#11-instagram--social-calendar)
12. [Backup & Resilience](#12-backup--resilience)
13. [Common Operations](#13-common-operations)
14. [What's Working / What's Pending](#14-whats-working--whats-pending)

---

## 1. Mission & Architecture

### Mission
Take a folder full of raw photos (RAW, JPEG, etc.) and surface only the keepers, with rich metadata, ready for:
- **Print sales** (Pixieset)
- **Instagram posting** (@moodyvalleystills)
- **Portfolio review** (dashboard)

Everything runs **locally**. Zero cloud dependencies for processing. The only outbound calls are to Instagram when publishing.

### High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Watcher (folder watch)  →  Pass 0 (EXIF)                       │
│                                ↓                                │
│                            Pass 1 (cull, 6 workers)             │
│                                ↓                                │
│                            Pass 2 (NIMA technical scoring)      │
│                                ↓                                │
│                            Pass 3 (vision tagging via Ollama)   │
│                                ↓                                │
│                            Privacy / Print / Social             │
│                                ↓                                │
│                         SQLite (local SSD)                      │
│                                ↓                                │
│                ┌───────────────┴──────────────┐                 │
│                │                              │                 │
│           FastAPI (8600)               Dashboard (8800)         │
│                │                              │                 │
│                └────────→ Instagram ←─────────┘                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Strict sequential waterfall
**ALL pass1 finishes before any pass2 starts. ALL pass2 finishes before any pass3 starts.** No overlap. This is enforced and non-negotiable.

---

## 2. Hardware & Runtime

| Component | Spec |
|---|---|
| Machine | Mac Studio M1 Max |
| OS | macOS |
| Python | 3.11 |
| DB | SQLite with WAL mode, on local SSD (`~/lens/data/lens.db`) |
| LLM runtime | Ollama (port 11434) |
| Vision models | `qwen2.5vl:7b` (current, fast) and `qwen2.5vl:32b` (~20GB RAM, slow, used for re-tagging) |
| Text model | (whatever `TEXT_MODEL` resolves to in `.env`) |

### Why local SSD for DB
The DB used to live on `/Volumes/8TB`. Heavy concurrent writes during bulk enqueue corrupted the file ("database disk image is malformed"). It was recovered with `sqlite3 .recover` (lost only 111 of 400k rows). Now lives at `~/lens/data/lens.db` with protective PRAGMAs (synchronous=FULL, WAL caps, foreign keys on).

---

## 3. Services (launchd jobs)

Six services run under `launchctl gui/$(id -u)/`:

| Service | What it does | Plist |
|---|---|---|
| `com.lens.core` | FastAPI on port 8600 | `~/lens/launchd/com.lens.core.plist` |
| `com.lens.pipeline` | Worker pool — runs the 4 pipeline passes | `~/lens/launchd/com.lens.pipeline.plist` |
| `com.lens.watcher` | Watches folders for new photos and enqueues them | `~/lens/launchd/com.lens.watcher.plist` |
| `com.lens.dashboard` | Static dashboard server on port 8800 | `~/lens/launchd/com.lens.dashboard.plist` |
| `com.lens.ollama` | Wraps `ollama serve` so it's always running | `~/lens/launchd/com.lens.ollama.plist` |
| `com.lens.backup` | Nightly DB backup at 3:30 AM | `~/lens/launchd/com.lens.backup.plist` |

### Common launchctl commands
```bash
# Start a service
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lens.<name>.plist

# Stop a service
launchctl bootout gui/$(id -u)/com.lens.<name>

# Restart (pick up new code/config)
launchctl kickstart -k gui/$(id -u)/com.lens.<name>

# Check status
launchctl list | grep com.lens
```

### Uses 20GB+ RAM warning
`qwen2.5vl:32b` uses ~20GB. Don't run it while editing in Photoshop or Lightroom. To unload from RAM:
```
POST http://localhost:8600/social/mode/off
```
Or via Priority Queue tab → "Unload LLM" button.

---

## 4. The Pipeline (Pass 0 → Pass 3)

### Pass 0 — EXIF extraction
- Reads camera, lens, ISO, shutter, aperture, focal length, capture time, GPS, etc.
- Fast (~50ms per file).
- Code: `pipeline/pass0_exif.py`

### Pass 1 — Cull (6 workers)
- **Goal**: drop blur, near-duplicates, technically dead frames; pass everything else.
- Computes blur score, exposure issues, near-duplicate hash.
- Routes each image to one of: `pass`, `dup`, `failed`, `raw_review`.
- ~5,000 images/hour with 6 workers.
- Code: `pipeline/pass1_cull.py`

### Pass 2 — NIMA technical scoring
- Runs only on pass1 `pass`-status images.
- Computes `nima_composite` (0-10 aesthetic-technical score).
- Also computes `grid_fit_score` (Instagram grid suitability).
- Code: `pipeline/pass2_nima.py`

### Pass 3 — Vision tagging
- Runs only on pass2-scored images.
- Uses Ollama (`qwen2.5vl:7b` currently) to extract:
  - `genre` — nature, portrait, wedding, boudoir, commercial, events
  - `subject_type` — landscape, solo portrait, couple, group, product
  - `mood` — serene, dramatic, intimate, etc.
  - `setting` — outdoor water, urban, studio, etc.
  - `tags` — JSON list of 10 freeform descriptors (e.g. `["foggy", "lake", "canoe"]`)
  - `caption_draft` — auto-generated IG caption
- Records `pass3_model` (`qwen2.5vl:7b` or `qwen2.5vl:32b`) so 7b-tagged images can be re-reviewed by 32b later.
- Code: `pipeline/pass3_tag.py`

### Re-tagging with 32b
When you want quality over speed:
1. Switch `.env`: `VISION_MODEL=qwen2.5vl:32b`
2. Restart core
3. Hit `POST /pipeline/pass3/retag-7b?print_worthy_only=true` — re-enqueues all 7b-tagged images for 32b
4. Run overnight, switch back to 7b in the morning

---

## 5. Scoring System

### `nima_composite` (0-10)
Aesthetic + technical quality. Computed during pass2.
- ≥ 7.0 → fine art tier
- 6.5 - 7.0 → standard print tier
- < 6.5 → below threshold (kept but not flagged for sale)

### `grid_fit_score` (0-1)
How well the image fits an Instagram grid aesthetically. Used as default sort for the post candidate pool.

### `print_score`
Currently mirrors `nima_composite` (rule-based, set in pass2).
- Was previously LLM-based — switched to rule-based per user direction so prints score with existing data and pass3 (LLM) is reserved for tagging only.

### `print_tier`
- `fine_art` — `nima_composite >= 7.0`
- `standard` — `nima_composite 6.5 - 7.0`
- `below_threshold` — anything else

Set in `services/print_curator.py`.

---

## 6. Database

**Path**: `/Users/stevenhoward/lens/data/lens.db`
**Mode**: WAL with `synchronous=FULL`, `wal_autocheckpoint=200`, `journal_size_limit=64MB`, `foreign_keys=ON`

### Key tables

#### `images`
Every photo lives here once imported.
```
id, file_path, file_name, captured_at, ...exif fields...
pass1_status, cull_score
nima_composite, quality_score, grid_fit_score
genre, subject_type, mood, setting, tags (JSON), caption_draft
print_worthy, print_tier, print_score, print_technique
edition_title, edition_size, editions_sold
pixieset_url, pixieset_product_id
posted_at, posted_to                    -- IG posting record
content_ready, social_queue
pass3_at, pass3_model                   -- which model tagged it
```

#### `pipeline_jobs`
Work queue for the 4 passes. One row per (image, pass).
```
id, image_id, job_type ('pass1'|'pass2'|'pass3'|'pass0')
status ('queued'|'running'|'complete'|'errored')
heartbeat_at, started_at, completed_at, error
```

#### `calendar_posts`
IG posting calendar.
```
id, post_date, post_time ('morning'|'evening')
pillar ('personality'|'transformation'|'social_proof'|'education'|'portfolio')
genre, image_id
caption, hashtags
status ('planned'|'scheduled'|'posted'), posted_at
```

#### `print_sales` / `print_revenue` / `editions`
Print business tracking.

### Critical indexes
```
idx_images_pass1_status
idx_images_cull_score
idx_images_pass2_at
idx_images_pass3_at
idx_images_portfolio
idx_images_print_worthy ON images(print_worthy) WHERE print_worthy=1
idx_images_print_score
idx_images_subject_type
idx_images_genre_pw
idx_pj_image_type ON pipeline_jobs(image_id, job_type)
```
Without these, `/intelligence/pipeline-health` was taking 3.7s. With them: 70ms.

---

## 7. Configuration

### `.env` (`/Users/stevenhoward/lens/.env`)
```
LENS_DB_PATH=/Users/stevenhoward/lens/data/lens.db
VISION_MODEL=qwen2.5vl:7b
TEXT_MODEL=...
OLLAMA_URL=http://localhost:11434

# Meta / Instagram
META_APP_ID=1672205817296983
META_APP_SECRET=de67120b7217963af0fd6e9510b316c4
META_ACCESS_TOKEN=<long-lived token>
META_IG_BUSINESS_ID=17841433141998115
META_FB_PAGE_ID=1128845970304377
INSTAGRAM_ACCESS_TOKEN=<same token>
INSTAGRAM_ACCOUNT_ID=17841433141998115

# Pixieset (optional, set when publishing prints)
PIXIESET_API_TOKEN=
PIXIESET_USER_ID=
```

### Print pricing (`core/config.py`)
```python
standard_prices = {
    "8x10":  {"paper": 75,  "canvas": None, "metal": None},
    "11x14": {"paper": 110, "canvas": 200,  "metal": 225},
    "16x20": {"paper": 165, "canvas": 285,  "metal": 325},
    "20x30": {"paper": 260, "canvas": 420,  "metal": 475},
    "24x36": {"paper": 345, "canvas": 485,  "metal": 575},
}
fine_art_prices = {
    "11x14": {"paper": 175,  "canvas": 300,  "metal": 350},
    "16x20": {"paper": 250,  "canvas": 400,  "metal": 475},
    "20x30": {"paper": 395,  "canvas": 575,  "metal": 675},
    "24x36": {"paper": 525,  "canvas": 750,  "metal": 875},
    "40x60": {"paper": 1100, "canvas": 1450, "metal": 1750},
}
fine_art_edition_size = 25      # editioned
standard_edition_size = 0       # open edition
```

---

## 8. Dashboard (port 8800)

URL: **http://localhost:8800**

### Tabs

| Tab | What it shows | Loader function |
|---|---|---|
| **Overview** | Pipeline progress bars, recent jobs, quick stats | `loadOverview()` |
| **📅 Calendar** | Day/Week/Month view + Post Candidate Pool | `loadCalendar()` |
| **Pipeline** | Health bar, job queue, error log, pass-by-pass progress | `loadPipeline()` |
| **Images** | Browse all images with filters | `loadImages()` |
| **Clients** | Client/shoot management | `loadClients()` |
| **🖼 Prints** | Print candidate pool + pricing | `loadPrints()` |
| **Priority Queue** | "Process this folder NOW" tool | `loadPriority()` |
| **Settings** | Mode toggles, IG status, Pixieset status | — |

### Calendar tab — full breakdown
See [Section 11](#11-instagram--social-calendar).

### Prints tab — full breakdown
See [Section 10](#10-print-business).

---

## 9. API (port 8600) — Endpoint Map

### Pipeline — `/pipeline/*`
| Endpoint | Method | Use |
|---|---|---|
| `/pipeline/health` | GET | Status dot color + counts |
| `/pipeline/jobs` | GET | Recent jobs with state |
| `/pipeline/scan` | POST | Walk a folder, enqueue new photos. Filters junk paths and existing jobs. |
| `/pipeline/pass3/retag-7b` | POST | Clear pass3 on 7b-tagged images and re-enqueue for 32b |

### Intelligence — `/intelligence/*`
| Endpoint | Method | Use |
|---|---|---|
| `/intelligence/pipeline-health` | GET | Counts by pass for dashboard |
| `/intelligence/thumb/{id}` | GET | Cached thumbnail (filesystem cache `~/lens/cache/thumbs/`) |

### Images — `/api/v1/images/*`
| Endpoint | Method | Use |
|---|---|---|
| `/api/v1/images/{id}/thumb` | GET | Image thumbnail (used by dashboard cards) |

### Print — `/api/v1/print/*`
See [Section 10](#10-print-business).

### Social — `/social/*`
See [Section 11](#11-instagram--social-calendar).

---

## 10. Print Business

### Curation flow
1. Pass2 sets `nima_composite` for every image.
2. `services/print_curator.py` tiers each image:
   - `nima_composite >= 7.0` → `fine_art` (edition of 25)
   - `nima_composite 6.5 - 7.0` → `standard` (open edition)
   - else → `below_threshold`
3. Setting `print_worthy=1` on tier-eligible images.
4. Prints tab shows them with suggested prices per size/medium.
5. User picks one, opens its Pixieset listing manually, and the dashboard records the URL.

### Endpoints

| Endpoint | What it does |
|---|---|
| `GET /api/v1/print/candidates` | Filter by tier/genre/subject/tag, returns cards with prices |
| `GET /api/v1/print/pricing` | Returns the pricing tables |
| `POST /api/v1/print/mark-posted` | Records `pixieset_url` for an image |
| `GET /api/v1/print/worthy` | Just the print-worthy list |
| `GET /api/v1/print/top` | Top by `print_score` |
| `POST /api/v1/print/editions` | Define a limited edition |
| `GET /api/v1/print/editions/alerts` | Editions hitting 50/80/100% sold |
| `POST /api/v1/print/sales` | Record a sale (price, channel, lab cost) |
| `GET /api/v1/print/revenue` | Revenue summary |
| `GET /api/v1/print/revenue/by-channel` | Channel breakdown |
| `GET /api/v1/print/revenue/by-month` | 12-month trend |
| `GET /api/v1/print/dashboard` | Combined inventory + revenue |
| `GET /api/v1/print/gbp/queue` | Google Business Profile push queue (not yet wired up) |

### Why no auto-upload to Pixieset
Pixieset only has a **read-only API**. Listing prints is manual: log into Pixieset, upload photo, set price, copy URL, paste it in the LENS print modal.

---

## 11. Instagram / Social Calendar

### Auth setup (DONE)
- App: LENS (Meta dev)
- Page: Moody Valley Stills
- Account: `@moodyvalleystills` (Business)
- Long-lived token (60 days) in `.env`

### Calendar UI
**Layout** (Calendar tab):
1. IG / Pixieset status indicators
2. **Day / Week / Month** view toggle + date picker + genre filter + Fill-7d / Fill-14d shortcuts + ✨ Captions
3. The active subtab view (day/week/month grid)
4. **📷 Post Candidate Pool** — Prints-style filter bar + grid (always visible below all 3 views)

### Click flows
| Action | Result |
|---|---|
| Click empty slot in Week view | Cell highlights blue, pool scrolls into view |
| Click image in pool (with slot pre-selected) | Instantly assigned (no modal) |
| Click filled slot in Week view | Cell highlights blue (swap mode) |
| Click image in pool (filled slot pre-selected) | Instantly swaps the image |
| Click image in pool (no slot pre-selected) | Schedule modal opens (date/slot/pillar) |
| Click X on filled cell | Deletes the calendar post (slot becomes empty); blocked for `posted` rows |
| Double-click filled cell | Opens preview/edit modal |
| Click same highlighted cell again | Deselects |

### Endpoints
| Endpoint | Method | Use |
|---|---|---|
| `/social/post-candidates` | GET | Rich pool query (genre, subject, tag, min_nima, sort, exclude_scheduled, exclude_posted, limit ≤ 10000) |
| `/social/calendar` | GET | List posts in a date range |
| `/social/calendar` | POST | Create a planned post (date, slot, pillar, image_id) — rejects double-bookings with 409 |
| `/social/calendar/{id}` | GET | Single post with image metadata |
| `/social/calendar/{id}` | DELETE | Remove a post (blocked if `posted`) |
| `/social/calendar/{id}/image` | PATCH | Swap image on a post |
| `/social/calendar/{id}/caption` | PATCH | Edit caption + hashtags |
| `/social/caption` | POST | Generate caption for one image |
| `/social/caption/batch/scheduled` | POST | Batch-generate captions for next N days |
| `/social/queue` | GET | Quick stats — unposted / by genre |
| `/social/grid` | GET | IG grid preview (last N posts visualized) |
| `/social/instagram/status` | GET | Auth health (configured, token_set, last_post) |
| `/social/publish/{id}/preview` | GET | **Offline preview, no API calls** |
| `/social/publish/{id}` | POST | Publish; `?dry_run=true` (default) creates container only; `?dry_run=false` actually posts |
| `/social/mode/{mode}` | POST | Switch operating mode (off/text/auto/priority) — controls Ollama loading |

### Three-layer publish safety
| Layer | Calls IG? | Public? |
|---|---|---|
| `GET /publish/{id}/preview` | No | No |
| `POST /publish/{id}?dry_run=true` (default) | Yes (creates container) | No (container expires unused in 24h) |
| `POST /publish/{id}?dry_run=false` | Yes | **YES** |

The default-on `dry_run=true` means a typo cannot publish.

---

## 12. Backup & Resilience

### Nightly backups
- Service: `com.lens.backup` runs at 3:30 AM
- Script: `~/lens/scripts/backup_db.sh`
- Method: `sqlite3 .backup` (safe with active connections)
- Retention: last 14 daily backups kept, older pruned
- Path: `~/lens/backups/lens-YYYYMMDD-HHMMSS.db`
- Verifies each backup with `PRAGMA integrity_check` — failed verifies are kept as `.suspect` for inspection.
- Logs: `~/lens/logs/backup.log`, `~/lens/logs/backup.error.log`

### Protective PRAGMAs
Set on every connection in `core/database.py`:
```sql
PRAGMA journal_mode=WAL
PRAGMA synchronous=FULL
PRAGMA wal_autocheckpoint=200
PRAGMA journal_size_limit=67108864
PRAGMA foreign_keys=ON
```

### Recovery from corruption
If `lens.db` ever shows "database disk image is malformed":
```bash
cp ~/lens/data/lens.db ~/lens/data/lens.corrupt.db
sqlite3 ~/lens/data/lens.corrupt.db ".recover" > ~/lens/data/recovered.sql
mv ~/lens/data/lens.db ~/lens/data/lens.broken.db
sqlite3 ~/lens/data/lens.db < ~/lens/data/recovered.sql
```
This recovered 400k-1 of 400k rows on the previous incident.

---

## 13. Common Operations

### Restart everything
```bash
for svc in core pipeline watcher dashboard; do
  launchctl kickstart -k gui/$(id -u)/com.lens.$svc
done
```

### Check pipeline health
```bash
curl -s http://localhost:8600/intelligence/pipeline-health | python3 -m json.tool
```

### Pause everything (free RAM for Photoshop)
```bash
launchctl bootout gui/$(id -u)/com.lens.pipeline
# Optional: also unload Ollama
curl -X POST http://localhost:8600/social/mode/off
```

### Resume
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lens.pipeline.plist
```

### Scan a new folder
```bash
curl -X POST http://localhost:8600/pipeline/scan \
  -H 'Content-Type: application/json' \
  -d '{"path": "/path/to/folder"}'
```

### Tail the core log
```bash
tail -f ~/lens/logs/core.log
```

### See tonight's backup
```bash
ls -lh ~/lens/backups/ | tail -5
tail ~/lens/logs/backup.log
```

---

## 14. What's Working / What's Pending

### ✅ Working
- Full pipeline (pass0 → pass3) on 230k+ images, ~5,000/hr
- Strict sequential waterfall enforced
- NIMA scoring + rule-based print tiering
- Pass3 vision tagging via Ollama (7b for speed)
- Print pricing tables + Prints tab UI
- IG / Meta auth wired, account verified
- Calendar tab with Day/Week/Month + Prints-style candidate pool
- Click-and-click + Schedule modal flows
- Three-layer publish safety (offline preview → dry-run container → real publish)
- Nightly DB backups
- DB on local SSD with protective PRAGMAs

### 🟡 Pending
1. **Image hosting for real IG publish** — IG requires a public HTTPS URL. Options:
   - Pixieset URL (set per-image manually)
   - Cloudflare Tunnel (set `PUBLIC_IMAGE_BASE_URL` in `.env`)
2. **Caption population** — most calendar posts have null `caption_draft`. Run `POST /social/caption/batch/scheduled?days=7` to generate.
3. **First test post** — chain: preview → dry-run → real publish, in that order, on one carefully-chosen image.
4. **Auto-refresh of IG access token** — currently expires every 60 days. Add a launchd job that refreshes monthly.
5. **32b re-tag pass** — when ready: switch `.env` to `qwen2.5vl:32b`, restart core, hit `/pipeline/pass3/retag-7b?print_worthy_only=true`.
6. **Pixieset upload workflow** — manual; Pixieset has read-only API only.
7. **Google Business Profile push** — endpoints exist but no OAuth wired up.

### ⛔ Blocked
- **Meta SMS verification** — initial blocker resolved. Token now valid.
- **Pixieset write API** — does not exist, will always be manual.

---

## Reference Documents

- `~/lens/LENS_OPERATIONS.md` — primary operational runbook
- `~/lens/CALENDAR_AND_INSTAGRAM.md` — Calendar/IG specifics
- `~/lens/PRICING.md` — print pricing strategy + market comps
- `~/.claude/projects/.../MEMORY.md` — assistant memory index

## Quick links

| What | Where |
|---|---|
| Dashboard | http://localhost:8800 |
| API | http://localhost:8600 |
| API docs | http://localhost:8600/docs |
| Ollama | http://localhost:11434 |
| DB | `~/lens/data/lens.db` |
| Backups | `~/lens/backups/` |
| Logs | `~/lens/logs/` |
| Code | `~/lens/` |
