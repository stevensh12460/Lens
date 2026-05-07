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
