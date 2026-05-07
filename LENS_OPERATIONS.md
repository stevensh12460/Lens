# LENS Operations Guide
**Last updated: 2026-04-09**
**Written for future Claude instances — read this before touching anything.**

---

## What LENS Is

Fully local photography business OS running on Steven's Mac Studio M1 Max (32 GB unified memory, macOS 26.x). No cloud. No subscriptions for AI. Everything runs on-device. Privacy enforced: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` — no data leaves the machine.

- **API**: FastAPI at `http://localhost:8600`
- **Dashboard**: Static HTML at `http://localhost:8800`
- **Ollama**: `http://localhost:11434`
- **Database**: `/Volumes/8TB/claudes selects/lens/data/lens.db` (SQLite WAL)
- **Code**: `/Users/stevenhoward/lens/`
- **Venv**: `/Users/stevenhoward/lens/venv/` (Python 3.11)
- **Model weights**: `~/lens/models/` (LAION MLP) + `~/.cache/` (NIMA, CLIP auto-cached)

---

## Services (launchd — KeepAlive = true)

All services are managed by launchd and **will restart automatically** if killed. Use the correct commands.

| Label | What it does | Port |
|---|---|---|
| `com.lens.core` | FastAPI API server | 8600 |
| `com.lens.dashboard` | Static dashboard server | 8800 |
| `com.lens.pipeline` | Queue manager / processing loop | none |
| `com.lens.watcher` | File system watcher (auto-import) | none |
| `com.lens.ollama` | Ollama inference server | 11434 |
| `com.lens.post-scheduler` | Auto-publish (900s interval) | none |

**Restart a service** (clean restart, clears stale state):
```bash
launchctl kickstart -k gui/$(id -u)/com.lens.core
```

**Do NOT use `launchctl stop`** — KeepAlive means it restarts in 10 seconds anyway and leaves jobs stuck in 'running'.

**Plist files**: `/Users/stevenhoward/lens/launchd/` (symlinked into `~/Library/LaunchAgents/`)

---

## Directory Structure

```
~/lens/
  api/main.py                    # FastAPI app
  api/routes/pipeline.py         # Pipeline/jobs/priority endpoints
  api/routes/social.py           # Instagram, captions, calendar, mode
  api/routes/crm.py              # Clients, bookings, intake, galleries
  api/routes/intelligence.py     # Revenue, analytics, image browser, thumbnails
  api/routes/lightroom.py        # LR sync
  api/routes/content.py          # Calendar, hashtags, pillars
  api/routes/inspiration.py      # Concepts, locations
  api/routes/portfolio.py        # Genre portfolio curation
  api/routes/print.py            # Print opportunities
  core/config.py                 # Pydantic settings (reads .env)
  core/database.py               # SQLite connection, schema, migrations
  core/ollama.py                 # Ollama client (vision_json, text_json)
  pipeline/pass0_metadata.py     # EXIF extraction
  pipeline/pass1_cull.py         # Multi-signal cull scoring (CPU only)
  pipeline/pass2_nima.py         # 4-signal ensemble scoring (GPU + CPU)
  pipeline/pass3_tag.py          # Vision tagging (qwen2.5vl:32b), 600s timeout
  pipeline/queue_manager.py      # Job dispatcher, waterfall, _auto_promote
  pipeline/priority_queue.py     # Priority session management
  pipeline/watcher.py            # Folder watchdog (watchdog lib)
  pipeline/preprocessor.py       # Image resize for LLM
  services/caption_gen.py        # AI caption generation
  services/grid_aesthetic.py     # Instagram grid scoring
  services/pixieset_sync.py      # Pixieset catalog sync
  services/post_scheduler.py     # Auto-post (900s interval)
  dashboard/ui/index.html        # Single-page dashboard (all tabs + JS + CSS)
  models/                        # Downloaded model weights (LAION MLP)
  logs/                          # Per-service .log and error.log files
  launchd/                       # launchd plist files
```

---

## .env Config (`~/lens/.env`)

```
LENS_DB_PATH=/Volumes/8TB/claudes selects/lens/data/lens.db
PHOTO_WATCH_PATH=/Volumes/8TB/claudes selects/lens/incoming
LENS_API_PORT=8600
LENS_DASHBOARD_PORT=8800
OLLAMA_BASE_URL=http://localhost:11434
VISION_MODEL=qwen2.5vl:32b
TEXT_MODEL=qwen2.5:32b
PIPELINE_WORKERS=3
RESIZE_MAX_DIMENSION=1024
NIMA_THRESHOLD=5.5
BLUR_THRESHOLD=100.0
PHOTOGRAPHER_NAME=Steven
LOCATION=Hudson Valley, NY
GENRES=wedding,portrait,boudoir,commercial,events,nature
```

---

## Temp State Files

- `/tmp/lens_mode` — current mode (off/text/auto/priority)
- `/tmp/lens_priority_mode` — priority mode active flag
- `/tmp/lens_priority_state.json` — priority session metadata (folders, image_paths, started_at)
- `/tmp/lens_pipeline.pid` — pipeline process ID
- `/tmp/lens_maintenance` — maintenance mode flag (pauses all processing)

**None of these survive a reboot.** Re-enable after reboots if needed.

---

## Pipeline Architecture

### Waterfall — STRICTLY SEQUENTIAL

```
Pass 0  → Pass 1  → Pass 2  → Pass 3
(EXIF)    (cull)    (score)   (vision tag)
```

**ALL pass1 must finish before ANY pass2 starts. ALL pass2 before ANY pass3.** This is non-negotiable. Enforced in the `elif` chain in `queue_manager.py` AND in `_auto_promote()`. Reason: pass1/2 = CPU/GPU, pass3 = full GPU (20GB qwen2.5vl:32b). No resource fighting.

In **priority mode**, the waterfall only considers priority>=10 jobs — normal jobs don't block promotion.

### Pass Details

| Pass | File | Type | Timeout | Workers | What |
|------|------|------|---------|---------|------|
| pass0 | `pass0_metadata.py` | CPU | — | 1 | EXIF extraction (aperture, ISO, focal length, GPS, captured_at, season, time_of_day, creative_intent) |
| pass1 | `pass1_cull.py` | CPU | 120s | **6** | Multi-signal cull scoring. Produces cull_score 0-10. Dedup via perceptual hash. |
| pass1_raw | `pass1_cull.py` (async) | LLM | — | 1 | LLM salvage review for raw_review RAW files. NOT auto-pipeline. |
| pass2 | `pass2_nima.py` | **GPU (MPS)** | 120s | **2** | 4-signal ensemble: NIMA + LAION aesthetic + composition (8 sub-signals) + EXIF. Batched GPU inference. |
| pass3 | `pass3_tag.py` | LLM (async) | 600s | 1 | Vision tagging: genre, mood, quality_score, tags, description, composition, subjects, print_notes, etc. |
| privacy | `privacy_filter.py` | CPU | — | 1 | Face/boudoir detection and folder isolation |

**Batch sizes**: pass1/pass2 = 50 images, pass1_raw = 20, pass3 = 1 (10min/image).
**Max retry**: 3 attempts per job, then permanently skipped.

### Workers & Concurrency (`queue_manager.py`)

```python
_WORKERS = {"pass1": 6, "pass2": 2}  # all others default to 1
```

- `_db_write_lock` (threading.Lock) serializes all DB writes — prevents overlapping SQLite writes
- `_gpu_lock` (threading.Lock, in pass2) serializes GPU between pass2 workers — one does GPU while other does CPU composition
- Workers use `ThreadPoolExecutor` with `future.result(timeout=)` for thread-safe timeouts (no SIGALRM)

### Error Handling & Recovery

**Heartbeat system**: Each worker spawns a `_HeartbeatThread` that updates `heartbeat_at` on its running jobs every 30 seconds. This lets the watchdog distinguish stuck jobs (heartbeat stopped) from slow-but-alive ones (heartbeat fresh).

**Stuck job watchdog** (`_reset_stuck_jobs()`):
- Jobs with heartbeat: stuck if `heartbeat_at` > 5 minutes old (worker stopped sending)
- Jobs without heartbeat (legacy): stuck if `started_at` > 15 minutes old
- Stuck jobs reset to `queued` and logged to `error_log`

**Error logging**: All errors written to `error_log` table (not just `pipeline_jobs.error`):
- Per-job errors: image processing failures, timeouts
- Worker crashes: severity=critical, includes which batch was affected
- System events: startup recovery (stale job clearing), pass3 timeouts, stuck job resets

**Startup recovery**: On boot, all `running` jobs reset to `queued` (worker crash recovery). Event logged to `error_log`.

**Health endpoint** (`GET /pipeline/health`):
- Returns `green` / `yellow` / `red` status with reason
- Red: pipeline down, critical errors, stuck jobs
- Yellow: errored jobs, elevated error rate
- Green: all normal
- Dashboard shows health bar on Pipeline tab + status dot on Overview tab

**Error visibility**:
- Dashboard Pipeline tab: health bar (green/yellow/red) + expandable error log
- Each error can be individually resolved or bulk-resolved
- Overview tab: system status dot reflects pipeline health

---

## Pass 1 — Multi-Signal Cull Scoring

**File**: `pipeline/pass1_cull.py`
**Type**: CPU only, no GPU
**Output**: `cull_score` (0-10), `cull_sub` (JSON dict of 7 sub-scores)

### 7 Sub-Signals with Weights

| Signal | Weight | What it measures |
|--------|--------|------------------|
| `zone_sharpness` | 0.30 | 5x5 grid Laplacian variance. Face zones weighted 1.2x higher via Haar cascade detection. |
| `edge_density` | 0.15 | Canny edge percentage. Face-aware subject area measurement. |
| `frequency_ratio` | 0.10 | FFT high vs low frequency energy — detects detail vs blur at frequency level. |
| `highlight_clip` | 0.15 | % pixels at 250-255 (harsh highlight clipping). |
| `shadow_clip` | 0.10 | % pixels at 0-5 (shadow crush). More lenient than highlights. |
| `dynamic_range` | 0.10 | Histogram spread (1st-99th percentile). |
| `noise` | 0.10 | Median absolute deviation of Laplacian × 1.4826. |

### Cull Thresholds

| Score | Result |
|-------|--------|
| >= 4.5 | **pass** — promotes to pass2 |
| 3.0 - 4.5 | **raw_review** (RAW files only) — queues for LLM salvage review |
| < 3.0 | **fail** — culled permanently |

### Other Features

- **Blank frame detection**: std < 5.0 → auto-fail
- **Perceptual hash dedup**: `_load_phash_cache()` preloads all passed image hashes into memory dict (one DB read per batch, not per image). `find_duplicate()` checks cache.
- **Face detection**: Haar cascade (`haarcascade_frontalface_default.xml`), shared between zone_sharpness and edge_density
- **RAW file support**: ARW, CR2, CR3, NEF, RAF, DNG, ORF, RW2, PEF decoded via `rawpy` with `half_size=True`

### DB Columns Written

`pass1_status`, `pass1_at`, `blur_score`, `exposure_score`, `is_duplicate`, `duplicate_of`, `cull_score`, `cull_sub`, `highlight_clipping`, `shadow_clipping`, `noise_estimate`, `phash`

---

## Pass 2 — 4-Signal Ensemble Scoring

**File**: `pipeline/pass2_nima.py`
**Type**: GPU (MPS) + CPU
**Output**: `nima_technical`, `nima_aesthetic`, `nima_composite` (all 0-10 scale)

### Signal 1: Technical Quality (30% of composite)
- **Model**: pyiqa `nima-vgg16-ava` — VGG16 backbone trained on AVA dataset (255k human-rated photos)
- **What it measures**: Sharpness, noise, exposure correctness, distortion
- **Weights**: Auto-cached at `~/.cache/torch/hub/pyiqa/NIMA_VGG16_ava-dc4e8265.pth`
- **Inference**: Batched — `_batch_nima()` stacks all tensors, single forward pass per batch

### Signal 2: Aesthetic Quality (35% of composite)
- **Model**: LAION Aesthetic Predictor V2 — CLIP ViT-L/14 (frozen) + MLP head (768→1024→128→64→16→1)
- **Weights**: `~/lens/models/sac_logos_ava1_l14_linearMSE.pth` (MLP) + CLIP auto-cached by `open_clip_torch`
- **What it measures**: Composition appeal, mood, visual interest, color harmony
- **Trained on**: SAC + LAION-Logos + AVA (human aesthetic preferences at massive scale)
- **Inference**: Batched — `_batch_aesthetic()` stacks tensors, single CLIP forward pass
- **Completely independent from Signal 1** — different model, different training data

### Signal 3: Composition (20% of composite)
Pure OpenCV, no model. **8 sub-signals**:

| Sub-Signal | Method | Cost |
|------------|--------|------|
| S1 Thirds | Spectral residual saliency → centroid vs 1/3 intersections | ~2ms |
| S2 Golden Ratio | Phi-line intersections + best of 4 spiral orientations | ~5ms |
| S3 Color Harmony | K-means CIELab clustering vs harmony templates | ~15ms |
| S4 Visual Balance | Quadrant entropy comparison | ~3ms |
| S5 Symmetry | SSIM horizontal + vertical flip (scikit-image) | ~8ms |
| S6 Visual Weight | Sobel edge center-of-mass + Hough leading lines convergence | ~15ms |
| S7 Face Placement | Haar cascade + distance to golden ratio / thirds power points | ~10ms |
| S8 DOF/Bokeh | Laplacian variance ratio (subject vs background) | ~3ms |

**Two weighting profiles** (auto-selected by face detection):
- **Faces detected**: face_placement 25%, golden_ratio 15%, dof 15%, thirds 10%, harmony 10%, visual_weight 10%, balance 8%, symmetry 7%
- **No faces**: thirds 18%, golden_ratio 18%, harmony 15%, balance 15%, visual_weight 15%, symmetry 12%, dof 7%

**Composition notes**: Max 3 actionable suggestions per image stored in `composition_notes` (JSON array). Examples:
- "Stronger composition if flipped horizontally — subject aligns better with golden spiral"
- "Crop 8% from left to place face on power point"
- "Subject and background have similar sharpness — wider aperture would add separation"

### Signal 4: EXIF Bonus (15% of composite)
- **JPG/PNG/TIF** (human-curated exports): Flat **7.5** score (curation proxy — if you exported it, you liked it)
- **RAW files**: Base 5.0 + aperture bonus (f/4-f/8 = +2.5) + ISO bonus (≤400 = +2.5, scaled penalties up to ISO 6400+)
- Reads `aperture` and `iso` columns already populated by pass0

### Composite Formula

```
nima_composite = clamp(
    (nima_technical × 0.30) +
    (nima_aesthetic × 0.35) +
    (composition   × 0.20) +
    (exif_bonus    × 0.15),
    0, 10
)
```

### Performance

- **~0.68s/image** steady-state (after one-time ~9s model load)
- **~900MB GPU** for both models (NIMA + CLIP). No conflict with qwen2.5vl:32b (20GB) since pass2 and pass3 never run simultaneously (waterfall).
- GPU batching: 2 forward passes per batch of 50 instead of 100 individual calls

### DB Columns Written

`nima_technical`, `nima_aesthetic`, `nima_composite`, `pass2_at`, `score_composition`, `score_exif`, `composition_notes`, `composition_sub`

---

## Pass 3 — Vision Tagging

**File**: `pipeline/pass3_tag.py`
**Type**: LLM (async), qwen2.5vl:32b via Ollama
**Timeout**: 600s per image
**Speed**: ~580s/image (10 min)
**VRAM**: ~20 GB

### Tiered Promotion (pass2 → pass3)

`_auto_promote()` promotes by composite score:
- **>= 6.5** → pass3 at priority 10 (best photos, processed first)
- **6.0 – 6.5** → pass3 at priority 3 (decent photos, overnight batch)
- **< 6.0** → never promoted (not worth 10min GPU time — viewable in Images tab "Pass3 Skipped" filter, manually rescuable via "Rescue → P3" button)

### Score Interpretation

| Composite | Meaning |
|-----------|---------|
| 7.5+ | Exceptional — portfolio/print candidate |
| 6.5 – 7.5 | Strong — post-worthy |
| 5.5 – 6.5 | Solid — decent bulk of shoots |
| 4.5 – 5.5 | Weak — skip (no pass3) |
| < 4.5 | Bad — cull (no pass3) |

### DB Columns Written

`genre`, `mood`, `lighting`, `subject_type`, `faces_present`, `face_count`, `color_palette`, `setting`, `quality_score`, `portfolio_worthy`, `content_ready`, `tags`, `caption_draft`, `pass3_at`, `description`, `composition`, `subjects`, `print_notes`, `technical_issues`, `emotional_impact`

---

## Mode System

| Mode | What runs | AI/LLM? |
|------|-----------|---------|
| **off** | Pass1 + Pass2 only | No |
| **text** | Text model loaded (qwen2.5:32b) | Text only |
| **auto** | All passes including pass3 | Yes (vision) |
| **priority** | Only priority>=10 jobs, full waterfall | Yes |

- Endpoint: GET/POST `/social/mode` and `/social/mode/{mode}`
- Priority mode is manually activated — processes priority=10 jobs through the full waterfall before anything else.

---

## Priority System

### Priority Levels
- **10** = Priority folder (e.g. Poets Walk) — processed first
- **5** = Normal pass1/pass2
- **4** = Normal pass3
- **3** = Privacy / low-tier pass3

`_fetch_batch()` always uses `ORDER BY priority DESC` so priority-10 jobs go first within each pass.

### Priority Mode

When `/tmp/lens_priority_mode` exists, **ALL passes** only process `priority >= 10` jobs. Regular images are completely skipped.

```bash
# Via API
curl -X POST http://localhost:8600/pipeline/priority/start \
  -H "Content-Type: application/json" \
  -d '{"folder_path": "/path/to/folder"}'

curl -X POST http://localhost:8600/pipeline/priority/cancel
```

---

## Maintenance Mode

Pauses all processing without fighting launchd:

```bash
touch /tmp/lens_maintenance
# or: curl -X POST http://localhost:8600/pipeline/maintenance/enable

rm /tmp/lens_maintenance
# or: curl -X POST http://localhost:8600/pipeline/maintenance/disable
```

Pipeline loop sleeps every 10 seconds doing nothing. Service stays alive, launchd is happy.

**Always use maintenance mode before system work** instead of trying to stop the pipeline.

---

## Ollama / LLM Management

### Models

| Model | Purpose | VRAM |
|---|---|---|
| `qwen2.5vl:32b` | Pass 3 vision tagging, Pass 1 RAW review | ~20 GB |
| `qwen2.5:14b` | Text tasks (captions, analysis) | ~9 GB |

### Context Window

`num_ctx=2048` (set in `core/ollama.py`). Do NOT increase — at higher values it bloats to 57GB+ and causes swap hell.

### Unloading

```bash
# Force unload
curl -X POST http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5vl:32b","keep_alive":0,"prompt":""}'

# Nuclear option
launchctl kickstart -k gui/$(id -u)/com.lens.ollama
```

The 32b loads itself whenever pass3 or pass1_raw jobs are ready. This is correct, not a bug.

---

## Dashboard Tabs

1. **Overview** — stats, today's post, mode buttons
2. **Calendar** — day/week/month schedule, IG/Pixieset status, candidate pool
3. **Pipeline** — pass progress, queue counts, LLM status
4. **Images** — paginated browser with filters (genre, mood, portfolio, RAW review, Pass3 Skipped, quality slider). "Pass3 Skipped" shows images below 6.0 composite with "Rescue → P3" button to manually queue for vision tagging.
5. **Clients** — client list, search
6. **Bookings** — kanban pipeline (inquiry→booked→shot→editing→delivered→complete)
7. **Content** — queue, calendar sub-tab, hashtags
8. **Priority** — priority mode controls, per-pass progress bars with % completion, culled breakdown, score tier breakdowns per pass

### Priority Tab — Score Tier Breakdowns

Each pass shows a tier breakdown alongside progress:
- **Pass 1**: 8+ (green) | 6-8 (yellow) | 4.5-6 (orange) | <4.5 (red)
- **Pass 2**: 7+ (green) | 6-7 (yellow) | 5-6 (orange) | <5 (red)
- **Pass 3**: 6.5+ (green) | 5.5-6.5 (yellow) | 5-5.5 (orange) | <5 (red)

API endpoint: `GET /pipeline/priority/status` returns `pass1_tiers`, `pass2_tiers`, `pass3_tiers` objects.

---

## Key API Endpoints

```
GET  /pipeline/priority/status        # Priority progress (per-pass counts + tiers)
POST /pipeline/priority/start         # Start/append priority session
POST /pipeline/priority/cancel        # Cancel priority, downgrade jobs
GET  /pipeline/queue-counts           # Queued jobs per pass type
GET  /pipeline/stats                  # Total images, pass completion counts
GET  /pipeline/health                 # Health check: green/yellow/red + heartbeat, errors, stuck jobs
GET  /pipeline/errors                 # Recent errors (filterable: ?severity=critical&resolved=false)
POST /pipeline/errors/{id}/resolve    # Mark single error resolved
POST /pipeline/errors/resolve-all     # Mark all errors resolved
GET  /pipeline/llm/current            # Currently running LLM job
POST /pipeline/llm/unload             # Force model unload
POST /pipeline/scan                   # Scan folder & queue
POST /pipeline/rescue/{image_id}      # Manually queue below-threshold image for pass3

GET  /social/mode                     # Current mode
POST /social/mode/{mode}              # Switch mode
GET  /social/schedule?view=week       # Calendar week view
GET  /social/candidates               # Images for calendar filling

GET  /api/v1/images?page=1&limit=50   # Image browser (filters: genre, mood, pass1_status, etc.)
GET  /api/v1/images/{id}/thumb        # Thumbnail (800px, handles RAW via rawpy)

GET  /crm/clients                     # Client list
GET  /crm/bookings                    # Booking list
```

---

## Database Schema

### Tables

`images`, `pipeline_jobs`, `error_log`, `shoots`, `bookings`, `clients`, `client_profiles`, `galleries`, `gallery_images`, `calendar_posts`, `concepts`, `locations`, `import_logs`, `licenses`, `oauth_tokens`, `overnight_reports`, `print_sales`, `sequence_reminders`, `shoot_briefs`, `vendors`

### `images` Table — Key Columns

**Identity & metadata (pass0)**:
`id`, `file_path`, `file_name`, `shoot_id`, `imported_at`, `captured_at`, `season`, `time_of_day`, `aperture`, `shutter_speed`, `iso`, `focal_length`, `lens_model`, `camera_body`, `flash_fired`, `orientation`, `creative_intent`, `exposure_compensation`, `white_balance`, `gps_lat`, `gps_lng`, `gps_location_name`

**Pass 1 — cull**:
`pass1_status` (pass/fail/duplicate/raw_review), `pass1_at`, `blur_score`, `exposure_score`, `is_duplicate`, `duplicate_of`, `phash`, `cull_score` (0-10), `cull_sub` (JSON), `highlight_clipping`, `shadow_clipping`, `noise_estimate`

**Pass 1 RAW review**:
`raw_potential` (yes/no), `raw_potential_notes`

**Pass 2 — scoring**:
`nima_technical`, `nima_aesthetic`, `nima_composite` (all 0-10), `pass2_at`, `score_composition` (0-10), `score_exif` (0-10), `composition_notes` (JSON array), `composition_sub` (JSON dict of 8 sub-scores)

**Pass 3 — vision tagging**:
`genre`, `mood`, `lighting`, `subject_type`, `faces_present`, `face_count`, `color_palette`, `setting`, `quality_score`, `portfolio_worthy`, `content_ready`, `tags`, `caption_draft`, `pass3_at`, `description`, `composition`, `subjects`, `print_notes`, `technical_issues`, `emotional_impact`

**Privacy**:
`identifiable`, `privacy_folder`, `privacy_at`

**Social & portfolio**:
`posted_at`, `posted_to`, `social_queue`, `grid_fit_score`, `grid_fit_reason`

**Lightroom sync**:
`trust_score`, `lr_rating`, `lr_pick`, `lr_keywords`, `lr_caption`, `lr_collections`, `lr_pick_flag`, `lr_color_label`, `lr_star_rating`, `lr_synced_at`

**Prints**:
`print_worthy`, `print_score`, `edition_title`, `edition_size`, `editions_sold`, `edition_retired`, `pixieset_product_id`, `print_tier`, `print_technique`, `print_location_name`, `print_first_sale_at`, `print_total_revenue`, `print_times_sold`, `pixieset_url`

**Retag**:
`retag_queued`, `retag_note`

### `pipeline_jobs` Table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Job ID |
| `job_type` | TEXT | pass0/pass1/pass1_raw/pass2/pass3/privacy |
| `shoot_id` | INTEGER | FK to shoots |
| `image_id` | INTEGER | FK to images |
| `status` | TEXT | queued/running/complete/error |
| `priority` | INTEGER | 3-10 (10=priority, 5=normal) |
| `attempts` | INTEGER | Retry count (max 3) |
| `error` | TEXT | Last error message |
| `queued_at` | DATETIME | When job was created |
| `started_at` | DATETIME | When processing began |
| `completed_at` | DATETIME | When processing finished |
| `heartbeat_at` | DATETIME | Last heartbeat from worker (updated every 30s while processing) |
| `worker_id` | INTEGER | Which worker (0-5) picked up this job |

### `error_log` Table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | INTEGER PK | Error ID |
| `timestamp` | DATETIME | When the error occurred |
| `source` | TEXT | pass1/pass2/pass3/system/watchdog |
| `severity` | TEXT | warning/error/critical |
| `job_id` | INTEGER | Related pipeline job (if applicable) |
| `image_id` | INTEGER | Related image (if applicable) |
| `message` | TEXT | Error description |
| `resolved` | BOOLEAN | Whether the error has been acknowledged |
| `resolved_at` | DATETIME | When it was resolved |

All migrations are additive (`ALTER TABLE ADD COLUMN`). Safe to re-run `init_db()`.

---

## Dependencies

**In `requirements.txt`**:
fastapi, uvicorn, python-dotenv, httpx, Pillow, opencv-python-headless, imagehash, watchdog, torch, torchvision, numpy, scipy, aiofiles, pydantic, pydantic-settings, exifread, geopy, reverse_geocoder

**Installed but not in requirements.txt** (add if doing a fresh install):
`open_clip_torch` (3.3.0), `pyiqa` (0.1.15), `rawpy` (0.26.1), `scikit-image` (0.26.0)

---

## Common Diagnostics

### Check queue state
```bash
/Users/stevenhoward/lens/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/Volumes/8TB/claudes selects/lens/data/lens.db')
rows = conn.execute('SELECT job_type, status, COUNT(*) FROM pipeline_jobs GROUP BY job_type, status ORDER BY job_type, status').fetchall()
for r in rows: print(f'{r[0]:12s} {r[1]:10s} {r[2]}')
"
```

### Check priority progress
```bash
/Users/stevenhoward/lens/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/Volumes/8TB/claudes selects/lens/data/lens.db')
rows = conn.execute('SELECT job_type, status, COUNT(*) FROM pipeline_jobs WHERE priority >= 10 GROUP BY job_type, status ORDER BY job_type, status').fetchall()
for r in rows: print(f'{r[0]:12s} {r[1]:10s} {r[2]}')
"
```

### Reset stuck running jobs (after a crash)
```bash
/Users/stevenhoward/lens/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/Volumes/8TB/claudes selects/lens/data/lens.db')
r = conn.execute(\"UPDATE pipeline_jobs SET status='queued', started_at=NULL WHERE status='running'\")
conn.commit()
print(f'Reset {r.rowcount} stuck jobs')
"
```

The pipeline startup also does this automatically on boot (clears all `running` → `queued`).

### Check system resources
```bash
top -l 1 -n 0 | head -12
sysctl vm.swapusage
ps -M -p $(pgrep -f queue_manager) | wc -l   # thread count
```

### Check pass coverage
```bash
curl -s http://localhost:8600/pipeline/stats | python3 -m json.tool
```

---

## Known Issues / Watch Out For

1. **Waterfall is non-negotiable.** Steven is very firm: ALL pass1 done before ANY pass2, ALL pass2 before ANY pass3. No overlap. Ever. In priority mode, the waterfall only considers priority>=10 jobs.

2. **Priority mode doesn't survive reboots.** `/tmp/lens_priority_mode` is cleared on reboot. Re-touch if needed.

3. **OpenCV can't decode RAW files.** Always use `rawpy` for ARW/CR2/CR3/NEF/RAF/DNG. `cv2.imread()` on a RAW returns None.

4. **32b context must stay at 2048.** Higher values cause 57GB+ memory bloat and swap hell on the 32GB machine.

5. **`/Volumes/8TB` is user-managed.** Do NOT scan, list, or modify anything under it without explicit permission. The DB path (`/Volumes/8TB/claudes selects/lens/data/`) is the only exception.

6. **Duplicate job prevention.** Any code that seeds jobs must check for existing jobs for the same `image_id` + `job_type` before inserting. Historical bug: bulk seed + priority start both created jobs = 2x duplicates.

7. **numpy float32 serialization.** When writing JSON to DB (composition_sub, cull_sub), wrap numpy values in `round(float(x), 2)`. Raw `np.float32` is not JSON serializable.

8. **Swap budget.** 32GB machine with ~1GB swap in normal operation. Pass1 at 6 workers + pass2 at 2 workers is the tested safe maximum. Don't increase workers without checking swap.

---

## Key Constants

```python
# pass1_cull.py
_CULL_PASS = 4.5          # cull_score >= this → pass
_CULL_RAW_REVIEW = 3.0    # RAW files between this and _CULL_PASS → raw_review
_FILE_TIMEOUT = 120       # seconds

# pass2_nima.py
_W_TECHNICAL = 0.30       # composite weight
_W_AESTHETIC = 0.35
_W_COMPOSITION = 0.20
_W_EXIF = 0.15
_FILE_TIMEOUT = 120

# queue_manager.py
_BATCH_SIZE = 50
_LLM_BATCH_SIZE = 20
_P3_BATCH_SIZE = 1
_POLL_INTERVAL = 5        # seconds
_WORKERS = {"pass1": 6, "pass2": 2}

# General
PRIORITY_HIGH = 10
PRIORITY_NORMAL = 5
MAX_ATTEMPTS = 3
NIMA_THRESHOLD = 5.5
Supported extensions: .jpg .jpeg .png .tif .tiff .cr2 .cr3 .nef .arw .raf .dng .orf .rw2 .pef
```

---

## Changelog

### 2026-04-09 — Major Pipeline Overhaul

- **Pass1 rewrite**: Replaced crude blur/exposure binary checks with 7-signal cull scoring (0-10). Zone-based face-aware sharpness, exposure clipping analysis, noise estimation, frequency analysis. Preloaded phash cache for batch dedup.
- **Pass2 rewrite**: Replaced broken single-model NIMA (untrained random weights) with 4-signal ensemble (real NIMA + LAION aesthetic + 8-signal composition + EXIF). Batched GPU inference (2 forward passes per batch instead of 100). Face-aware composition weighting profiles. Actionable composition notes.
- **EXIF curation proxy**: JPG/PNG/TIF get flat 7.5 EXIF score (human-curated export proxy).
- **Pass3 tiered promotion**: >= 6.5 → priority 10, 5.5-6.5 → priority 3, < 5.5 → never promoted.
- **Workers bumped**: pass1 from 2→4→6, pass2 stays at 2.
- **Dashboard**: Added score tier breakdowns for all 3 passes in Priority tab. Added completion percentage next to each progress bar.
- **Bug fixes**: 9,503 duplicate jobs, 13 stuck pass1 jobs, priority mode waterfall blocking, missing DB columns, numpy float32 serialization.
- **Full priority re-run**: 9,516 images reset and re-processing from scratch with new scoring systems.
- **Error handling system**: Heartbeat threads (30s updates), `error_log` table, health endpoint (green/yellow/red), dashboard health bar + error log panel, startup recovery logging, stuck job detection using heartbeat-aware watchdog (5min heartbeat timeout vs 15min legacy), worker_id tracking on jobs, per-error resolve/resolve-all via API and dashboard.
- **Pass3 floor raised to 6.0**: Images below 6.0 composite never auto-promoted to pass3. Viewable in Images tab "Pass3 Skipped" filter with "Rescue → P3" button for manual override.
- **Dashboard clock fixed**: Top-right corner now shows live ticking clock in Eastern time (was broken/stale).
