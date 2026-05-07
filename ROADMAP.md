# LENS Roadmap & Ideas
*Captured during build session — 2026-04-06*

---

## Dashboard Redesign

### Layout
- **Left column** — today's schedule, hour by hour
- **Right column** — this week, shape of the week at a glance
- **Bottom** — full month calendar grid with color-coded markers:
  - Blue = shoots
  - Green = posts
  - Yellow = follow-ups
  - Red = deadlines

### Tabs
- **Calendar** — day / week / month all in one view
- **Pipeline** — machine room, Pass 1/2/3 progress, queue depth, system vitals, Ollama status
- **Images** — processed work, filterable by genre/shoot/score, actual thumbnails not file paths
- **Clients** — profiles, booking history, revenue, last contact, upcoming shoots
- **Bookings** — confirmed, pending, contract status, intake status
- **Content** — social queue, approved/draft/posted, feeds from calendar
- **Intelligence** — revenue by month/genre, best clients, referral sources, busy seasons

### Adding to Calendar
- Click any day or time slot → panel slides in from right, no page change
- Asks what type first: shoot, post, follow-up, deadline, personal block
- Shows only relevant fields for that type
- Client name autocompletes from database
- Image picker pulls from social-ready queue, not a file browser
- Hit save → panel closes, marker appears instantly
- **Quick-add bar** at top of every tab — always visible, type fast, capture anything

### Parsing
- Rule-based code only — no LLM for data entry
- Pattern matching for dates, times, client names
- Fast, local, works even if Ollama is down

---

## LLM Usage Policy
*Ollama runs only when genuinely needed. Everything else is pure code.*

**LLM fires up for:**
- Pass 3 — vision tagging (the big one, hours, close all apps first)
- Caption generation — single text model call
- Shoot brief / concept generation — text model, single call
- New shoot pipeline — Pass 3 phase only

**LLM never runs for:**
- Dashboard, calendar, CRM, bookings, content queue
- Data entry, search, filtering, linking records
- Anything that pure code can handle

**Heads up system:**
- Dashboard banner warning before Pass 3 starts — "Pass 3 starting soon — close heavy applications"
- No surprises

---

## SD Card Auto-Import
- LENS detects SD card insertion
- Dashboard banner / notification: "SD card detected. Import?"
- User confirms, gives shoot a name, picks genre
- LENS creates folder on 8TB in user's exact folder structure
- Copies files off card (never moves — SD stays untouched until user formats)
- Kicks off Pass 1 automatically once copy is verified
- User always confirms before anything starts — never fully automatic

**To do:** Steven to show his folder organization system → LENS mirrors it exactly

---

## Content & Social Strategy

### Post Structure (per slot)
- 2 photos + 1 editing process video
- Before/after with editing video performs best
- LENS flags images with high transformation potential for video candidates
  (big exposure corrections, heavy color grades, dramatic crops)

### Instagram Integration
- **Phase 1 (now):** LENS prepares everything — image selected, caption written, hashtags ready, scheduled time set. User gets notified, approves, posts manually.
- **Phase 2 (later):** Official Meta Graph API integration if desired. Requires Facebook Business account + Meta app approval.
- Recommendation: stay on Phase 1 for new/growing account — algorithm rewards human engagement early

### Content Pillars (weekly rotation per spec)
- Monday: transformation
- Tuesday: genre spotlight (6-week rotation)
- Wednesday: BTS
- Thursday: social proof
- Friday: personality

---

## Business Intelligence Ideas
- **Know your numbers** — true cost per shoot including time, travel, editing, delivery
- **Referral tracking** — which sources actually convert to bookings
- **Seasonal patterns** — slow months, busy months, plan accordingly
- **Genre profitability** — which work pays best per hour
- **Client lifetime value** — who books again, who refers, who's worth investing in
- **Competitor pricing research** — manual for now, Hudson Valley market

---

## Pricing & Business Direction
- Currently underpricing across all genres
- Time to treat this as a real business
- LENS infrastructure replaces what serious photographers pay others to manage
- Compete on experience and consistency, not price
- The intake → shoot → delivery → follow-up experience is the product, not just the photos

---

## Composition Intelligence (Pass 3 enhancement)

Add specific composition analysis to the Pass 3 vision prompt. Store results as separate fields in the database.

**Questions to ask the model per image:**
- Is the subject well framed or does it feel cramped?
- Is the horizon level or tilted?
- Is there intentional use of negative space?
- Rule of thirds — is the subject placed with intention?
- Leading lines present?
- Overall composition rating

**Fixability flag:**
- If composition issue detected, assess whether it's fixable in post
- Uneven horizon → fixable via straighten tool
- Poor crop / subject placement → fixable via recrop
- Cramped framing → fixable if there's enough edge to recrop into
- Flag these as `composition_fixable = TRUE` so they don't get buried in rejects
- In the Images tab, show these separately — "Fixable in Edit" category
- Note specifically what to fix — "horizon tilted left, straighten and recrop"

**The workflow this enables:**
LENS flags the issue + tells you exactly what's wrong + tells you it's salvageable. You open Lightroom already knowing what to do. No guessing, no missed shots.

---

## Lead Generation + Website
*From master spec — Phase 3 build, direct revenue impact*

- **Smart intake + quote generator** — embeddable widget on website, genre-aware flows (wedding vs boudoir vs commercial ask completely different questions), feeds directly into CRM on submit. No manual data entry ever.
- **Interactive pricing calculator** — client-facing, shows package options by genre, add-ons visible, sets expectations before the first conversation. Reduces price-shock bookings.
- **Website structure** — genre landing pages, boudoir on a completely separate private URL (never appears in main nav), each page built to convert not just display. Copy informed by LENS client intelligence data.
- **Self-hosted gallery portal** — client delivery without Pixieset dependency for portrait/wedding/commercial work. Client gets a link, enters a PIN, downloads their gallery. Stays inside LENS, no third-party cut.
- **Local SEO + blog strategy** — Hudson Valley search traffic is real and largely unclaimed by working photographers. Long-tail location keywords (Hudson Valley wedding photographer, Rhinebeck portrait session, Catskills elopement). Blog posts generated by LENS text model, reviewed and published by you. Pairs with Google Business Profile weekly photo updates already planned.

---

## Services Layer — Specific Features
*Named items from the 34-feature master list, lives under services/ build phase*

- **Repurpose tracker** (`services/repurpose.py`) — flags shoots that haven't been fully used for content. "This wedding shoot from 6 months ago has 3 social-ready images and you've only posted 1." Compounding value from existing work.
- **Trending aesthetic auditor** (`services/style_tracker.py`) — monitors what's performing in your genres on Instagram, surfaces gaps between what's trending and what's in your library. Input for concept generator.
- **Gap-aware concept suggestions** — "You haven't posted a forest golden hour portrait in 6 weeks. You have 14 social-ready images from the October session at Catskill location." Closes the loop between the library and the content calendar automatically.
- **Social-to-shoot feedback loop** — best performing posts feed back into shoot brief generator. If forest golden hour content consistently outperforms studio work, the next shoot brief surfaces that signal. The system learns what your audience responds to and reflects it back.
- **Tiered packages per genre + add-on menu** — clean packaging of services, stored in the database, referenced by the intake form, pricing calculator, and contracts. Wedding: Essential / Signature / Premium. Boudoir: The Experience / The Collection. Commercial: Half Day / Full Day / Campaign. Add-ons: rush delivery, second shooter, extra hour, album, prints.

---

## Future Ideas (parking lot)
- Shoot brief generator — pulls client history, location, golden hour time, concepts not yet shot, weather
- Anniversary / birthday reminders for past clients — automatic re-booking opportunities
- Location bank — every location logged with best time of day, season, permit info, vibe tags built from real experience
- License renewal tracking — commercial work expiring, auto-flag for follow-up
- Workload tracker — how many images in post, realistic delivery timelines

---

## Build Queue (when pipeline scan is done)
1. Services layer — portfolio curator, caption gen, revenue forecasting, client intel
2. CRM layer — intake, contracts, sequences, gallery delivery
3. Content layer — calendar logic, hashtag engine, pillars, seasonal planning
4. Dashboard redesign — full rebuild per above spec
5. SD card import flow
6. Remove Zoom / Maxon / Red Giant launch agents (needs sudo)

---

## Pass 0 — Metadata Extraction
*Added 2026-04-06 — run this first, costs almost nothing, makes every pass smarter*

Before any AI processing, LENS extracts all metadata from RAW files — EXIF, XMP sidecars, and the Lightroom catalog directly. CPU only. Under 1 hour for the full 22TB library.

**What it populates with zero AI:**
- Season and time of day (golden hour, blue hour, midday, night) from capture timestamp
- Aperture, shutter, ISO, focal length, lens model, camera body — full shooting context
- Creative intent inference (long_exposure_intentional, motion_freeze, shallow_dof, landscape_deep_focus, standard)
- Burst group detection — groups within 2 seconds + sequential file numbers; best NIMA score wins
- GPS reverse geocoding → human-readable location name, matched against locations table (background job)
- Lightroom star ratings, pick/reject flags, color labels, keywords, collections — imported directly from .lrcat SQLite

**Trust hierarchy for quality scoring:**

| Source | Trust level |
|---|---|
| LR 5-star | Highest — always portfolio worthy |
| LR 4-star | Very high — print and content priority |
| LR pick flag | High — seeds Priority 2 queue automatically |
| NIMA ≥ 8.0 | Medium-high |
| Vision model quality ≥ 8.0 | Medium |
| LR reject flag | Skip — never process |

**Pipeline order after Pass 0:**
```
Pass 0 — metadata    (minutes, CPU, no AI)
Pass 1 — cull        (minutes, CPU, no AI — uses Pass 0 burst groups)
Pass 2 — NIMA        (minutes, Metal GPU, no AI)
Pass 3 — vision      (hours, Ollama — uses Pass 0 metadata as context priors)
```

**New `images` table fields:** captured_at, season, time_of_day, aperture, shutter_speed, iso, focal_length, lens_model, camera_body, body_serial, flash_fired, orientation, drive_mode, creative_intent, burst_group_id, burst_position, gps_lat, gps_lng, gps_location_name, gps_town, gps_county, lr_rating, lr_color_label, lr_pick, lr_keywords, lr_caption, lr_collections, trust_score

**Build target:** `pipeline/pass0_metadata.py` — add as step 0 in queue_manager before pass1

---

## Idle Processing System
*Added 2026-04-06 — processes 22TB library silently over weeks using idle Mac cycles*

### Philosophy
When you're working, pipeline pauses. When the Mac sits idle, workers spin up and process silently. Every idle hour compounds the asset catalog. Same pattern as Time Machine and Spotlight indexing.

### Idle detection
IOKit via `ioreg -c IOHIDSystem → HIDIdleTime`. Checked every 30 seconds.
- 10+ minutes idle → full (3 workers, qwen2.5vl:32b)
- 2+ minutes idle → throttled (1 worker)
- User active → pause workers

### Priority tiers

| Priority | What | Model | When |
|---|---|---|---|
| 1 | Top 500 by NIMA score | qwen2.5vl:32b | Immediately — no wait |
| 2 | All Lightroom pick-flagged | qwen2.5vl:32b | First idle window |
| 3 | Everything above NIMA threshold | qwen2.5vl:32b | Extended idle |
| 4 | Full library sweep | qwen2.5vl:7b | Deep idle — nights/weekends |

Priority 4 images that score unexpectedly high → flagged for Priority 1 re-run with 32b.

### Library timeline (22TB)
- Priority 1 (500 images): 45 min–2 hours
- Priority 2 (~5,000–10,000 LR picks): 3–8 hours spread across nights
- Priority 3 (~60,000 above threshold): several weeks
- Priority 4 (~440,000+ total): 2–3 months consistent idle

**The business does not wait for completion.** Priority 1 done → launch Pixieset store. Priority 2 done → launch full content calendar. Each completion unlocks the next layer.

### Overnight report
First panel on dashboard every morning:
```
LENS overnight report — [date]
────────────────────────────────────────
Processed last 8 hours:     847 images
Priority 1 complete:        500 / 500  ✓
Priority 2 remaining:       3,241 images
Library coverage:           2.3%
New print candidates found: 23
New content-ready images:   61
Est. Priority 2 complete:   4 nights at current pace
```

**Build targets:** `get_idle_seconds()`, `should_process()`, `PriorityQueue` class, `WorkerPool`, `NightlyReport` — all in `pipeline/queue_manager.py`. New API endpoints: `GET /pipeline/status`, `GET /pipeline/overnight`, `GET /pipeline/coverage`.

---

## Print Business — Experimental Fine Art Prints
*Added 2026-04-06 — passive revenue, build-once sell-forever, defensible visual signature*

### The technique
Camera on lightstand boom arm, pivoting around a central point during long exposures. Creates genuine parallax — real optical physics, not a filter. Cannot be replicated in post. At 42MP (A7R III) abstract experimental images print at 40x60in with gallery-quality tonal detail.

**Kit:** A7R III + 35mm GM f/1.4 + DJI RS4 Mini + lightstand + boom arm

**Technique variations:**
- Long exposure orbit — light sources trace circular arcs, rooms become vortices
- f/1.4 focal plane sweep — razor depth of field sweeps through scene during rotation
- Strobe freeze mid-rotation — subject sharp inside pure abstract motion blur
- Color vortex — colored gels at different positions, overlapping arcs create color mixing impossible in the scene
- Turntable variant — subject rotates in front of locked camera (also: 360 product spins for commercial)
- Dual rotation — subject and camera rotating opposite directions, interference patterns unrepeatable

**Hudson Valley locations:** Old barns, Catskill forest, waterfalls, Hudson riverfront at dusk, Shawangunks, narrow alleyways in Hudson/Rhinebeck

### Two-tier product structure

**Tier 1 — Standard prints (Pixieset + WHCC auto-fulfillment, zero touch)**
- 8x10: $75–100 / 11x14: $125–175 / 16x20: $250–350 / 20x30: $400–550

**Tier 2 — Limited edition fine art (self-fulfillment, numbered, Hahnemühle/Canson)**
- 20x30 ed/25: $500–700 / 30x40 ed/15: $800–1,100 / 40x60 ed/10: $1,200–1,800
- As editions sell down → remaining prints increase in value → buyers have reason to purchase now

**Tier 3 — 360 product spins** (commercial, same turntable rig, delivered as video/GIF for e-commerce)

### Revenue at scale
Pixieset on a paid plan = 0% commission. WHCC 16x20 costs ~$15–25. Sell at $300 = $275 margin. Lab cost is not the price anchor.

### Sales channels
- Pixieset store (primary — always on, every client gallery links to it)
- Instagram/TikTok — BTS of rotation session shoots performs well, makes people want the artifact
- Pinterest — pin once, landscape + location tags drive traffic for years
- Google Business Profile — weekly auto-upload of new print_worthy images (GBP rewards fresh photos with local ranking)
- Local galleries — Hudson, Rhinebeck, Woodstock, Beacon (40–50% consignment, high credibility)
- Etsy — reaches tourists who want to take Hudson Valley home
- Interior designers — wholesale, one relationship = recurring revenue
- Art fairs — seasonal, direct sales, no commission

**Content engine connection:** Add `print_campaign` flag to calendar posts. When pushing a specific print, calendar surfaces BTS content, caption generator tells the story of the image, social queue pulls hero image and supporting frames automatically.

### LENS additions for print business

**New `images` table fields:** print_worthy, print_score, edition_title, edition_size, editions_sold, edition_retired, pixieset_product_id, tier (standard/fine_art/commercial), technique (rotation/turntable/orbit/standard), location_name, first_sale_at, total_revenue, times_sold

**New `print_sales` table:** sale_date, size, paper_type, tier, edition_number, sale_price, lab_cost, margin, channel, buyer_location

**New services:**
- `services/print_curator.py` — vision model print-worthiness scoring per landscape image
- `services/edition_tracker.py` — alerts at 50% sold (raise price), 80% sold (publicize scarcity), 100% (retire)
- `services/print_revenue.py` — margin per image, per technique, per channel, by month
- `services/gbp_print_push.py` — weekly auto-upload to Google Business Profile

**Dashboard additions:** Print revenue panel — this month vs last, top selling images, edition status, upcoming art fair deadlines, GBP last upload, images awaiting Pixieset upload

**Phase 7b build order:**
1. Add print fields to `images` table
2. Create `print_sales` table
3. `services/print_curator.py`
4. `services/edition_tracker.py`
5. `services/print_revenue.py`
6. `services/gbp_print_push.py`
7. `api/routes/print.py`
8. Dashboard print revenue panel

### First action before building any of this
Go shoot. One Hudson Valley location, rotation rig, 50–100 frames. Pull files, find 2–3 that genuinely surprise you. Print one at 16x20 through Mpix (~$25). Put it on the wall. Live with it 7 days. If you still love it — that's your first Pixieset listing. The business builds from that one print.

---

## Restaurant Content App — Visual Content Subscription for Food & Hospitality
*Added 2026-04-06 — separate service, builds on LENS infrastructure, build after LENS Phase 1-2 stable*

### The concept
Full-service visual content subscription for restaurants, wineries, farms, and food businesses in Hudson Valley. Not a photography retainer. Not a social media agency. A new category that combines photography, motion design, AI-powered story extraction, and client management in one operation — possible only because of the specific combination of professional chef background + video production + AI pipeline + photography.

**The unfair advantage:** A chef background means real conversations with restaurant owners that a generic content person cannot have. That trust is the foundation everything is built on.

### What clients are buying
Three components delivered monthly:
1. **Photography** — monthly shoot, new dishes, seasonal items, kitchen BTS, events, edited gallery
2. **Designed artwork** — photos become Instagram posts with typography, story templates, motion graphics, After Effects Reels, animated content that stops scrolling
3. **The app** — client portal + operator dashboard managing content queue, approvals, scheduling, asset library, performance metrics, invoicing

### The Origin Session — the core differentiator
One 90-minute recorded conversation with the owner/chef. Transcribed locally by faster-whisper (M1 Max: 90 min → 5-10 min, fully private, never leaves the Mac). Processed by qwen2.5:32b in chunks (transcript too long for one context window). Synthesized into a 500-800 word Story Brief capturing: central story arc, core obsession, defining moment, specific details, authentic voice (direct quotes), emotional truth.

**From one Story Brief:**
- Brand story (400–600 words) → website about page
- Short documentary Reel (60–90 sec) → their actual voice from conversation over shoot footage — outperforms agency content because it's authentic
- Origin story post series (5–8 posts, 6-8 week Instagram run)
- Pull quotes → designed graphic assets
- Email welcome sequence (3 parts)
- Press kit narrative
- Venue description for GBP/Yelp/booking platforms

The conversation requires genuine food industry knowledge to execute. The chef background is not a credential, it's what makes the conversation real.

### Pricing architecture

| Tier | Monthly | Included |
|---|---|---|
| Essential | $1,200 | 2hr shoot, 20 images, 8 posts, captions, portal |
| Signature | $2,200 | 4hr shoot, 40 images, 20 posts + 4 Reels, AI captions in brand voice, performance report |
| Premium | $3,500 | Full day shoot, unlimited images, 30 posts + 8 motion, story series, GBP mgmt, email content, quarterly strategy |

**Add-ons:** Origin Session $750–1,500 / Brand identity $1,200–2,500 / Menu redesign $500–1,500 / Event coverage $800–2,000 / Press kit $400

**Revenue at scale:** 5 Signature clients = $11,000/month ($132,000/year). 5 clients = one shoot day per week. Very manageable.

### Technology stack
- Backend: FastAPI on port 8700 (separate from LENS core at 8600)
- Database: SQLite (separate from LENS DB — cleaner boundaries)
- Operator frontend: React + Tailwind (desktop-first)
- Client portal: React + Tailwind (mobile-first, radically simple)
- AI captions: Ollama qwen2.5:32b (shared, same localhost:11434)
- Transcription: faster-whisper (local, private, M1 Max optimized)
- Social API: Meta Graph API (Instagram + Facebook posting + analytics)
- Payments: Stripe (recurring subscriptions + one-time invoices)
- Services: launchd (same pattern as LENS services)

### The Origin Session as a standalone product
Once proven across 3-4 clients — named, documented, productized methodology. $750–1,500 standalone. Every new retainer client gets it at onboarding. Eventually: workshops for other photographers serving the restaurant market. Full-day workshop $500–800/attendee × 8–10 people = $4,000–8,000 for one Saturday.

### Build order
**Phase 1:** Database schema, FastAPI on 8700, client records CRUD, Stripe subscriptions, launchd plist
**Phase 2:** Audio upload/storage, faster-whisper transcription, chunk extraction, story synthesis, Story Brief storage, brand voice profile builder
**Phase 3:** Shoot brief generator (golden hour + weather + shot list), content calendar builder, caption generator (Ollama 32B + brand voice), asset management (ingest from LENS), approval workflow state machine
**Phase 4:** Client portal — auth, content queue, approval interface, request form, asset library, performance snapshot
**Phase 5:** Meta Graph API per client, automated post scheduling, daily performance data pull, performance snapshots
**Phase 6:** Multi-client operator overview grid, shoot calendar, invoice management, overnight report, cross-client performance comparison

**Rule:** Do not start this until LENS Priority 2 scan is complete and the print store is live. First restaurant client deserves full attention. Don't context-switch during onboarding.
