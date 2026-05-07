# LENS — Calendar & Instagram Integration

Full breakdown of what was built, how it works, and what's next.

Last updated: 2026-04-25

---

## 1. Instagram / Meta API Connection

### What's connected
- **App**: LENS (registered at developers.facebook.com)
- **Business Portfolio**: Steven Howard
- **Facebook Page**: Moody Valley Stills
- **Instagram Business Account**: `@moodyvalleystills`
- **Auth**: long-lived User Access Token (60 days)

### IDs in `.env`
```
META_APP_ID=1672205817296983
META_APP_SECRET=de67120b7217963af0fd6e9510b316c4
META_ACCESS_TOKEN=<long-lived 60-day token>
META_IG_BUSINESS_ID=17841433141998115
META_FB_PAGE_ID=1128845970304377

# LENS-side (used by services/post_scheduler.py and routes/social.py)
INSTAGRAM_ACCESS_TOKEN=<same token>
INSTAGRAM_ACCOUNT_ID=17841433141998115
```

### Token refresh
- Long-lived token expires in ~60 days from issue.
- **Renewal endpoint** (drop into Safari, replace placeholders):
  ```
  https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=APPID&client_secret=APPSECRET&fb_exchange_token=CURRENT_LONG_TOKEN
  ```
- Returns a new 60-day token. Paste it into `.env` (both `META_ACCESS_TOKEN` and `INSTAGRAM_ACCESS_TOKEN`), restart core.
- **TODO**: add a launchd job that does this automatically every 30 days.

### Health check
```
GET http://localhost:8600/social/instagram/status
```
Should return `{"configured": true, "account_id": "17841433141998115", "token_set": true, ...}`

---

## 2. Publish Flow — Three-Layer Safety

### The Instagram Graph API publish flow (3 steps)
1. **Create container**: `POST /{ig-user-id}/media` with `image_url` + `caption` → returns `creation_id`. **Container is NOT publicly visible.** Expires unused in ~24h.
2. **Poll status**: `GET /{creation_id}?fields=status_code` until `FINISHED`.
3. **Publish**: `POST /{ig-user-id}/media_publish` with `creation_id` → **NOW the post appears on the feed.**

### Three layers of protection in LENS

| Layer | Endpoint | What it does | Touches IG? | Visible publicly? |
|---|---|---|---|---|
| 1. Offline preview | `GET /social/publish/{post_id}/preview` | Shows full payload, validates caption length / hashtag count / file existence | No | No |
| 2. Dry-run | `POST /social/publish/{post_id}?dry_run=true` (default) | Steps 1-2 only — creates container, verifies it | Yes (creates container) | **No** |
| 3. Real publish | `POST /social/publish/{post_id}?dry_run=false` | All 3 steps | Yes | **Yes** |

The `dry_run=true` default means a typo or mis-click cannot publish. You must explicitly add `?dry_run=false` to the URL.

### Files
- `api/routes/social.py` — `publish_preview()` and `publish_now()` endpoints
- `services/post_scheduler.py` — `publish_post(post_id, dry_run=True)` with the real Graph API logic

---

## 3. The Calendar Tab UI

### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  IG status • Pixieset status                                 │
│                                                              │
│  [Day] [Week] [Month]    [Date picker] [🎨 Genres] [Fill 7d] │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ─── Day / Week / Month view ───                             │
│  (whichever subtab is active)                                │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  📷 Post Candidate Pool                       e.g. 280/4747  │
│  [Genre▾] [Subject▾] [Tag] [Sort▾] [Min NIMA▾]              │
│  [✓ Hide scheduled] [✓ Hide posted] [Limit▾] [Apply]         │
│                                                              │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐            │
│  │ img │ │ img │ │ img │ │ img │ │ img │ │ img │ ...        │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

The **pool is always visible below** all 3 view subtabs (Day / Week / Month).

### Filter options

| Filter | Values | Default |
|---|---|---|
| Genre | nature, portrait, wedding, boudoir, commercial, events | nature |
| Subject | landscape, solo portrait, couple, group, product | landscape |
| Tag | substring match in pass3 tags (e.g. "sunset") | — |
| Sort | grid_fit, nima, recent, random | grid_fit |
| Min NIMA | 0 / 5.5 / 6.0 / 6.5 / 7.0 | 6.5 |
| Hide scheduled | bool | on |
| Hide posted | bool | on |
| Limit | 100 / 500 / 1k / 5k | 500 |

Each card shows: thumbnail, genre, score, filename. Badges for **Posted** (green) and **Scheduled** (amber).

---

## 4. Click Flows

### Flow A: Quick assign (click-and-click) — recommended for batch scheduling

1. **Click an empty slot** in Week view → cell highlights blue, pool scrolls into view.
2. **Click any image** in the pool → **instantly assigned** to that slot. No modal, no confirmation.
3. Repeat for next slot.

### Flow B: Quick swap

1. **Click a filled slot** in Week view → cell highlights blue, pool scrolls into view.
2. **Click any image** in the pool → **instantly swaps** the image on that post (caption is cleared, since it's stale for the new image).

### Flow C: Schedule with full control

1. **Click an image** with no slot pre-selected → Schedule modal opens.
2. Pick **date**, **time slot** (morning 9 AM / evening 6 PM), **pillar** (personality / transformation / social proof / education / portfolio).
3. Click **"Add to Calendar"** → post created.

### Flow D: Remove a post

- **Click the X** in the top-right of a filled cell → deletes the entire calendar post (slot becomes empty).
- X is blocked for posts already marked `posted` — can't accidentally delete IG history.

### Flow E: Preview / edit a post

- **Double-click a filled cell** → opens preview/edit modal (existing flow, unchanged).

### Flow F: Deselect a slot
- **Click the same cell again** (the one already highlighted) → deselects.

---

## 5. Backend Endpoints

### `GET /social/post-candidates`
Rich candidate pool query, mirrors `/print/candidates`.

**Query params** (all optional):
- `genre` — nature, portrait, wedding, boudoir, commercial, events
- `subject_type` — landscape, solo portrait, couple, group, product
- `tag` — case-insensitive substring match in pass3 tags
- `min_nima` — float, default 0
- `min_grid_fit` — float, default 0
- `exclude_scheduled` — bool, default true (drops images already on calendar)
- `exclude_posted` — bool, default true (drops images already posted)
- `sort` — `grid_fit` (default) | `nima` | `random` | `recent`
- `limit` — 1-10000, default 500

**Returns**:
```json
{
  "count": 280,
  "total": 4747,
  "images": [
    {
      "id": 48003,
      "file_name": "DSC07820.ARW",
      "file_path": "...",
      "genre": "nature",
      "subject_type": "landscape",
      "mood": "serene",
      "setting": "outdoor water",
      "tags": "[\"foggy\", \"lake\", ...]",
      "caption_draft": null,
      "pixieset_url": null,
      "nima_composite": 7.115,
      "grid_fit_score": 0.85,
      "quality_score": 8.5,
      "print_score": 7.12,
      "posted_at": null,
      "captured_at": "2024-09-27T07:03:39",
      "scheduled": 0
    },
    ...
  ]
}
```

### `POST /social/calendar`
Create a planned calendar post.

**Body**:
```json
{
  "post_date": "2026-05-01",
  "post_time": "morning",        // morning | evening
  "pillar": "portfolio",
  "genre": "nature",             // optional
  "image_id": 48003,             // optional but recommended
  "format": null,
  "concept": null,
  "shoot_id": null
}
```

**Returns**: `{"id": 123, "post_date": "2026-05-01", "post_time": "morning"}`

**Errors**:
- `409` if that date/slot is already taken by an unposted booking.

### `DELETE /social/calendar/{post_id}`
Removes a calendar post. Blocked if `status='posted'`.

### `PATCH /social/calendar/{post_id}/image`
Swap the image on a calendar post.
**Body**: `{"image_id": 48003}`

### `GET /social/publish/{post_id}/preview`
Pure offline preview. No API calls, no DB writes. See section 2.

### `POST /social/publish/{post_id}?dry_run=true|false`
Real Graph API publish. See section 2.

### `GET /social/instagram/status`
Auth health.

---

## 6. Database

### `calendar_posts` table — fields used
- `id` — primary key
- `post_date` — `YYYY-MM-DD`
- `post_time` — `morning` | `evening`
- `pillar` — `personality` | `transformation` | `social_proof` | `education` | `portfolio`
- `genre` — copied from image
- `caption` — final caption (null until generated)
- `hashtags` — JSON list or space-separated string
- `image_id` — FK → `images.id`
- `status` — `planned` | `scheduled` | `posted`
- `posted_at` — timestamp when published to IG (real publish only)

### `images` table — fields read by candidate pool
- `id`, `file_name`, `file_path`, `genre`, `subject_type`, `mood`, `setting`
- `tags` (JSON list from pass3 vision tagging)
- `caption_draft` (auto-generated by `services/caption_gen.py`)
- `pixieset_url` (set when uploaded to Pixieset; doubles as the public image URL for IG)
- Scores: `nima_composite`, `grid_fit_score`, `quality_score`, `print_score`
- `content_ready` (gate flag — must be true)
- `posted_at`, `posted_to`

---

## 7. What's Still Pending

### A. Image hosting for real publish
**Problem**: Instagram fetches the image from a public HTTPS URL. Local file paths don't work.

**Options** (in order of preference):
1. **Pixieset URL** — if `image.pixieset_url` is set, that URL is used. Cleanest path. Manual upload workflow already exists in the Prints tab.
2. **Cloudflare Tunnel** — free, spins up a public URL pointing at your dashboard's image-serving endpoint. Lives only while the tunnel runs.
3. **Image host** (Imgur, Cloudinary) — adds dependency.

A `PUBLIC_IMAGE_BASE_URL` env var hook is already in `services/post_scheduler.py` — just set it to the tunnel URL when ready.

### B. Caption generation
The `caption_draft` field is null on most images. Two ways to populate:
- **Per-post**: `POST /social/caption` with `{"image_id": N, "style": "instagram"}`
- **Batch for next 7 days**: `POST /social/caption/batch/scheduled?days=7` — generates captions for all calendar posts in the window that don't have one.

### C. Test post
1. Pick a planned post (or schedule one via the new pool).
2. Generate caption if missing.
3. Hit `GET /social/publish/{post_id}/preview` — review everything offline.
4. Set up image hosting (option A or B above).
5. Hit `POST /social/publish/{post_id}` (defaults to dry_run=true) — creates IG container, doesn't publish.
6. Verify the response says `"status": "dry_run_ok"`.
7. **ONLY THEN** hit `POST /social/publish/{post_id}?dry_run=false` to actually publish.

### D. Auto-refresh of the access token
Add a launchd plist that hits the token-exchange URL every 30 days and rewrites `.env`. Prevents unexpected expiry.

---

## 8. Files Modified

| File | Change |
|---|---|
| `.env` | Added `META_*` and `INSTAGRAM_*` env vars |
| `api/routes/social.py` | New endpoints: `/post-candidates`, `/publish/{id}/preview`. Updated `/calendar` POST to accept `post_time` and reject double-bookings. Rewrote `/publish/{id}` with `dry_run` flag. |
| `services/post_scheduler.py` | Full rewrite. Real 3-step Graph API publish flow with `dry_run=True` default. |
| `dashboard/ui/index.html` | Removed old candidate pool from Week subtab. Added Prints-style pool below all 3 calendar views. Added Schedule modal. New JS: `loadPostCandidates`, `pickCandidate`, `openSchedModal`, `submitSchedule`. Repurposed `selectCandidateSlot` for click-and-click flow. |

---

## 9. Quick Reference Commands

```bash
# Check IG auth health
curl -s http://localhost:8600/social/instagram/status | python3 -m json.tool

# List candidates
curl -s "http://localhost:8600/social/post-candidates?genre=nature&subject_type=landscape&min_nima=6.5&limit=10" | python3 -m json.tool

# See a single calendar post
curl -s http://localhost:8600/social/calendar/63 | python3 -m json.tool

# Offline preview a post (no API calls)
curl -s http://localhost:8600/social/publish/63/preview | python3 -m json.tool

# Dry-run (creates container, does not publish)
curl -s -X POST http://localhost:8600/social/publish/63 | python3 -m json.tool

# REAL publish (actually posts to @moodyvalleystills)
curl -s -X POST "http://localhost:8600/social/publish/63?dry_run=false" | python3 -m json.tool

# Restart LENS core after .env changes
launchctl kickstart -k gui/$(id -u)/com.lens.core
```
