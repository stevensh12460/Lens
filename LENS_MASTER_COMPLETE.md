# LENS — Complete Master Document
## Photography Operating System + Restaurant Content App + Print Business
**Version 1.0 — Steven Howard — Hudson Valley, NY**
**Mac Studio M1 Max 32GB — Standalone — LENS sees all.**

---

## Document Map

This is the single source of truth for the entire LENS system.
Feed this document to Claude Code at the start of every build session.

| Section | What it covers |
|---|---|
| Part 1 — Core System | Architecture, hardware, tech stack, database schema, build order, all 34 features |
| Part 2 — Print Business | Landscape fine art prints, experimental photography, Pixieset store, idle processing, Pass 0 metadata |
| Part 3 — Restaurant App | Visual content subscription, The Origin Session, story extraction, client portal, operator dashboard |
| Part 4 — Claude Code Prompt | Session kickoff instructions, startup checklist, what to say to start each phase |

---

# LENS — Photography Operating System
## Master Specification Document
**Version 1.0 — Session Reference for Claude Code**

---

## What is LENS

LENS (Local Enrichment and Navigation System) is a fully self-contained photography business operating system built for and running exclusively on a Mac Studio M1 Max. It handles every aspect of a professional multi-genre photography business — lead generation, photo pipeline processing, client management, content creation, business intelligence, and creative inspiration — using local AI models with no cloud dependency and no external subscriptions.

The system is built by a solo developer with a production-grade background in autonomous systems (the Nikita Network trading system). Architecture philosophy mirrors that work: shared data layer, service-oriented design, autonomous background processing, and a unified dashboard surface.

**Core principle:** Every service writes to and reads from one SQLite database. Nothing is siloed. Intelligence compounds over time.

---

## Hardware

| Property | Value |
|---|---|
| Machine | Mac Studio |
| Chip | Apple M1 Max |
| RAM | 32GB unified memory |
| OS | macOS |
| Network | Standalone — no LAN dependency |
| Ollama endpoint | `localhost:11434` |
| Photo library | Local SSD (path configured in `.env`) |

**This machine runs LENS exclusively. It has no dependency on any other machine on the network. GGcomp (.237) and TheOmnissiah (.203) are separate systems running the Nikita trading stack and are never referenced in LENS code.**

---

## Models

| Model | Purpose | Approx VRAM |
|---|---|---|
| `qwen2.5vl:7b` | Vision — photo tagging, culling, privacy filter | ~5GB |
| `qwen2.5:14b` | Text — captions, briefs, concepts, CRM parsing | ~9GB |
| Both loaded simultaneously | Fits in 32GB with headroom | ~14GB total |

Both models run via Ollama on `localhost:11434`. Requests use the standard Ollama `/api/chat` endpoint with base64-encoded images for vision calls.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Backend framework | FastAPI |
| Database | SQLite (single file, shared across all services) |
| ORM | SQLModel or raw sqlite3 |
| Vision inference | Ollama API (`qwen2.5vl:7b`) |
| Text inference | Ollama API (`qwen2.5:14b`) |
| Image processing | Pillow, OpenCV |
| Quality scoring | NIMA (Neural Image Assessment) |
| Duplicate detection | imagehash (perceptual hashing) |
| Face detection | OpenCV DNN or RetinaFace |
| Folder watching | Watchdog |
| Service management | launchd (plist files in `~/Library/LaunchAgents/`) |
| Adobe integration | Lightroom Classic Lua SDK |
| Environment | Python venv (never system Python) |
| Frontend | FastAPI + Jinja2 templates or lightweight React |
| Dependency management | pip + requirements.txt |

**Never use `--break-system-packages`. Always use the project venv.**

---

## Project Structure

```
~/lens/
├── .env                          # Environment config (paths, ports, thresholds)
├── requirements.txt
├── venv/
│
├── core/
│   ├── database.py               # SQLite connection, schema init, shared session
│   ├── config.py                 # Loads .env, exposes all config values
│   └── ollama.py                 # Shared Ollama client — vision + text calls
│
├── pipeline/
│   ├── watcher.py                # Watchdog folder monitor — triggers on import
│   ├── pass1_cull.py             # Technical cull: blur, exposure, dedup
│   ├── pass2_nima.py             # NIMA quality scoring
│   ├── pass3_tag.py              # Vision model tagging (3 parallel workers)
│   ├── privacy_filter.py         # Face detection, boudoir segregation
│   ├── preprocessor.py           # Resize to 1024px before vision calls
│   └── queue_manager.py          # Job queue, worker pool, status tracking
│
├── services/
│   ├── portfolio.py              # Auto-curator — top 20 per genre
│   ├── social_queue.py           # Content-ready flagging
│   ├── caption_gen.py            # AI caption generator
│   ├── inspiration.py            # Concept generator + location bank
│   ├── shoot_brief.py            # Shoot day logistics engine
│   ├── repurpose.py              # Shoot reuse tracker
│   ├── revenue.py                # Revenue forecasting
│   ├── workload.py               # Post-production tracker
│   ├── licensing.py              # Commercial license tracker
│   ├── referral.py               # Referral network mapper
│   ├── style_tracker.py          # Aesthetic evolution analysis
│   ├── upsell.py                 # Print + product upsell engine
│   └── client_intel.py           # Client profile builder from email threads
│
├── crm/
│   ├── clients.py                # Client records + profiles
│   ├── bookings.py               # Booking management
│   ├── intake.py                 # Per-genre intake form logic
│   ├── contracts.py              # Contract templates per genre
│   ├── sequences.py              # Automated follow-up sequences
│   └── gallery.py                # Gallery delivery portal
│
├── content/
│   ├── calendar.py               # 30-day content calendar
│   ├── hashtags.py               # Hudson Valley location hashtag bank
│   ├── pillars.py                # 5 weekly content pillars config
│   └── seasonal.py               # Seasonal weighting logic
│
├── api/
│   ├── main.py                   # FastAPI app entry point — port 8600
│   ├── routes/
│   │   ├── pipeline.py           # Pipeline status, trigger, results
│   │   ├── portfolio.py          # Portfolio endpoints
│   │   ├── social.py             # Content calendar + caption endpoints
│   │   ├── crm.py                # Client + booking endpoints
│   │   ├── inspiration.py        # Concept generator endpoints
│   │   ├── intelligence.py       # Dashboard data endpoints
│   │   └── lightroom.py          # Lightroom plugin API endpoints
│   └── models.py                 # Pydantic request/response models
│
├── dashboard/
│   └── ui/                       # LENS dashboard frontend — port 8800
│
├── lightroom/
│   └── LENS.lrplugin/            # Lightroom Classic plugin
│       ├── Info.lua
│       ├── LensPlugin.lua         # Main plugin entry
│       ├── LensPanel.lua          # Sidebar UI panel
│       └── LensAPI.lua            # HTTP client to localhost:8600
│
└── launchd/
    ├── com.lens.core.plist        # FastAPI backend service
    ├── com.lens.watcher.plist     # Folder watcher service
    ├── com.lens.pipeline.plist    # Pipeline queue worker
    └── com.lens.ollama.plist      # Ollama keepalive (if needed)
```

---

## Service Ports

| Service | Port | Notes |
|---|---|---|
| LENS API (FastAPI) | `8600` | All internal service communication |
| LENS Dashboard | `8800` | Browser UI |
| Ollama | `11434` | Standard Ollama port |

---

## Database Schema

Single SQLite file at path defined in `.env` as `LENS_DB_PATH`.

### Core tables

```sql
-- Every image that enters the system
CREATE TABLE images (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path       TEXT UNIQUE NOT NULL,
    file_name       TEXT,
    shoot_id        INTEGER REFERENCES shoots(id),
    imported_at     DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Pass 1: technical cull
    blur_score      REAL,
    exposure_score  REAL,
    is_duplicate    BOOLEAN DEFAULT FALSE,
    duplicate_of    INTEGER REFERENCES images(id),
    pass1_status    TEXT,       -- 'keep' | 'reject' | 'review'
    pass1_at        DATETIME,

    -- Pass 2: NIMA scoring
    nima_technical  REAL,       -- 0-10
    nima_aesthetic  REAL,       -- 0-10
    nima_composite  REAL,       -- weighted average
    pass2_at        DATETIME,

    -- Pass 3: vision tagging
    genre           TEXT,
    mood            TEXT,
    lighting        TEXT,
    subject_type    TEXT,
    faces_present   BOOLEAN,
    face_count      INTEGER,
    color_palette   TEXT,
    setting         TEXT,
    quality_score   REAL,       -- 0-10, vision model assessment
    portfolio_worthy BOOLEAN,
    content_ready   BOOLEAN,
    tags            TEXT,       -- JSON array
    caption_draft   TEXT,
    pass3_at        DATETIME,

    -- Privacy
    identifiable    BOOLEAN,
    privacy_folder  TEXT,       -- path if segregated
    privacy_at      DATETIME,

    -- LR integration
    lr_pick_flag    TEXT,       -- 'pick' | 'reject' | 'unflagged'
    lr_color_label  TEXT,
    lr_star_rating  INTEGER,
    lr_synced_at    DATETIME,

    -- Social
    posted_at       DATETIME,
    posted_to       TEXT,       -- JSON array of platforms
    social_queue    BOOLEAN DEFAULT FALSE
);

-- Shoots / sessions
CREATE TABLE shoots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER REFERENCES clients(id),
    shoot_date      DATE,
    genre           TEXT,       -- 'wedding' | 'portrait' | 'boudoir' | 'commercial' | 'events' | 'nature'
    location        TEXT,
    location_id     INTEGER REFERENCES locations(id),
    notes           TEXT,
    total_images    INTEGER,
    delivered_at    DATETIME,
    gallery_url     TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Clients
CREATE TABLE clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    referred_by     INTEGER REFERENCES clients(id),
    referred_by_vendor INTEGER REFERENCES vendors(id),
    first_booked    DATE,
    last_booked     DATE,
    total_bookings  INTEGER DEFAULT 0,
    total_revenue   REAL DEFAULT 0,
    notes           TEXT,
    preferences     TEXT,       -- JSON: style prefs, comfort notes, etc.
    anniversary     DATE,
    birthday        DATE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Bookings
CREATE TABLE bookings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER REFERENCES clients(id),
    shoot_id        INTEGER REFERENCES shoots(id),
    genre           TEXT,
    booked_date     DATE,
    shoot_date      DATE,
    package         TEXT,
    package_tier    TEXT,       -- 'essential' | 'signature' | 'premium'
    amount          REAL,
    deposit_paid    BOOLEAN DEFAULT FALSE,
    balance_paid    BOOLEAN DEFAULT FALSE,
    status          TEXT,       -- 'inquiry' | 'booked' | 'shot' | 'editing' | 'delivered' | 'complete'
    source          TEXT,       -- 'website' | 'referral' | 'instagram' | 'google' | etc.
    source_detail   TEXT,
    contract_signed BOOLEAN DEFAULT FALSE,
    intake_complete BOOLEAN DEFAULT FALSE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Content calendar
CREATE TABLE calendar_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_date       DATE,
    pillar          TEXT,       -- 'transformation' | 'genre_spotlight' | 'bts' | 'social_proof' | 'personality'
    genre           TEXT,
    format          TEXT,       -- 'reel' | 'carousel' | 'single' | 'story'
    concept         TEXT,
    caption         TEXT,
    hashtags        TEXT,       -- JSON array
    image_id        INTEGER REFERENCES images(id),
    shoot_id        INTEGER REFERENCES shoots(id),
    status          TEXT DEFAULT 'planned', -- 'planned' | 'ready' | 'scheduled' | 'posted'
    posted_at       DATETIME,
    likes           INTEGER,
    saves           INTEGER,
    shares          INTEGER,
    comments        INTEGER,
    profile_visits  INTEGER,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Locations
CREATE TABLE locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    area            TEXT,       -- 'catskills' | 'hudson_valley' | 'rhinebeck' | etc.
    type            TEXT,       -- 'forest' | 'waterfall' | 'barn' | 'urban' | 'estate' | etc.
    address         TEXT,
    lat             REAL,
    lng             REAL,
    best_seasons    TEXT,       -- JSON array
    best_time_of_day TEXT,      -- 'golden_hour' | 'blue_hour' | 'midday' | 'any'
    golden_hour_notes TEXT,
    permit_required BOOLEAN DEFAULT FALSE,
    permit_notes    TEXT,
    vibe_tags       TEXT,       -- JSON array: 'moody' | 'romantic' | 'rustic' | etc.
    notes           TEXT,
    times_used      INTEGER DEFAULT 0
);

-- Shoot concepts / inspiration
CREATE TABLE concepts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT,
    genre           TEXT,
    season          TEXT,
    mood            TEXT,
    location_id     INTEGER REFERENCES locations(id),
    brief           TEXT,       -- full AI-generated brief
    wardrobe_notes  TEXT,
    lighting_notes  TEXT,
    props           TEXT,
    caption_angle   TEXT,
    source          TEXT,       -- 'ai_generated' | 'manual' | 'trending'
    used            BOOLEAN DEFAULT FALSE,
    shoot_id        INTEGER REFERENCES shoots(id),
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Commercial licenses
CREATE TABLE licenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER REFERENCES clients(id),
    shoot_id        INTEGER REFERENCES shoots(id),
    image_ids       TEXT,       -- JSON array
    usage_type      TEXT,       -- 'digital' | 'print' | 'broadcast' | 'unlimited'
    licensed_at     DATE,
    expires_at      DATE,
    renewal_amount  REAL,
    renewal_notified BOOLEAN DEFAULT FALSE,
    notes           TEXT
);

-- Vendors (for referral tracking)
CREATE TABLE vendors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    type            TEXT,       -- 'venue' | 'planner' | 'florist' | 'makeup' | etc.
    contact_name    TEXT,
    email           TEXT,
    phone           TEXT,
    referrals_sent  INTEGER DEFAULT 0,
    referrals_received INTEGER DEFAULT 0,
    notes           TEXT
);

-- Pipeline job queue
CREATE TABLE pipeline_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type        TEXT,       -- 'pass1' | 'pass2' | 'pass3' | 'privacy' | 'caption'
    shoot_id        INTEGER REFERENCES shoots(id),
    image_id        INTEGER REFERENCES images(id),
    status          TEXT DEFAULT 'queued', -- 'queued' | 'processing' | 'done' | 'failed'
    priority        INTEGER DEFAULT 5,
    attempts        INTEGER DEFAULT 0,
    error           TEXT,
    queued_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at      DATETIME,
    completed_at    DATETIME
);
```

---

## Build Order

Build in this sequence. Each item depends on the one above it.

### Phase 1 — Foundation (build first, everything depends on this)
| # | Item | Why first |
|---|---|---|
| 1 | `core/database.py` — schema init + connection | Every service needs this |
| 2 | `core/config.py` — `.env` loader | Every service needs this |
| 3 | `core/ollama.py` — shared Ollama client | Pipeline + all AI services need this |
| 4 | `api/main.py` — FastAPI skeleton | Services expose via this |
| 5 | launchd plists — core + watcher + pipeline | Keep services running |

### Phase 2 — Photo Pipeline (core value, run early)
| # | Item | Notes |
|---|---|---|
| 6 | `pipeline/preprocessor.py` | Resize to 1024px before any vision call |
| 7 | `pipeline/pass1_cull.py` | OpenCV blur + exposure + imagehash dedup |
| 8 | `pipeline/pass2_nima.py` | NIMA quality scoring |
| 9 | `pipeline/pass3_tag.py` | qwen2.5vl:7b, 3 workers, JSON output |
| 10 | `pipeline/privacy_filter.py` | Face detection + encrypted folder |
| 11 | `pipeline/queue_manager.py` | Job queue + worker pool |
| 12 | `pipeline/watcher.py` | Folder monitor → triggers pipeline |

### Phase 3 — Lead Generation (direct revenue impact)
| # | Item | Notes |
|---|---|---|
| 13 | Intake + quote generator widget | Embeddable, genre-aware flows |
| 14 | Pricing calculator | Interactive, feeds into intake |
| 15 | Website structure | Genre pages, boudoir private URL |

### Phase 4 — Content Engine
| # | Item | Notes |
|---|---|---|
| 16 | `content/calendar.py` | 30-day calendar, pillar system |
| 17 | `services/caption_gen.py` | qwen2.5:14b, image tags → captions |
| 18 | `services/social_queue.py` | Flags content-ready images |
| 19 | `services/inspiration.py` | Concept generator + location bank |
| 20 | `services/repurpose.py` | Shoot reuse tracker |

### Phase 5 — Adobe Integration
| # | Item | Notes |
|---|---|---|
| 21 | `api/routes/lightroom.py` | API endpoints for plugin |
| 22 | `lightroom/LENS.lrplugin/` | Lua plugin — thin HTTP client |

### Phase 6 — CRM + Bookings
| # | Item | Notes |
|---|---|---|
| 23 | `crm/clients.py` + `crm/bookings.py` | Core records |
| 24 | `crm/intake.py` + `crm/contracts.py` | Per-genre forms |
| 25 | `crm/sequences.py` | Automated follow-ups |
| 26 | `crm/gallery.py` | Self-hosted delivery portal |

### Phase 7 — Business Intelligence
| # | Item | Notes |
|---|---|---|
| 27 | `services/portfolio.py` | Top 20 per genre auto-curator |
| 28 | `services/revenue.py` | Forecasting vs seasonal norms |
| 29 | `services/workload.py` | Edit queue tracker |
| 30 | `services/shoot_brief.py` | Shoot day logistics engine |
| 31 | `services/client_intel.py` | LLM email parser → client profiles |
| 32 | `services/referral.py` | Referral network mapper |
| 33 | `services/upsell.py` | Print + product upsell engine |
| 34 | `services/licensing.py` | Commercial license renewal tracker |
| 35 | `services/style_tracker.py` | Aesthetic evolution analysis |

### Phase 8 — Dashboard
| # | Item | Notes |
|---|---|---|
| 36 | `dashboard/` — LENS UI | Unified view of everything, port 8800 |

---

## Full Feature List (34 items)

### Lead generation
| # | Feature | Priority |
|---|---|---|
| 01 | Smart intake + quote generator | Build now |
| 02 | Interactive pricing calculator | Build soon |

### Website
| # | Feature | Priority |
|---|---|---|
| 03 | Website structure + page architecture | Build now |
| 04 | Self-hosted client gallery portal | Build soon |
| 05 | Local SEO + blog strategy | Build later |

### Social + content
| # | Feature | Priority |
|---|---|---|
| 06 | 30-day content calendar app | Build now |
| 07 | AI caption generator | Build soon |
| 08 | Repurpose tracker | Build later |

### Photo pipeline
| # | Feature | Priority |
|---|---|---|
| 09 | Pass 1 — technical cull (OpenCV) | Automated |
| 10 | Pass 2 — NIMA quality scoring | Automated |
| 11 | Pass 3 — vision model tagging | Automated |
| 12 | Boudoir privacy filter | Automated |
| 13 | Portfolio auto-curator | Build soon |
| 14 | Social queue auto-feeder | Build soon |

### Adobe integration
| # | Feature | Priority |
|---|---|---|
| 15 | Lightroom Classic plugin (Lua) | Build soon |
| 16 | Core Python organizer service | Build now |

### CRM + bookings
| # | Feature | Priority |
|---|---|---|
| 17 | Per-genre intake + contracts | Build soon |
| 18 | Automated follow-up sequences | Build soon |
| 19 | Client intelligence profiles | Build soon |
| 20 | Referral network mapper | Build soon |

### Inspiration engine
| # | Feature | Priority |
|---|---|---|
| 21 | AI concept generator | Build soon |
| 22 | Hudson Valley location bank | Build soon |
| 23 | Trending aesthetic auditor | Build later |
| 24 | Gap-aware concept suggestions | Build soon |

### Business intelligence
| # | Feature | Priority |
|---|---|---|
| 25 | LENS dashboard | Build now |
| 26 | Revenue forecasting | Build soon |
| 27 | Shoot day logistics engine | Build soon |
| 28 | Post-production workload tracker | Build soon |
| 29 | Style evolution tracker | Build later |
| 30 | Print + product upsell engine | Build soon |
| 31 | Commercial licensing tracker | Build later |
| 32 | Social-to-shoot feedback loop | Build later |

### Pricing
| # | Feature | Priority |
|---|---|---|
| 33 | Tiered packages per genre | Build later |
| 34 | Add-on menu | Build later |

---

## Photography Genres

The system recognizes these genres throughout. Use these exact strings everywhere.

`wedding` `portrait` `boudoir` `commercial` `events` `nature`

Boudoir is treated as a special case in all privacy, content, and intake logic.

---

## Content Pillars (Weekly Rotation)

| Day | Pillar | Description |
|---|---|---|
| Monday | `transformation` | Before/after edits, color grade breakdowns, how-I-shot-this |
| Tuesday | `genre_spotlight` | Rotates through all 6 genres on a 6-week cycle |
| Wednesday | `bts` | Behind the scenes — location, gear setup, editing process |
| Thursday | `social_proof` | Testimonials, session recaps, what-it's-like-to-book |
| Friday | `personality` | Your voice, opinions, local scenery, background story |

---

## Pipeline Processing Notes

- **Always resize to 1024px longest edge** before any vision model call. Never send 42MP RAW exports to Ollama.
- Use Pillow for resize: `Image.thumbnail((1024, 1024), Image.LANCZOS)`, save as JPEG quality 85.
- Pass 1 runs on CPU — no GPU needed, no Ollama call.
- Pass 2 uses Metal GPU via PyTorch MPS backend on Apple Silicon: `device = torch.device("mps")`.
- Pass 3 uses 3 parallel asyncio workers hitting Ollama concurrently.
- Pass 3 prompt must request structured JSON output — genre, mood, lighting, subject_type, faces_present, face_count, color_palette, setting, quality_score (0-10), portfolio_worthy (bool), content_ready (bool), tags (array).
- Privacy filter runs face detection on any image where `genre = 'boudoir'` OR `faces_present = true`.
- Encrypted boudoir folder path defined in `.env` as `BOUDOIR_PRIVATE_PATH`.

---

## Ollama Call Patterns

### Vision call (Pass 3 tagging)
```python
import ollama
import base64
from pathlib import Path

def tag_image(image_path: str) -> dict:
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()
    
    response = ollama.chat(
        model="qwen2.5vl:7b",
        messages=[{
            "role": "user",
            "content": TAGGING_PROMPT,
            "images": [image_data]
        }]
    )
    # Parse JSON from response
    return parse_json_response(response["message"]["content"])
```

### Text call (captions, briefs, concepts)
```python
def generate_caption(tags: dict, genre: str) -> str:
    response = ollama.chat(
        model="qwen2.5:14b",
        messages=[{
            "role": "user",
            "content": f"Write an Instagram caption for a {genre} photo. Tags: {tags}"
        }]
    )
    return response["message"]["content"]
```

---

## Environment Variables (.env)

```env
# Paths
LENS_DB_PATH=/Users/[username]/lens/data/lens.db
PHOTO_WATCH_PATH=/Volumes/[drive]/Photos/Incoming
BOUDOIR_PRIVATE_PATH=/Users/[username]/lens/private/boudoir
PORTFOLIO_EXPORT_PATH=/Users/[username]/lens/portfolio

# Ports
LENS_API_PORT=8600
LENS_DASHBOARD_PORT=8800

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
VISION_MODEL=qwen2.5vl:7b
TEXT_MODEL=qwen2.5:14b

# Pipeline
PIPELINE_WORKERS=3
RESIZE_MAX_DIMENSION=1024
NIMA_THRESHOLD=5.5
BLUR_THRESHOLD=100.0
EXPOSURE_LOW=0.05
EXPOSURE_HIGH=0.95

# Business
PHOTOGRAPHER_NAME=[your name]
BUSINESS_NAME=[business name]
LOCATION=Hudson Valley, NY
GENRES=wedding,portrait,boudoir,commercial,events,nature
```

---

## Naming Conventions

- Python files: `snake_case.py`
- Classes: `PascalCase`
- Functions: `snake_case`
- Database tables: `snake_case` (plural nouns: `images`, `shoots`, `clients`)
- API routes: `/api/v1/[resource]`
- Launchd labels: `com.lens.[service]`
- Lightroom plugin: `LENS.lrplugin`

---

## Session Instructions for Claude Code

When starting a new Claude Code session with this document:

1. Read this document fully before writing any code
2. All new code goes in `~/lens/` following the project structure above
3. Always activate the venv before running anything: `source ~/lens/venv/bin/activate`
4. Every service that touches images must call `preprocessor.py` first
5. All database access goes through `core/database.py` — never open SQLite directly
6. All Ollama calls go through `core/ollama.py` — never call the API directly from service files
7. Every new service gets a corresponding API route in `api/routes/`
8. Write launchd plists for any service meant to run persistently
9. Test each pass of the pipeline independently before wiring to the queue manager
10. The Lightroom plugin is Lua — keep it thin, all logic stays in Python

---

*LENS Master Spec v1.0 — generated from design session*
*Owner: Steven | Machine: Mac Studio M1 Max 32GB | Location: Hudson Valley, NY*

---

# LENS — Print Business Addendum
## Landscape Fine Art & Experimental Photography Revenue Stream
**Add this to the LENS Master Spec as a supplementary module**

---

## Overview

A passive print revenue stream built on top of the LENS photo pipeline. Experimental landscape photography — shot using motion techniques unavailable to most photographers — sold as fine art prints through Pixieset. Two-tier model: standard prints via automatic fulfillment, limited edition fine art prints via self-fulfillment through specialty labs.

This is a build-once, sell-forever revenue channel. The pipeline identifies print-worthy images automatically. The store handles fulfillment. The experimental technique creates a defensible visual signature nobody else in the Hudson Valley market is producing.

---

## The Visual Signature — What Makes These Prints Different

Standard Hudson Valley landscape photography is a crowded market. The differentiator here is a specific set of motion techniques that produce images impossible to replicate with a static tripod setup.

### Core technique — rotating camera on pivot arm

Camera mounted on a lightstand boom arm, pivoting around a central point. Camera shoots video or stills during the rotation. The physical movement of the camera through real space creates genuine parallax — objects at different distances move at different rates across the frame — which the human brain reads as volumetric three-dimensional depth. This cannot be replicated in post-processing.

**Why it creates 3D depth:** As the camera moves through space, near objects sweep past the frame quickly while distant objects barely move. The brain assembles these different movement rates into a perception of depth — the same reason telephone poles blur past while mountains barely move when driving. This is optical physics, not a filter.

### Equipment

| Item | Spec | Notes |
|---|---|---|
| Camera | Sony A7R III | 42MP — prints beautifully at 40x60in |
| Lens | G Master 35mm f/1.4 | At f/1.4 creates shifting focal plane during rotation |
| Stabilizer | DJI RS4 Mini | 2kg payload limit — A7R III + 35GM = ~1.5kg, within spec |
| Rotation rig | Lightstand + boom arm | Camera at end of arm, pivots around central point |
| Motor (optional) | Motorized pan head | Controlled repeatable rotation speed |

### Technique variations

**Long exposure orbit (primary)**
Slow shutter 1–4 seconds during rotation. Light sources trace circular arcs. Rooms become tunnels. Forests become vortices. Every frame unique and unrepeatable.

**f/1.4 focal plane sweep**
At f/1.4 the razor-thin depth of field sweeps through the scene as the camera rotates. Different elements are sharp at different points in the rotation. In a 2-second exposure you get a circular arc of relative sharpness surrounded by soft light — impossible to produce any other way.

**Strobe freeze mid-rotation**
Camera rotating, one strobe fires at a specific point. Background becomes motion blur circles. The strobe-frozen subject — a face, a hand, an object — floats sharp inside pure abstract motion. At 42MP the sharp element has full portrait-quality resolution embedded in an abstract image.

**Color vortex**
Colored gels on lights at different positions around the rotation path. Long exposure, full 360 rotation. Each colored source traces its own arc. Overlapping arcs create color mixing that doesn't exist in the scene — only in the exposure. Cyan where blue and green arcs cross. Magenta where red and blue meet.

**Turntable variant**
Camera locked central and stationary. Subject or object on a motorized turntable rotating in front of the lens. The world orbits the lens. Works for product photography (360 degree e-commerce spins) and experimental portrait.

**Dual rotation**
Subject on turntable rotating one direction. Camera on pivot arm rotating the other. Interference patterns emerge that are genuinely impossible to predict or replicate. Pure experimental — every frame is a discovery.

### Hudson Valley locations suited to this technique

| Location | Why it works |
|---|---|
| Old barn interior | Light rays through slats, dust particles, layered depth of beams |
| Catskill forest | Trees at varying distances create rich parallax layers, vortex effect |
| Waterfall | Moving water contrasts with frozen rotation geometry |
| Hudson riverfront at dusk | Water reflections become light arcs, horizon geometry curves |
| Shawangunk ridge | Strong linear geometry abstracts into curves |
| Narrow alleyways — Hudson, Rhinebeck | Architecture becomes impossible geometry |

### The A7R III advantage

42 megapixels means abstract long exposure images print at 40x60 inches with extraordinary tonal detail. Most photographers shooting abstract or experimental work use lower resolution cameras — the assumption being resolution doesn't matter for abstract images. Wrong. At large print sizes the tonal gradations, color transitions, and light behavior in a 42MP file produce a quality that justifies premium pricing. The same abstract image at 12MP is a social post. At 42MP it's a gallery piece.

---

## The Print Business Model

### Two-tier product structure

**Tier 1 — Standard prints (automatic fulfillment)**
Set up once, fully automated. Client orders, lab prints, ships directly to buyer. You never touch the product.

| Size | Suggested price | Target buyer |
|---|---|---|
| 8x10 | $75–$100 | Impulse buy, gift |
| 11x14 | $125–$175 | Apartment buyer |
| 16x20 | $250–$350 | Home decorator — main seller |
| 20x30 | $400–$550 | Statement piece, smaller home |

**Tier 2 — Fine art limited editions (self-fulfillment)**
Your experimental signature pieces. Numbered editions. Specialty paper. Premium pricing justified by the technique, the paper quality, and the scarcity.

| Size | Edition size | Suggested price | Paper |
|---|---|---|---|
| 20x30 | Edition of 25 | $500–$700 | Hahnemühle Photo Rag |
| 30x40 | Edition of 15 | $800–$1,100 | Canson Baryta Photographique |
| 40x60 | Edition of 10 | $1,200–$1,800 | Hahnemühle Photo Rag Baryta |

As editions sell down, remaining prints increase in value. Gives buyers a reason to purchase now. Creates genuine scarcity and perceived investment value.

**Tier 3 — 360 product spins (commercial, self-fulfillment)**
Turntable setup for commercial clients — jewelry, clothing, shoes, food, consumer goods. Delivered as video files or animated GIFs for e-commerce. Not print but same equipment, same session, additional revenue stream from commercial clients.

### Limited edition tracking in LENS

Add `edition_number`, `edition_size`, and `editions_sold` fields to the database. LENS tracks which prints are limited edition, how many have sold, and when to retire an edition. Automatically flags when an edition is 50% sold — prompt to raise price on remaining prints.

---

## Pixieset Store Setup

### Lab partners (North America)

| Lab | Ships to | Best for |
|---|---|---|
| WHCC (White House Custom Color) | USA, Canada, international | Standard prints, automatic fulfillment |
| ProDPI | USA, Canada, international | Premium standard prints |
| Miller's Professional Imaging | USA (all 50 states) | High volume standard prints |
| Self-fulfillment via Bay Photo or Mpix | Anywhere | Fine art limited editions |

### Store configuration

**Automatic fulfillment price sheet** — standard prints Tier 1. Set up once via WHCC or ProDPI. Zero commission on paid Pixieset plan. Fully hands-off.

**Self-fulfillment price sheet** — fine art limited editions Tier 2. Client orders through Pixieset. You receive notification. You print via Bay Photo, Loxley Colour, or directly via Epson archival printer. You ship. More work, full quality control, justified at premium price points.

**Important:** Only JPEG files supported for Pixieset print products. Export A7R III files as high quality JPEG before uploading. Full resolution — do not downsize, the 42MP is the product.

### Pricing philosophy

Your margin is the difference between lab cost and your selling price. Pixieset takes 0% on paid plans. Set prices that reflect the technique, the equipment, the location, and the scarcity — not just the lab cost. A 16x20 from WHCC costs roughly $15-25 depending on paper. Selling at $300 is a $275 margin. That's the math. Don't undersell.

---

## Sales Channels

### Primary — Pixieset store

Always on, automated, integrated into your client galleries. Every client who receives a gallery automatically sees your print store. Every landscape gallery is also a sales opportunity.

### Secondary channels

| Channel | Strategy | Effort |
|---|---|---|
| Instagram main account | Behind the scenes of experimental sessions drives print interest | Medium — content you're already making |
| TikTok | Process videos of rotating camera setups perform well — people love the how | Medium |
| Pinterest | Landscape images with location tags drive long-tail traffic for years | Low — pin once, works forever |
| Google Business Profile | Upload new prints weekly — GBP rewards fresh photo activity with better local ranking | Low — automated via LENS |
| Local galleries | Hudson, Rhinebeck, Woodstock, Beacon — consignment, typically 40-50% commission | Low effort, high credibility |
| Etsy | Reaches tourists and Hudson Valley visitors who want to take the landscape home | Low — separate from Pixieset |
| Interior designers | Wholesale buyers — one relationship = recurring revenue, no marketing required | Medium to build, low ongoing |
| Art fairs | Hudson Valley craft and art fair circuit — seasonal, direct sales, no commission | High effort but high volume days |

### The content engine that drives print sales

People who watch you make an image are significantly more likely to buy it than people who just see the finished result. Your video production background is the unfair advantage here. Behind the scenes of an experimental rotation session in a Catskill barn at dusk — that's a TikTok and Instagram Reel that builds the story of how the print was made. The print becomes the artifact of a process people witnessed. That emotional connection is what drives purchase decisions for art.

The LENS content calendar already manages this. Add a `print_campaign` flag to calendar posts — when you're running a push on a specific print, the calendar surfaces related BTS content, the caption generator writes copy that tells the story of the image, and the social queue auto-feeder pulls the hero image and supporting frames.

---

## LENS Database Additions for Print Business

Add these fields to the `images` table:

```sql
-- Print business fields
print_worthy        BOOLEAN DEFAULT FALSE,  -- vision model assessment
print_score         REAL,                   -- 0-10 composite print quality score
edition_title       TEXT,                   -- name for limited edition prints
edition_size        INTEGER,                -- total prints in edition (NULL = open edition)
editions_sold       INTEGER DEFAULT 0,      -- track remaining availability
edition_retired     BOOLEAN DEFAULT FALSE,  -- mark when edition is closed
pixieset_product_id TEXT,                   -- link to Pixieset store listing
tier                TEXT,                   -- 'standard' | 'fine_art' | 'commercial'
technique           TEXT,                   -- 'rotation' | 'turntable' | 'orbit' | 'standard'
location_name       TEXT,                   -- specific Hudson Valley location
first_sale_at       DATETIME,
total_revenue       REAL DEFAULT 0,
times_sold          INTEGER DEFAULT 0
```

Add a `print_sales` table:

```sql
CREATE TABLE print_sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id        INTEGER REFERENCES images(id),
    sale_date       DATETIME,
    size            TEXT,
    paper_type      TEXT,
    tier            TEXT,
    edition_number  INTEGER,
    sale_price      REAL,
    lab_cost        REAL,
    margin          REAL,
    channel         TEXT,   -- 'pixieset' | 'gallery' | 'art_fair' | 'direct'
    buyer_location  TEXT,
    notes           TEXT
);
```

---

## New LENS Services for Print Business

Add these to `~/lens/services/`:

**`services/print_curator.py`**
Queries vision model for print-worthiness assessment. Scores each landscape image on: tonal range, compositional strength, color palette cohesion, unusual perspective, large-format viability. Maintains `print_worthy` flag and `print_score` in the database. Feeds the Pixieset upload queue automatically.

**`services/edition_tracker.py`**
Tracks limited edition status. Alerts when editions reach 50% sold (prompt to raise price), 80% sold (prompt to publicize scarcity), and 100% sold (retire edition, archive for provenance). Generates edition certificates on request.

**`services/print_revenue.py`**
Aggregates print sales data. Reports margin per image, margin per technique, best-selling sizes, best-selling channels, revenue by month vs seasonal norms. Feeds the LENS dashboard.

**`services/gbp_print_push.py`**
Weekly upload of new `print_worthy` images to Google Business Profile via API. Fresh photos on GBP = better local search ranking. Automatic, zero effort after initial auth.

---

## LENS Dashboard Additions — Print Module

Add a Print Revenue panel to the LENS dashboard showing:

- Total print revenue this month vs last month
- Top selling images (by revenue and by units)
- Edition status — which limited editions are active, how many remain
- Pixieset store traffic (if API available)
- Upcoming art fair or gallery deadlines
- GBP photo upload status (last upload date)
- Images in print queue awaiting Pixieset upload

---

## Build Order Addition

Insert after Phase 7 (Business Intelligence), before Phase 8 (Dashboard):

**Phase 7b — Print Business Module**

1. Add print fields to `images` table schema
2. Create `print_sales` table
3. `services/print_curator.py` — vision model print scoring
4. `services/edition_tracker.py` — limited edition management
5. `services/print_revenue.py` — sales aggregation and reporting
6. `services/gbp_print_push.py` — Google Business Profile automation
7. `api/routes/print.py` — print module API endpoints
8. Dashboard print revenue panel

---

## The First Experimental Session — Action Plan

Before building any of this — go shoot.

**Location:** One Hudson Valley location with strong depth layers and interesting light. Old barn, forest clearing, waterfall, riverfront at dusk.

**Kit:** A7R III + 35mm GM + DJI RS4 Mini + lightstand + boom arm.

**Settings to start:** Manual mode, ISO 400, f/2.8, shutter 2 seconds. Get the behavior, then open to f/1.4.

**Session goal:** Not to get portfolio shots. To understand what the rotation does to light and geometry in this specific environment. Shoot 50-100 frames. Pull the files. Find the 2-3 that genuinely surprise you.

**The test:** Print one at 16x20 through Mpix (~$25). Put it on your wall. Live with it for a week. If you still love it after 7 days it's worth selling. That's your first Pixieset listing.

The business builds from that one print.

---

*LENS Print Business Addendum v1.0*
*Experimental landscape photography — Hudson Valley, NY*
*Sony A7R III + G Master 35mm f/1.4 + DJI RS4 Mini*

---

## Idle Processing System

### Philosophy

LENS processes the full 22TB library using idle Mac cycles. When you are working — Lightroom open, dashboard active, content generation running — the pipeline pauses or throttles. When the Mac sits idle the worker spins up and processes silently in the background. Every idle hour compounds the asset catalog. You wake up and LENS worked all night.

This is how macOS itself handles background work — Time Machine, Spotlight indexing, Photos analysis. LENS follows the same pattern.

### Idle detection

macOS exposes system idle time via IOKit. LENS checks it every 30 seconds and adjusts worker count accordingly.

```python
import subprocess
import time

def get_idle_seconds():
    result = subprocess.run(
        ['ioreg', '-c', 'IOHIDSystem'],
        capture_output=True, text=True
    )
    for line in result.stdout.split('\n'):
        if 'HIDIdleTime' in line:
            idle_ns = int(line.split('=')[-1].strip())
            return idle_ns / 1_000_000_000  # convert to seconds
    return 0

def should_process():
    idle = get_idle_seconds()
    if idle > 600:      # 10+ minutes idle
        return 'full'   # 3 workers, full speed
    elif idle > 120:    # 2+ minutes idle
        return 'throttled'  # 1 worker
    else:
        return 'pause'  # user is active, stop

# Main queue loop in queue_manager.py
while True:
    mode = should_process()
    if mode == 'full':
        run_workers(count=3, model='qwen2.5vl:32b')
    elif mode == 'throttled':
        run_workers(count=1, model='qwen2.5vl:32b')
    else:
        pause_workers()
    time.sleep(30)
```

### Priority queue tiers

LENS does not process the library as one flat queue. It stages work by priority so the most valuable images are always processed first.

| Priority | What | Model | When runs |
|---|---|---|---|
| 1 | Top 500 by NIMA score | qwen2.5vl:32b | Immediately — does not wait for idle |
| 2 | All Lightroom pick-flagged images | qwen2.5vl:32b | First idle window |
| 3 | Everything above NIMA threshold | qwen2.5vl:32b | Extended idle periods |
| 4 | Full library sweep | qwen2.5vl:7b (speed) | Deep idle only — nights, weekends |

Priority 4 is the one that eventually gets everything. It runs silently over weeks and months. Any image that surprises the 7B model — scoring unexpectedly high on quality or portfolio worthiness — gets flagged for a Priority 1 re-run with the 32B model.

### Realistic timeline on 22TB

| Tier | Images | Est. processing time |
|---|---|---|
| Priority 1 — top 500 | 500 | 45 min to 2 hours |
| Priority 2 — LR picks | ~5,000–10,000 | 3–8 hours idle spread across nights |
| Priority 3 — above NIMA threshold | ~60,000 | Several weeks of idle time |
| Priority 4 — full library | ~440,000+ | 2–3 months of consistent idle |

The business does not wait for completion. The moment Priority 1 is done LENS has enough to run the print store. The moment Priority 2 is done LENS has enough for the full content calendar. Everything after is compounding value added silently over time.

### Overnight processing report

Every morning LENS generates a one-page summary of what processed overnight. Displayed as the first panel on the LENS dashboard when you open it.

```
LENS overnight report — [date]
────────────────────────────────────────
Processed last 8 hours:     847 images
Priority 1 complete:        500 / 500  ✓
Priority 2 remaining:       3,241 images
Priority 3 remaining:       47,832 images
Priority 4 remaining:       ~440,000 images
Library coverage:           2.3%
New print candidates found: 23
New content-ready images:   61
Est. Priority 2 complete:   4 nights at current pace
```

This report is also delivered as a lightweight push notification or email summary if configured — you don't need to open the dashboard to know what LENS did while you slept.

### Queue manager additions to build

Add to `pipeline/queue_manager.py`:

- `get_idle_seconds()` — IOKit idle time detection
- `should_process()` — returns 'full', 'throttled', or 'pause'
- `PriorityQueue` class — manages the four tiers, always pulls from highest priority first
- `WorkerPool` — spawns and kills async workers based on mode
- `NightlyReport` — aggregates overnight stats, writes to database, surfaces on dashboard

Add to `api/routes/pipeline.py`:

- `GET /api/v1/pipeline/status` — current queue depth per tier, worker count, model loaded
- `GET /api/v1/pipeline/overnight` — last overnight report
- `GET /api/v1/pipeline/coverage` — library coverage percentage and projection

### The deployment note

**Do not add new features until the Priority 2 scan is complete.**

Let LENS process your Lightroom picks fully before extending the system. The scanned data tells you what you actually have — what genres dominate the library, which locations appear most, what quality distribution looks like across 22TB. That intelligence should inform every feature decision that follows. Build on real data, not assumptions.

Priority 1 scan complete → launch Pixieset store with top 500.
Priority 2 scan complete → launch full content calendar and social queue.
Priority 3 scan complete → launch themed collections and series.
Priority 4 scan complete → full business intelligence, complete asset catalog.

Each completion is a milestone that unlocks the next layer of the business. The system grows with the data.

---

*Idle Processing Addendum — added post 22TB library intake session*
*Process Priority 1 and 2 before adding any new LENS features*

---

## Pass 0 — Metadata Extraction

### Overview

Before any AI processing runs, LENS performs a full metadata extraction pass on every RAW file in the library. This pass costs almost nothing computationally — milliseconds per file, CPU only, no GPU, no Ollama — and pre-populates a huge portion of the database before a single vision model call is made.

By the time the vision model sees an image, LENS already knows when it was shot, potentially exactly where, what lens and settings were used, what season and time of day, whether it was part of a burst sequence, and what creative intent the photographer had based on aperture and shutter choices. The vision model then adds the subjective layer on top of this objective factual foundation.

**Add `pipeline/pass0_metadata.py` as the first step in the pipeline — before preprocessor, before Pass 1.**

---

### What is extracted

**From EXIF (embedded in every RAW file):**

| Field | What LENS does with it |
|---|---|
| DateTimeOriginal | Season, time of day, shoot grouping |
| GPSLatitude / GPSLongitude | Reverse geocode to location name |
| FNumber (aperture) | Creative intent inference |
| ExposureTime (shutter) | Motion intent inference |
| ISOSpeedRatings | Lighting condition context |
| FocalLength | Lens context |
| LensModel | Which lens was used |
| Make / Model | Camera body |
| BodySerialNumber | Track which body shot each image |
| Flash | Flash fired or not |
| MeteringMode | Exposure strategy |
| ExposureProgram | Manual vs auto |
| ExposureBiasValue | Exposure compensation |
| WhiteBalance | Lighting type intent |
| FileSequenceNumber | Burst grouping |
| Orientation | Portrait vs landscape |
| DriveMode | Single shot vs continuous |

**From XMP sidecar files (written by Lightroom):**

| Field | What LENS does with it |
|---|---|
| xmp:Rating | Star rating (1–5) — trusted human editorial signal |
| xmp:Label | Color label from Lightroom |
| xmp:Subject | Keywords manually added in Lightroom |
| dc:description | Caption if written in Lightroom |
| lr:pick | Pick / reject flag |
| GPano fields | Panorama metadata if applicable |
| GPS from Lightroom | Location data added manually in LR |

**From Lightroom catalog (.lrcat — SQLite database):**

| Data | What LENS does with it |
|---|---|
| Star ratings | Weighted trust signal — 4/5 star overrides AI quality score |
| Color labels | Maps to LENS workflow status |
| Pick flags | Seeds Priority 2 queue automatically |
| Collections | Pre-built groupings inform collection_fit field |
| Keywords | Pre-populates tags before vision model runs |
| Develop settings | Exposure adjustments signal intentional creative choices |
| Crop ratio | Portrait vs landscape intent |

---

### Automatic tagging from metadata alone

These fields are populated with zero AI involvement — pure metadata math.

```python
from datetime import datetime
from exifread import process_file

def get_season(month):
    if month in [12, 1, 2]:    return 'winter'
    elif month in [3, 4, 5]:   return 'spring'
    elif month in [6, 7, 8]:   return 'summer'
    else:                       return 'autumn'

def get_time_of_day(hour):
    if 5 <= hour <= 7:     return 'blue_hour_morning'
    elif 7 <= hour <= 9:   return 'golden_hour_morning'
    elif 9 <= hour <= 16:  return 'midday'
    elif 16 <= hour <= 19: return 'golden_hour_evening'
    elif 19 <= hour <= 21: return 'blue_hour_evening'
    else:                   return 'night'

def infer_creative_intent(aperture, shutter, focal_length):
    if shutter >= 1.0:
        return 'long_exposure_intentional'
    elif shutter <= 0.001:
        return 'motion_freeze'
    elif aperture <= 2.0:
        return 'shallow_dof_portrait_or_low_light'
    elif aperture >= 8.0 and focal_length <= 35:
        return 'landscape_deep_focus'
    else:
        return 'standard'

def group_bursts(images):
    # Images within 2 seconds of each other
    # with sequential file numbers = burst group
    # Keep highest NIMA score from each group
    ...
```

---

### GPS reverse geocoding

If GPS coordinates exist in EXIF or XMP, LENS reverse geocodes them to human-readable location names and attempts to match against the locations table.

```python
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

geolocator = Nominatim(user_agent="lens_photo_os")
reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)

def get_location_from_gps(lat, lng):
    location = reverse(f"{lat}, {lng}", language='en')
    address = location.raw.get('address', {})
    return {
        'town': address.get('town') or address.get('village'),
        'county': address.get('county'),
        'state': address.get('state'),
        'country': address.get('country_code'),
        'display': location.address
    }
```

Reverse geocoding is rate-limited to respect Nominatim's free API. For a 22TB library with GPS data this runs as a background job — not blocking the main pipeline. Alternatively use a local offline geocoder like `reverse_geocoder` Python package for zero rate limiting and no internet dependency.

---

### Lightroom catalog integration

The Lightroom Classic catalog is a SQLite database. LENS can query it directly — read-only, never modifying the catalog.

```python
import sqlite3

def read_lightroom_catalog(lrcat_path):
    conn = sqlite3.connect(lrcat_path)
    
    # Get all images with their ratings and pick status
    images = conn.execute('''
        SELECT 
            f.absolutePath,
            ai.rating,
            ai.colorLabels,
            ai.pick,
            ai.touchCount
        FROM AgLibraryFile f
        JOIN Adobe_images ai ON ai.rootFile = f.id_local
        WHERE ai.rating >= 3
        ORDER BY ai.rating DESC
    ''').fetchall()
    
    # Get keywords per image
    keywords = conn.execute('''
        SELECT 
            f.absolutePath,
            k.name
        FROM AgLibraryFile f
        JOIN AgLibraryKeywordImage ki ON ki.image = f.id_local  
        JOIN AgLibraryKeyword k ON k.id_local = ki.tag
    ''').fetchall()
    
    conn.close()
    return images, keywords
```

**Trust hierarchy for quality scoring:**

| Source | Trust level | Notes |
|---|---|---|
| LR 5-star rating | Highest | Your definitive best — always portfolio worthy |
| LR 4-star rating | Very high | Strong work — prioritize for print and content |
| LR pick flag | High | You selected it — seeds Priority 2 queue |
| NIMA score ≥ 8.0 | Medium-high | Objectively strong technical quality |
| Vision model quality_score ≥ 8.0 | Medium | AI assessment of overall quality |
| LR 3-star rating | Medium | Worth processing but not priority |
| No rating, above NIMA threshold | Low-medium | Unknown — let vision model decide |
| LR reject flag | Ignore | Never process — skip entirely |

A 5-star rating from Lightroom overrides any AI quality score. Your editorial judgment from years of shooting is the ground truth LENS defers to.

---

### Database additions for metadata

Add these fields to the `images` table:

```sql
-- Pass 0 metadata fields
captured_at          DATETIME,         -- exact capture timestamp from EXIF
season               TEXT,             -- 'spring' | 'summer' | 'autumn' | 'winter'
time_of_day          TEXT,             -- 'golden_hour_morning' | 'blue_hour_evening' etc.
aperture             REAL,             -- f-number
shutter_speed        TEXT,             -- '1/250' | '2"' etc.
iso                  INTEGER,
focal_length         REAL,             -- mm
lens_model           TEXT,
camera_body          TEXT,
body_serial          TEXT,
flash_fired          BOOLEAN,
orientation          TEXT,             -- 'landscape' | 'portrait'
drive_mode           TEXT,
creative_intent      TEXT,             -- inferred from settings
burst_group_id       INTEGER,          -- groups burst sequences together
burst_position       INTEGER,          -- position within burst
gps_lat              REAL,
gps_lng              REAL,
gps_location_name    TEXT,             -- reverse geocoded
gps_town             TEXT,
gps_county           TEXT,

-- Lightroom catalog fields
lr_rating            INTEGER,          -- 1-5 stars
lr_color_label       TEXT,
lr_pick              TEXT,             -- 'pick' | 'reject' | 'unflagged'
lr_keywords          TEXT,             -- JSON array from LR keyword tree
lr_caption           TEXT,             -- caption written in LR
lr_collections       TEXT,             -- JSON array of LR collection names

-- Derived trust score
trust_score          REAL              -- composite of LR rating + NIMA + vision score
```

---

### Pass 0 timing on 22TB

| Task | Time estimate |
|---|---|
| EXIF extraction — full library | 15–30 minutes (CPU only) |
| XMP sidecar reading — full library | 10–20 minutes |
| Lightroom catalog import | 5–10 minutes |
| Burst grouping | 5 minutes |
| GPS reverse geocoding (if GPS data present) | Runs as background job, hours |
| Season + time of day tagging | Included in EXIF pass |

**Total Pass 0 time: under 1 hour for the full 22TB library.**

After Pass 0 completes, LENS has structured metadata on every image in the library — before a single Ollama call, before NIMA scoring, before any GPU work. The priority queue can be built immediately from Lightroom pick flags and star ratings. Pass 1 can use burst group data instead of perceptual hashing for duplicate detection — more accurate, faster.

---

### Updated full pipeline order

```
Pass 0 — metadata extraction     (minutes, CPU, no AI)
         └── reads EXIF, XMP, LR catalog
         └── tags season, time of day, creative intent
         └── groups burst sequences
         └── imports LR ratings and keywords
         └── seeds priority queue from LR picks

Pass 1 — technical cull          (minutes, CPU, no AI)
         └── blur detection
         └── exposure analysis
         └── burst dedup (now uses Pass 0 burst groups)

Pass 2 — NIMA scoring            (minutes, Metal GPU, no AI)
         └── quality score per image
         └── combined with LR rating for trust score

         [your Lightroom manual cull if desired]

Pass 3 — vision model tagging    (hours, Ollama, overnight)
         └── qwen2.5vl:32b on priority images
         └── full semantic analysis
         └── knows season/location/lens from Pass 0
         └── uses LR keywords as priors
         └── generates captions, collection fits, print scores
```

---

### The compounding effect

Pass 0 metadata + Lightroom catalog + vision model analysis = the richest possible description of every image. Three layers of intelligence:

Layer 1 — objective facts from the camera itself. When, where, how it was shot.
Layer 2 — your editorial judgment from years of culling in Lightroom. What you thought was worth keeping.
Layer 3 — AI semantic understanding. What it looks like, what it means, what story it tells.

No commercial photo management software combines all three of these. LENS does. That's the asset catalog that comes out the other side of 22TB through this pipeline — not just tagged files, but a fully understood creative library.

---

*Pass 0 Metadata Addendum — added after 22TB library intake session*
*Run Pass 0 first — it costs nothing and makes every subsequent pass smarter*

---

# LENS — Restaurant Content App
## Visual Content Subscription Service for Food & Hospitality
**Standalone module — builds on LENS core infrastructure**

---

## The Concept

A full-service visual content subscription for restaurants, wineries, farms, and food businesses in the Hudson Valley. Not a photography retainer. Not a social media agency. Something new that combines both and is only possible because of a specific combination of skills — professional chef background, video production capability, AI pipeline, and photography.

The operator shows up. Shoots. Creates designed motion artwork. Manages the client's entire social presence from one app. The client gets a professional visual content operation at a fraction of what a full agency charges. The operator runs multiple clients simultaneously from one dashboard.

**The unfair advantage:** A chef background means real conversations with restaurant owners and chefs that a generic content person cannot have. They open up differently. The food knowledge is real. The credibility is earned. That trust is the foundation everything else is built on.

---

## What Clients Are Buying

Not photography. A complete visual content subscription with three components delivered monthly.

**Component 1 — Photography**
Monthly shoot. New dishes, seasonal menu items, team portraits, behind the scenes kitchen content, plating process, atmosphere shots, events. Delivered as a gallery of edited images the client owns and can use anywhere. Flows through LENS pipeline automatically.

**Component 2 — Designed Artwork**
Photographs become social assets. Instagram posts with typography, story templates, promotional graphics, menu card designs, event announcements, seasonal campaign visuals. Motion graphics for Instagram stories and Reels — animated menu reveals, short cinematic clips, After Effects motion design. Content that stops scrolling because it moves. This is the component no photographer and no generic agency delivers simultaneously.

**Component 3 — The App**
A client portal and operator dashboard managing the entire operation. Content queue, approval workflow, shoot scheduling, asset library, performance metrics, invoicing. The app is what makes managing multiple clients possible without drowning in email chains and missed messages.

---

## The Origin Session — Story Extraction

### Why this exists

Every restaurant has a story. Almost none of them tell it well. A generic social media agency writes copy that sounds like every other restaurant. The Origin Session extracts the real story — the specific true things that make this place different from every other place — and turns it into the content engine for everything that follows.

One 90-minute conversation generates enough narrative material to inform a year of content. The captions have depth because they're drawn from real things this person actually said. The brand voice is accurate because it's built from their actual words. The short documentary Reel uses their own voice. The about page sounds like them because it is them.

### The conversation

Not an interview. Not a questionnaire. A real conversation between two people who both understand the food world. The chef background is the entry point — restaurant owners and chefs talk differently to someone who has worked a line than to someone who has only eaten at tables.

**Territory to explore — not a script, a mental map:**

The origin — why this, why here, why now. What were you doing before. What made you decide.

The obsession — what's the thing you care about that most people don't understand. What do you know about your craft that your customers don't know. What are you trying to do that nobody else is doing.

The specific — one ingredient, one supplier, one technique, one detail you're proud of that most people walk past without noticing. The flour from a specific mill. The hillside that determined everything. The supplier relationship that took ten years to build.

The struggle — what was the hardest moment. What almost didn't work. What do you still worry about.

The future — where does this go. What are you building toward. What does success look like to you.

These territories emerge naturally in conversation. You don't ask them in order. You follow the thread when it appears. That instinct is not teachable — it comes from years in professional kitchens knowing what matters and what doesn't.

### Recording setup

Unobtrusive is the key word. Small recorder sits on the table. They mostly forget it's there.

| Option | Device | Cost | Notes |
|---|---|---|---|
| Dedicated recorder | Zoom H1n or Sony PCM-A10 | $100–200 | 24-bit quality, flat on table |
| Mobile setup | iPhone + Rode Wireless GO | $300 | Clip-on, nearly invisible |

**Always get verbal consent at the start:** "I'm going to record our conversation so I can make sure I capture everything accurately — is that okay with you?" Everyone says yes. One sentence. Professional and protective.

### Transcription — local Whisper model

Audio returns to the Mac. Local Whisper model transcribes it — completely private, never touches a cloud server. A 90-minute conversation transcribes in roughly 5-10 minutes on M1 Max.

```bash
# Install faster-whisper
pip install faster-whisper

# Transcribe
from faster_whisper import WhisperModel

model = WhisperModel("large-v3", device="auto")
segments, info = model.transcribe("conversation.m4a")

transcript = ""
for segment in segments:
    transcript += f"[{segment.start:.1f}s] {segment.text}\n"
```

Alternatively pull via Ollama if Whisper support is added:
```bash
ollama pull whisper
```

Output is a full text transcript with timestamps. Saved to the client's Story record in the database. Never leaves the Mac.

### LLM processing — chunked story extraction

A 90-minute conversation is 15,000–25,000 words. Too long for one context window even at 32B. Process in two passes.

**Pass 1 — chunk extraction**

Split transcript into 10–15 minute segments. Run each chunk through `qwen2.5:32b` with this prompt:

```python
CHUNK_PROMPT = """
You are reading a transcript of a conversation with a 
restaurant owner / chef / food business operator. 

Extract from this segment:
1. Key themes and values expressed
2. Memorable direct quotes (exact words, preserved)
3. Specific details — ingredients, suppliers, techniques, 
   places, people mentioned
4. Emotional moments — where they became animated, 
   uncertain, proud, or vulnerable
5. Story threads — beginnings of narratives that may 
   continue in other segments
6. Their natural voice — vocabulary, rhythm, how they 
   naturally describe things

Return as structured JSON. Preserve exact quotes verbatim.
Do not summarize — extract and preserve.

Transcript segment:
{chunk}
"""
```

**Pass 2 — story synthesis**

Feed all chunk extractions together. Ask the model to find the through-line.

```python
SYNTHESIS_PROMPT = """
You have received structured notes extracted from multiple 
segments of a 90-minute conversation with a food business 
operator. 

Your task is to synthesize these notes into a Story Brief — 
a 500-800 word narrative document that captures:

1. The central story arc — what is this person's journey
2. The core obsession — what drives them that others miss
3. The defining moment — the decision or experience that 
   changed everything
4. The specific details that make this place unlike any other
5. Their authentic voice — 3-5 direct quotes that capture 
   who they are
6. The emotional truth — what they care about underneath 
   the business

This Story Brief becomes the content foundation for 
everything created for this client. It should read as 
narrative, not bullet points. It should sound like them.

Extracted notes from all segments:
{all_chunk_notes}
"""
```

Output is the Story Brief — 500-800 words of rich narrative material. Saved to the client record. Informs every piece of content created for this client from this point forward.

### What the Story Brief generates

From one conversation and one Story Brief:

| Content piece | Format | Use |
|---|---|---|
| Brand story | 400–600 words | Website about page |
| Short documentary Reel | 60–90 seconds | Instagram, TikTok hero content |
| Origin story post series | 5–8 posts | Instagram feed, 6-8 week run |
| Pull quotes | Designed graphic assets | Instagram, story templates |
| Email welcome sequence | 3-part series | Newsletter onboarding |
| Press kit narrative | 300 words | Media pitches, PR |
| Venue description | 150 words | Google Business Profile, Yelp, booking platforms |

**The short documentary Reel** is the highest-value single output. Visuals from the shoot. Audio is their actual voice from the conversation — the most compelling 60 seconds, lightly edited. No voiceover, no script. Real voice, real images. This format outperforms produced content on every platform because it's authentic in a way no agency content ever is.

---

## Pricing Architecture

### Retainer tiers

| Tier | Monthly fee | What's included |
|---|---|---|
| Essential | $1,200/month | Monthly shoot (2hrs), 20 edited images, 8 designed posts, basic captions, portal access |
| Signature | $2,200/month | Monthly shoot (4hrs), 40 edited images, 20 designed posts + 4 Reels/motion pieces, AI captions in brand voice, full portal, performance report |
| Premium | $3,500/month | Monthly shoot (full day), unlimited edited images, 30 designed posts + 8 motion pieces, story series content, GBP management, email content, quarterly strategy session |

### Add-ons

| Add-on | One-time fee | Notes |
|---|---|---|
| The Origin Session | $750–$1,500 | 90-min conversation, transcription, Story Brief, documentary Reel, brand voice profile. Every new client should do this. |
| Brand identity package | $1,200–$2,500 | Template library, color system, typography, visual grid — one-time setup |
| Menu redesign | $500–$1,500 | Full menu designed using shoot photography |
| Event coverage | $800–$2,000 | Special events, pop-ups, openings — outside retainer scope |
| Press kit | $400 | Full press kit built from Story Brief + best photography |

### Revenue at scale

| Clients | Monthly | Annual |
|---|---|---|
| 3 clients (Signature) | $6,600 | $79,200 |
| 5 clients (Signature) | $11,000 | $132,000 |
| 8 clients (mixed tiers) | $17,600 | $211,200 |

Each client shoot is roughly one day per month. Artwork creation is 2-3 days per client. 5 clients is very manageable. 8 is a full operation.

---

## The App — Architecture

### Two sides

**Operator dashboard** — your command center. All clients in one view. Full control.

**Client portal** — their window into their content. Clean, simple, mobile-first. They approve, request, and download. Nothing more complicated than that.

### Operator dashboard features

**Client overview panel**
All clients in one grid. Each card shows: next shoot date, content queue depth, pending approvals, last post date, billing status. You see the state of every client relationship at a glance without clicking into anything.

**Shoot brief generator**
Input: client, date, location.
Output: complete shoot brief — what to shoot based on upcoming menu and events, shot list by category, golden hour time for that specific location and date, weather forecast, gear checklist, client-submitted special requests.
You walk into every shoot prepared. Nothing forgotten.

**Content calendar builder**
Drag and drop. Assign images from the shoot to post dates. Attach designed assets. Write or generate captions. Set platform. Submit for client approval. One workflow, repeatable across every client.

**Caption generator**
Powered by Ollama 32B. Inputs: image tags from LENS vision analysis, client brand voice profile, Story Brief excerpts, platform (Instagram vs Facebook vs TikTok), post type (promotional, story, behind the scenes). Output: caption written in the client's authentic voice drawing from their real story. You review and adjust. Client approves.

**Asset management**
All photography from LENS pipeline flows in automatically. Designed assets uploaded from After Effects and Premiere exports. Everything tagged, organized, searchable by client, date, content type.

**Performance dashboard**
Instagram and Facebook Graph API integration. Reach, impressions, engagement rate, follower growth, post-by-post performance. Pulled automatically. Available in both operator view (across all clients) and client portal (their data only).

**Invoicing**
Stripe integration. Monthly retainer charged automatically on the 1st. Add-on invoices generated and sent from the app. Payment status visible in the client card. No chasing. No awkward conversations.

**Overnight report**
Each morning the app surfaces what happened overnight — posts that went live, performance on recent posts, any client portal activity, upcoming shoots this week, invoices paid or outstanding.

### Client portal features

**Content queue**
Posts scheduled for the month displayed as cards. Each card shows the image or video, designed asset preview, caption, scheduled date, platform. One click to approve. One click to request changes with a note.

**Request form**
Special event coming up. New dish launching. Seasonal promotion. They submit through the portal — it appears in your operator dashboard immediately with full details. No text messages, no email chains.

**Asset library**
Every image and designed piece ever delivered. Organized by month. Download anything, anytime. Shareable with their team.

**Performance snapshot**
Their numbers. Simple. Reach this month, engagement rate, follower growth, top performing post. They see the value of the retainer without you compiling a report.

**Story archive**
Their Story Brief. Their brand voice profile. Key quotes from the Origin Session. Available for them to read, share with staff, use in their own communications.

### Technology stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI | Separate instance from LENS core, port 8700 |
| Database | SQLite | Separate from LENS DB — cleaner boundaries |
| Operator frontend | React + Tailwind | Desktop-first, feature-rich |
| Client portal | React + Tailwind | Mobile-first, radically simple |
| AI captions | Ollama qwen2.5:32b | Shared with LENS, same localhost endpoint |
| Transcription | faster-whisper | Local, private, M1 Max optimized |
| Social API | Meta Graph API | Instagram + Facebook posting and analytics |
| Payments | Stripe | Recurring subscriptions + one-time invoices |
| File storage | Local + optional S3 | Assets stored locally, optional cloud backup |
| Service management | launchd | Same pattern as LENS services |

### Service ports

| Service | Port |
|---|---|
| Restaurant app API | 8700 |
| Operator dashboard | 8900 |
| Client portal | 8901 (or subdomain per client) |

---

## The Story Module — Database Schema

```sql
-- Client stories
CREATE TABLE stories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER REFERENCES restaurant_clients(id),
    recorded_at         DATETIME,
    audio_path          TEXT,           -- local path to recording
    transcript_path     TEXT,           -- local path to full transcript
    transcript_text     TEXT,           -- full transcript in DB
    story_brief         TEXT,           -- synthesized narrative 500-800 words
    brand_voice_profile TEXT,           -- JSON — tone, vocabulary, values
    key_quotes          TEXT,           -- JSON array of exact quotes
    specific_details    TEXT,           -- JSON — ingredients, suppliers, places
    origin_summary      TEXT,           -- the why/how they started
    core_obsession      TEXT,           -- what drives them
    defining_moment     TEXT,           -- the turning point
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME
);

-- Extracted content pieces from story
CREATE TABLE story_content (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id            INTEGER REFERENCES stories(id),
    content_type        TEXT,   -- 'quote' | 'origin_post' | 'documentary_script' 
                                -- | 'about_page' | 'press_kit' | 'email_sequence'
    content_text        TEXT,
    used                BOOLEAN DEFAULT FALSE,
    used_at             DATETIME,
    post_id             INTEGER REFERENCES content_posts(id),
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Restaurant clients
CREATE TABLE restaurant_clients (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_name       TEXT NOT NULL,
    owner_name          TEXT,
    cuisine_type        TEXT,
    location            TEXT,
    instagram_handle    TEXT,
    facebook_page       TEXT,
    instagram_token     TEXT,   -- encrypted
    facebook_token      TEXT,   -- encrypted
    retainer_tier       TEXT,   -- 'essential' | 'signature' | 'premium'
    monthly_fee         REAL,
    billing_day         INTEGER DEFAULT 1,
    stripe_customer_id  TEXT,
    portal_password     TEXT,   -- hashed
    onboarded_at        DATE,
    active              BOOLEAN DEFAULT TRUE,
    notes               TEXT
);

-- Content calendar posts
CREATE TABLE content_posts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER REFERENCES restaurant_clients(id),
    scheduled_date      DATE,
    platform            TEXT,   -- 'instagram' | 'facebook' | 'tiktok'
    content_type        TEXT,   -- 'photo' | 'reel' | 'story' | 'carousel'
    image_path          TEXT,
    designed_asset_path TEXT,
    caption             TEXT,
    hashtags            TEXT,   -- JSON array
    status              TEXT DEFAULT 'draft',
                                -- 'draft' | 'submitted' | 'client_review'
                                -- | 'approved' | 'changes_requested'
                                -- | 'scheduled' | 'posted' | 'archived'
    client_notes        TEXT,
    posted_at           DATETIME,
    reach               INTEGER,
    impressions         INTEGER,
    likes               INTEGER,
    comments            INTEGER,
    saves               INTEGER,
    shares              INTEGER,
    story_content_id    INTEGER REFERENCES story_content(id),
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Shoot briefs
CREATE TABLE shoot_briefs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER REFERENCES restaurant_clients(id),
    shoot_date          DATE,
    location            TEXT,
    golden_hour_time    TEXT,
    weather_forecast    TEXT,
    shot_list           TEXT,   -- JSON array by category
    gear_checklist      TEXT,   -- JSON array
    client_requests     TEXT,   -- JSON array from portal submissions
    special_notes       TEXT,
    completed           BOOLEAN DEFAULT FALSE,
    images_delivered    INTEGER DEFAULT 0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Client requests from portal
CREATE TABLE client_requests (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER REFERENCES restaurant_clients(id),
    request_type        TEXT,   -- 'special_event' | 'new_dish' | 
                                -- 'promotion' | 'general'
    description         TEXT,
    event_date          DATE,
    priority            TEXT DEFAULT 'normal',
    status              TEXT DEFAULT 'new',
    operator_notes      TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Performance snapshots
CREATE TABLE performance_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id           INTEGER REFERENCES restaurant_clients(id),
    snapshot_date       DATE,
    platform            TEXT,
    followers           INTEGER,
    posts_this_month    INTEGER,
    avg_reach           REAL,
    avg_engagement_rate REAL,
    total_impressions   INTEGER,
    top_post_id         INTEGER REFERENCES content_posts(id),
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## Client Onboarding Flow

**Day 1 — Discovery call (30 minutes)**
Understand their business, their current social presence, their goals. Qualify fit. Agree on retainer tier.

**Day 2 — The Origin Session (90 minutes)**
The conversation. Recording. No agenda beyond the mental map. Let it breathe. This is the most important thing you do with a new client.

**Day 3-4 — Story processing**
Transcribe. Run chunk extraction. Run synthesis. Generate Story Brief. Build brand voice profile. Extract key quotes. Build template library from their existing branding.

**Week 2 — First shoot**
Brief generated from Origin Session content and client business context. Shoot day. Images flow into LENS pipeline. Pass 0 metadata extraction runs immediately.

**Week 2-3 — First month content creation**
Design assets using their template library. Generate captions using brand voice profile and Story Brief. Build content calendar for the month. Submit to client portal for approval.

**Week 3 — Client approval**
They review in the portal. Approve or request changes. You make adjustments. Final approval.

**Week 4 — Content goes live**
Posts scheduled and published. Performance tracking begins. First overnight report generated.

**Month 2 onward — the flywheel**
Shoot brief smarter — knows what performed last month. Captions better — brand voice profile refined from client feedback. Story series posts running from Origin Session material. Calendar pre-seeded with their upcoming events. The operation gets smoother every month automatically.

---

## The Methodology — "The Origin Session"

Once this process is proven across 3-4 clients it becomes a named productized methodology. Documentable, teachable, scalable.

**What makes it distinct:**
- Requires genuine food industry knowledge to execute — not learnable from a course
- Produces content depth that no generic agency can match
- Combines audio, AI transcription, LLM synthesis, and creative production into one repeatable system
- The output (Story Brief + documentary Reel) is immediately and obviously more valuable than what competitors deliver

**Productized pricing:**
The Origin Session as a standalone one-time product — $750–$1,500. Every new retainer client gets it as part of onboarding. Existing clients who want their story told can add it at any point.

**The teachable version:**
Once the methodology is proven and documented — workshops for other photographers who serve the restaurant market. How to have the conversation. How to run the transcription and LLM pipeline. How to turn story into content. A full-day workshop at $500-800 per attendee, 8-10 people. That's $4,000-8,000 for one Saturday teaching what you've already built.

---

## Build Order

This app is built after LENS Phase 1-2 are stable. It shares the Ollama infrastructure and benefits from the LENS pipeline but runs as a separate service.

**Phase 1 — Core infrastructure**
1. Database schema — all tables above
2. FastAPI backend on port 8700
3. Basic client records CRUD
4. Stripe subscription integration
5. launchd service plist

**Phase 2 — Story module**
6. Audio upload and storage
7. faster-whisper transcription service
8. Chunk extraction pipeline
9. Story synthesis pipeline
10. Story Brief storage and retrieval
11. Brand voice profile builder

**Phase 3 — Content pipeline**
12. Shoot brief generator (golden hour, weather, shot list)
13. Content calendar builder
14. Caption generator (Ollama 32B + brand voice)
15. Asset management (ingest from LENS + manual upload)
16. Approval workflow state machine

**Phase 4 — Client portal**
17. Portal authentication (password per client)
18. Content queue view
19. Approval interface
20. Request submission form
21. Asset library
22. Performance snapshot view

**Phase 5 — Social integration**
23. Meta Graph API authentication per client
24. Automated post scheduling
25. Performance data pull (daily cron job)
26. Performance snapshots to database

**Phase 6 — Operator dashboard**
27. Multi-client overview grid
28. Shoot schedule calendar
29. Invoice management
30. Overnight report generation
31. Cross-client performance comparison

---

## The Claude Code Prompt Addition

Add this to the LENS Claude Code session prompt when starting the restaurant app build:

```
## Restaurant content app — separate module

Build after LENS Phase 1-2 are stable. Separate FastAPI 
instance on port 8700. Separate SQLite database. 
Shares Ollama endpoint at localhost:11434.

Key differentiator: The Origin Session — audio recording 
transcribed by local Whisper model, processed in chunks 
by qwen2.5:32b, synthesized into a Story Brief that 
informs all content created for that client.

The operator has a professional chef background — the 
conversation framework and brand voice system must 
reflect genuine food industry knowledge, not generic 
marketing language.

Priority build order: Story module first (this is the 
core differentiator), then content pipeline, then 
client portal, then social API integration.

Never store audio or transcripts in cloud. 
Everything local. Client privacy is non-negotiable.
```

---

*Restaurant Content App + Origin Session Methodology*
*Built on LENS infrastructure — separate service, shared AI*
*The chef background is the product. The technology is the scale.*

---

# LENS — Claude Code Session Prompt
## Hand this to Claude Code at the start of every build session.

---

## Who you are working with

My name is Steven. I am a solo developer based in Hudson Valley, New York. I have a production background building the Nikita Network — an autonomous multi-service cryptocurrency trading system running across a local LAN with FastAPI services, ZMQ messaging, SQLite databases, Ollama LLM inference, and NSSM-managed Windows services. I know how systems are built. I think in architecture first, code second. I do not need hand-holding. I need a sharp collaborator who writes clean, production-grade code and tells me when something is wrong before it becomes a problem.

---

## What we are building

LENS (Local Enrichment and Navigation System) is a fully self-contained photography business operating system. It runs exclusively on a Mac Studio M1 Max 32GB. No cloud. No external APIs. No LAN dependency. Everything local.

LENS handles:
- Photo pipeline processing (culling, quality scoring, AI tagging)
- Client CRM and booking management
- Content calendar and social media production
- Creative inspiration and shoot concept generation
- Business intelligence and revenue forecasting
- Adobe Lightroom Classic integration
- A unified dashboard surfacing everything in one place

The system is modeled after the same architecture philosophy as the Nikita Network — shared SQLite data layer, service-oriented design, autonomous background processing, launchd-managed persistent services, and a unified dashboard. One database. Everything talks through it. Intelligence compounds over time.

---

## Hardware

| Property | Value |
|---|---|
| Machine | Mac Studio |
| Chip | Apple M1 Max |
| RAM | 32GB unified memory |
| OS | macOS |
| Architecture | Fully standalone — no LAN dependency |
| Ollama | localhost:11434 |
| Vision model | qwen2.5vl:7b |
| Text model | qwen2.5:14b |

Both models fit in 32GB simultaneously (~14GB combined). The M1 Max's 400GB/s memory bandwidth makes this the fastest inference machine available for this workload.

**GGcomp (.237) and TheOmnissiah (.203) are separate machines running the Nikita trading stack. They are never referenced in LENS code.**

---

## Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Backend | FastAPI |
| Database | SQLite (single shared file) |
| Vision inference | Ollama API — qwen2.5vl:7b |
| Text inference | Ollama API — qwen2.5:14b |
| Image processing | Pillow, OpenCV |
| Quality scoring | NIMA (Neural Image Assessment) |
| Duplicate detection | imagehash (perceptual hashing) |
| Face detection | OpenCV DNN or RetinaFace |
| Folder watching | Watchdog |
| Service management | launchd plist files |
| Adobe integration | Lightroom Classic Lua SDK |
| Environment | Python venv — never system Python |
| GPU acceleration | PyTorch MPS backend (Apple Silicon Metal) |

---

## Service ports

| Service | Port |
|---|---|
| LENS API (FastAPI) | 8600 |
| LENS Dashboard | 8800 |
| Ollama | 11434 |

---

## Project structure

```
~/lens/
├── .env
├── requirements.txt
├── venv/
├── core/
│   ├── database.py        # SQLite connection, schema init, shared session
│   ├── config.py          # Loads .env, exposes all config values
│   └── ollama.py          # Shared Ollama client — vision + text calls
├── pipeline/
│   ├── watcher.py         # Watchdog folder monitor
│   ├── pass1_cull.py      # Blur, exposure, perceptual hash dedup
│   ├── pass2_nima.py      # NIMA quality scoring
│   ├── pass3_tag.py       # Vision model tagging, 3 parallel workers
│   ├── privacy_filter.py  # Face detection, boudoir segregation
│   ├── preprocessor.py    # Resize to 1024px before vision calls
│   └── queue_manager.py   # Job queue, worker pool, status tracking
├── services/
│   ├── portfolio.py       # Auto-curator — top 20 per genre
│   ├── social_queue.py    # Content-ready image flagging
│   ├── caption_gen.py     # AI caption generator
│   ├── inspiration.py     # Concept generator + location bank
│   ├── shoot_brief.py     # Shoot day logistics engine
│   ├── repurpose.py       # Shoot reuse tracker
│   ├── revenue.py         # Revenue forecasting
│   ├── workload.py        # Post-production tracker
│   ├── licensing.py       # Commercial license tracker
│   ├── referral.py        # Referral network mapper
│   ├── style_tracker.py   # Aesthetic evolution analysis
│   ├── upsell.py          # Print + product upsell engine
│   └── client_intel.py    # Client profile builder
├── crm/
│   ├── clients.py
│   ├── bookings.py
│   ├── intake.py
│   ├── contracts.py
│   ├── sequences.py
│   └── gallery.py
├── content/
│   ├── calendar.py
│   ├── hashtags.py
│   ├── pillars.py
│   └── seasonal.py
├── api/
│   ├── main.py            # FastAPI entry point — port 8600
│   ├── routes/
│   │   ├── pipeline.py
│   │   ├── portfolio.py
│   │   ├── social.py
│   │   ├── crm.py
│   │   ├── inspiration.py
│   │   ├── intelligence.py
│   │   └── lightroom.py
│   └── models.py
├── dashboard/
│   └── ui/                # LENS dashboard — port 8800
├── lightroom/
│   └── LENS.lrplugin/
│       ├── Info.lua
│       ├── LensPlugin.lua
│       ├── LensPanel.lua
│       └── LensAPI.lua
└── launchd/
    ├── com.lens.core.plist
    ├── com.lens.watcher.plist
    ├── com.lens.pipeline.plist
    └── com.lens.ollama.plist
```

---

## Database schema

Single SQLite file. Path from `.env` as `LENS_DB_PATH`.

```sql
CREATE TABLE images (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path        TEXT UNIQUE NOT NULL,
    file_name        TEXT,
    shoot_id         INTEGER REFERENCES shoots(id),
    imported_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    blur_score       REAL,
    exposure_score   REAL,
    is_duplicate     BOOLEAN DEFAULT FALSE,
    duplicate_of     INTEGER REFERENCES images(id),
    pass1_status     TEXT,
    pass1_at         DATETIME,
    nima_technical   REAL,
    nima_aesthetic   REAL,
    nima_composite   REAL,
    pass2_at         DATETIME,
    genre            TEXT,
    mood             TEXT,
    lighting         TEXT,
    subject_type     TEXT,
    faces_present    BOOLEAN,
    face_count       INTEGER,
    color_palette    TEXT,
    setting          TEXT,
    quality_score    REAL,
    portfolio_worthy BOOLEAN,
    content_ready    BOOLEAN,
    tags             TEXT,
    caption_draft    TEXT,
    pass3_at         DATETIME,
    identifiable     BOOLEAN,
    privacy_folder   TEXT,
    privacy_at       DATETIME,
    lr_pick_flag     TEXT,
    lr_color_label   TEXT,
    lr_star_rating   INTEGER,
    lr_synced_at     DATETIME,
    posted_at        DATETIME,
    posted_to        TEXT,
    social_queue     BOOLEAN DEFAULT FALSE
);

CREATE TABLE shoots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id    INTEGER REFERENCES clients(id),
    shoot_date   DATE,
    genre        TEXT,
    location     TEXT,
    location_id  INTEGER REFERENCES locations(id),
    notes        TEXT,
    total_images INTEGER,
    delivered_at DATETIME,
    gallery_url  TEXT,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    email           TEXT,
    phone           TEXT,
    referred_by     INTEGER REFERENCES clients(id),
    referred_by_vendor INTEGER REFERENCES vendors(id),
    first_booked    DATE,
    last_booked     DATE,
    total_bookings  INTEGER DEFAULT 0,
    total_revenue   REAL DEFAULT 0,
    notes           TEXT,
    preferences     TEXT,
    anniversary     DATE,
    birthday        DATE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE bookings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER REFERENCES clients(id),
    shoot_id        INTEGER REFERENCES shoots(id),
    genre           TEXT,
    booked_date     DATE,
    shoot_date      DATE,
    package         TEXT,
    package_tier    TEXT,
    amount          REAL,
    deposit_paid    BOOLEAN DEFAULT FALSE,
    balance_paid    BOOLEAN DEFAULT FALSE,
    status          TEXT,
    source          TEXT,
    source_detail   TEXT,
    contract_signed BOOLEAN DEFAULT FALSE,
    intake_complete BOOLEAN DEFAULT FALSE,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE calendar_posts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    post_date      DATE,
    pillar         TEXT,
    genre          TEXT,
    format         TEXT,
    concept        TEXT,
    caption        TEXT,
    hashtags       TEXT,
    image_id       INTEGER REFERENCES images(id),
    shoot_id       INTEGER REFERENCES shoots(id),
    status         TEXT DEFAULT 'planned',
    posted_at      DATETIME,
    likes          INTEGER,
    saves          INTEGER,
    shares         INTEGER,
    comments       INTEGER,
    profile_visits INTEGER,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE locations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    area             TEXT,
    type             TEXT,
    address          TEXT,
    lat              REAL,
    lng              REAL,
    best_seasons     TEXT,
    best_time_of_day TEXT,
    golden_hour_notes TEXT,
    permit_required  BOOLEAN DEFAULT FALSE,
    permit_notes     TEXT,
    vibe_tags        TEXT,
    notes            TEXT,
    times_used       INTEGER DEFAULT 0
);

CREATE TABLE concepts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT,
    genre         TEXT,
    season        TEXT,
    mood          TEXT,
    location_id   INTEGER REFERENCES locations(id),
    brief         TEXT,
    wardrobe_notes TEXT,
    lighting_notes TEXT,
    props         TEXT,
    caption_angle TEXT,
    source        TEXT,
    used          BOOLEAN DEFAULT FALSE,
    shoot_id      INTEGER REFERENCES shoots(id),
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE licenses (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id        INTEGER REFERENCES clients(id),
    shoot_id         INTEGER REFERENCES shoots(id),
    image_ids        TEXT,
    usage_type       TEXT,
    licensed_at      DATE,
    expires_at       DATE,
    renewal_amount   REAL,
    renewal_notified BOOLEAN DEFAULT FALSE,
    notes            TEXT
);

CREATE TABLE vendors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT,
    type                TEXT,
    contact_name        TEXT,
    email               TEXT,
    phone               TEXT,
    referrals_sent      INTEGER DEFAULT 0,
    referrals_received  INTEGER DEFAULT 0,
    notes               TEXT
);

CREATE TABLE pipeline_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type     TEXT,
    shoot_id     INTEGER REFERENCES shoots(id),
    image_id     INTEGER REFERENCES images(id),
    status       TEXT DEFAULT 'queued',
    priority     INTEGER DEFAULT 5,
    attempts     INTEGER DEFAULT 0,
    error        TEXT,
    queued_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at   DATETIME,
    completed_at DATETIME
);
```

---

## Environment variables (.env template)

```env
LENS_DB_PATH=/Users/USERNAME/lens/data/lens.db
PHOTO_WATCH_PATH=/Users/USERNAME/Pictures/Incoming
BOUDOIR_PRIVATE_PATH=/Users/USERNAME/lens/private/boudoir
PORTFOLIO_EXPORT_PATH=/Users/USERNAME/lens/portfolio

LENS_API_PORT=8600
LENS_DASHBOARD_PORT=8800
OLLAMA_BASE_URL=http://localhost:11434
VISION_MODEL=qwen2.5vl:7b
TEXT_MODEL=qwen2.5:14b

PIPELINE_WORKERS=3
RESIZE_MAX_DIMENSION=1024
NIMA_THRESHOLD=5.5
BLUR_THRESHOLD=100.0
EXPOSURE_LOW=0.05
EXPOSURE_HIGH=0.95

PHOTOGRAPHER_NAME=Steven
BUSINESS_NAME=
LOCATION=Hudson Valley, NY
GENRES=wedding,portrait,boudoir,commercial,events,nature
```

---

## Photography genres

Use these exact strings everywhere in the codebase:

```
wedding   portrait   boudoir   commercial   events   nature
```

Boudoir is a special case in all privacy, content, and intake logic. Always handle it separately.

---

## Content pillars (weekly rotation)

| Day | Pillar key | Description |
|---|---|---|
| Monday | transformation | Before/after edits, color grades, how-I-shot-this |
| Tuesday | genre_spotlight | Rotates through all 6 genres on a 6-week cycle |
| Wednesday | bts | Behind the scenes — location, gear, editing process |
| Thursday | social_proof | Testimonials, session recaps, what-it's-like-to-book |
| Friday | personality | Voice, opinions, Hudson Valley scenery, background story |

---

## Photo pipeline rules

- **Always** resize images to 1024px longest edge before any Ollama vision call
- Use Pillow: `Image.thumbnail((1024, 1024), Image.LANCZOS)`, save JPEG quality 85
- Pass 1 is CPU-only — no GPU, no Ollama
- Pass 2 uses Metal GPU: `device = torch.device("mps")`
- Pass 3 uses 3 parallel asyncio workers
- Pass 3 prompt must return structured JSON: genre, mood, lighting, subject_type, faces_present, face_count, color_palette, setting, quality_score (0–10), portfolio_worthy (bool), content_ready (bool), tags (array)
- Privacy filter runs on ALL boudoir images regardless of face detection result

---

## Pipeline timing reference (5k batch)

| Pass | Time | Notes |
|---|---|---|
| Pass 1 — technical cull | ~2 min | CPU, 5k images |
| Pass 2 — NIMA scoring | ~3–4 min | Metal GPU, ~3k remaining |
| Manual Lightroom cull | ~15–20 min | Your time |
| Pass 3 — vision tagging | ~25–35 min | 3 workers, ~1,200 picks |

---

## Build order — start here

### Phase 1 — Foundation (build this first, everything depends on it)

1. Create `~/lens/` project directory and initialize git
2. Create and activate Python venv
3. `core/database.py` — SQLite connection, full schema init from above, shared session factory
4. `core/config.py` — loads `.env` via python-dotenv, exposes typed config values
5. `core/ollama.py` — shared async Ollama client with separate methods for vision calls and text calls
6. `api/main.py` — FastAPI app skeleton, health check endpoint, mounts all route modules
7. `launchd/com.lens.core.plist` — persistent launchd service for the FastAPI backend
8. `.env` — populated from template above with actual paths

### Phase 2 — Photo pipeline (build second)

9. `pipeline/preprocessor.py` — resize to 1024px, save as JPEG
10. `pipeline/pass1_cull.py` — Laplacian blur score, histogram exposure, imagehash dedup
11. `pipeline/pass2_nima.py` — NIMA model, MPS device, batch scoring
12. `pipeline/pass3_tag.py` — 3 async workers, structured JSON prompt, writes to images table
13. `pipeline/privacy_filter.py` — face detection, segregate identifiable boudoir images
14. `pipeline/queue_manager.py` — job queue backed by pipeline_jobs table, worker pool
15. `pipeline/watcher.py` — Watchdog monitors PHOTO_WATCH_PATH, triggers queue on new folders

---

## Rules for every session

1. Read this document fully before writing any code
2. All code goes in `~/lens/` following the structure above
3. Always use the venv: `source ~/lens/venv/bin/activate`
4. Every service that touches images calls `preprocessor.py` first
5. All database access through `core/database.py` — never open SQLite directly elsewhere
6. All Ollama calls through `core/ollama.py` — never call the API directly from service files
7. Every new service gets a corresponding route in `api/routes/`
8. Write launchd plists for every service meant to run persistently
9. Test each pipeline pass in isolation before connecting to the queue manager
10. Lightroom plugin is Lua — keep it thin, all logic stays in Python
11. When something seems wrong with the approach, say so before writing the code
12. Prefer explicit over clever. This system runs unattended. Clarity matters more than elegance.

---

## Session startup checklist

Before writing any code, confirm:

```bash
# confirm you are in the right place
pwd  # should be ~/lens or about to create it

# confirm venv is active (or create it)
source ~/lens/venv/bin/activate

# confirm ollama is running
ollama list

# confirm models are pulled
ollama list | grep qwen
```

If models are not pulled:
```bash
ollama pull qwen2.5vl:7b
ollama pull qwen2.5:14b
```

---

## What to say to start a session

**Starting fresh (Phase 1):**
> "Read the LENS spec. Build Phase 1 foundation — project setup, venv, core/database.py with full schema, core/config.py, core/ollama.py, and the FastAPI skeleton on port 8600. Write the launchd plist for the core service. Start with project directory and git init."

**Continuing a phase:**
> "Read the LENS spec. We completed [X]. Continue with [Y]. Here is what is already built: [list files]."

**Debugging:**
> "Read the LENS spec. I am getting this error: [paste error]. Here is the relevant file: [paste code]."

---

*LENS v1.0 — Claude Code session prompt*
*Steven — Hudson Valley, NY — Mac Studio M1 Max 32GB*
