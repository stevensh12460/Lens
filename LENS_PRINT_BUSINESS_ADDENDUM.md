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
