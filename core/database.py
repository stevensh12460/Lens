import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from core.config import settings

_DB_PATH: Path = settings.lens_db_path


def _get_connection() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    # Connection pragmas — applied on every fresh connection. See
    # ~/Code/lens-core (when extracted) for the canonical helper.
    conn.execute("PRAGMA journal_mode=WAL")
    # NORMAL is corruption-safe under WAL and ~10x faster on writes than FULL.
    # The WAL provides the durability guarantees that FULL adds elsewhere.
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA wal_autocheckpoint=200")     # checkpoint to keep WAL small
    conn.execute("PRAGMA journal_size_limit=67108864") # cap WAL at 64MB
    conn.execute("PRAGMA foreign_keys=ON")
    # Phase 0 hardening (added 2026-05-07):
    conn.execute("PRAGMA cache_size=-65536")    # 64 MB page cache (default ~2 MB)
    conn.execute("PRAGMA temp_store=MEMORY")    # sort/temp in RAM, not on disk
    conn.execute("PRAGMA mmap_size=4294967296") # 4 GB mmap — bounded so it doesn't
                                                # contend with Ollama's 17-25 GB VRAM
                                                # on this 32 GB unified-memory machine.
    conn.execute("PRAGMA busy_timeout=5000")    # retry 5s on lock contention
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
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

CREATE TABLE IF NOT EXISTS shoots (
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

CREATE TABLE IF NOT EXISTS clients (
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

CREATE TABLE IF NOT EXISTS bookings (
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

CREATE TABLE IF NOT EXISTS calendar_posts (
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

CREATE TABLE IF NOT EXISTS locations (
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

CREATE TABLE IF NOT EXISTS concepts (
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

CREATE TABLE IF NOT EXISTS licenses (
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

CREATE TABLE IF NOT EXISTS vendors (
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

CREATE TABLE IF NOT EXISTS pipeline_jobs (
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
"""


_CRM_SCHEMA = """
CREATE TABLE IF NOT EXISTS shoot_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER REFERENCES clients(id),
    shoot_date DATE,
    location TEXT,
    genre TEXT,
    golden_hour_time TEXT,
    shot_list TEXT,
    gear_checklist TEXT,
    concepts TEXT,
    client_requests TEXT,
    special_notes TEXT,
    completed BOOLEAN DEFAULT FALSE,
    images_delivered INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sequence_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    booking_id INTEGER REFERENCES bookings(id),
    client_id INTEGER REFERENCES clients(id),
    sequence_name TEXT,
    step_index INTEGER,
    due_at DATETIME,
    message TEXT,
    status TEXT DEFAULT 'pending',
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS galleries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shoot_id INTEGER REFERENCES shoots(id),
    client_id INTEGER REFERENCES clients(id),
    token TEXT UNIQUE NOT NULL,
    pin TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    last_accessed DATETIME,
    total_views INTEGER DEFAULT 0,
    total_downloads INTEGER DEFAULT 0,
    active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS gallery_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gallery_id INTEGER REFERENCES galleries(id),
    image_id INTEGER REFERENCES images(id),
    file_path TEXT,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_NEW_COLUMNS = [
    # (column_name, column_definition)
    ("trust_score",      "REAL"),
    ("lr_rating",        "INTEGER"),
    ("lr_pick",          "TEXT"),
    ("lr_keywords",      "TEXT"),
    ("lr_caption",       "TEXT"),
    ("lr_collections",   "TEXT"),
]

# lr_color_label and lr_synced_at already exist in the schema above;
# guard them anyway in case a pre-schema DB is present.
_GUARDED_COLUMNS = _NEW_COLUMNS + [
    ("lr_color_label",   "TEXT"),
    ("lr_synced_at",     "DATETIME"),
]

# CRM columns to safely add if missing
_CRM_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "bookings": [
        ("intake_data",    "TEXT"),
        ("signed_by",      "TEXT"),
        ("signed_at",      "DATETIME"),
        ("upsell_sent_at", "DATETIME"),
    ],
}

_PHASE7_SCHEMA = """
CREATE TABLE IF NOT EXISTS client_profiles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id               INTEGER UNIQUE REFERENCES clients(id),
    communication_style     TEXT,
    style_preferences       TEXT,
    special_considerations  TEXT,
    rebooking_likelihood    TEXT,
    vip_worthy              BOOLEAN DEFAULT FALSE,
    suggested_next_session  TEXT,
    raw_analysis            TEXT,
    generated_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME
);
"""

_PHASE11_SCHEMA = """
CREATE TABLE IF NOT EXISTS overnight_reports (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date          DATE DEFAULT (date('now')),
    images_processed     INTEGER,
    new_portfolio_worthy INTEGER,
    new_social_ready     INTEGER,
    library_coverage_pct REAL,
    priority_1_pct       REAL,
    priority_2_pct       REAL,
    report_json          TEXT,
    generated_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

_PHASE9_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path      TEXT,
    destination_path TEXT,
    shoot_name       TEXT,
    genre            TEXT,
    files_copied     INTEGER DEFAULT 0,
    files_failed     INTEGER DEFAULT 0,
    total_size_mb    REAL,
    started_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at     DATETIME,
    status           TEXT DEFAULT 'in_progress'
);
"""

_PHASE7B_SCHEMA = """
CREATE TABLE IF NOT EXISTS print_sales (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id         INTEGER REFERENCES images(id),
    sale_date        DATETIME DEFAULT CURRENT_TIMESTAMP,
    size             TEXT,
    paper_type       TEXT,
    tier             TEXT,
    edition_number   INTEGER,
    sale_price       REAL,
    lab_cost         REAL,
    margin           REAL,
    channel          TEXT,
    buyer_location   TEXT,
    notes            TEXT
);
"""

# Phase 10: Pass 0 metadata columns for images table
_PASS0_COLUMNS: list[tuple[str, str]] = [
    ("captured_at",           "DATETIME"),
    ("season",                "TEXT"),
    ("time_of_day",           "TEXT"),
    ("aperture",              "REAL"),
    ("shutter_speed",         "TEXT"),
    ("iso",                   "INTEGER"),
    ("focal_length",          "REAL"),
    ("lens_model",            "TEXT"),
    ("camera_body",           "TEXT"),
    ("flash_fired",           "BOOLEAN"),
    ("orientation",           "TEXT"),
    ("creative_intent",       "TEXT"),
    ("gps_lat",               "REAL"),
    ("gps_lng",               "REAL"),
    ("gps_location_name",     "TEXT"),
    ("exposure_compensation", "REAL"),
    ("white_balance",         "TEXT"),
]

# Pass 2 scoring sub-signals (for weight tuning visibility)
_PASS2_SCORING_COLUMNS: list[tuple[str, str]] = [
    ("score_composition", "REAL"),  # Composition sub-score 0-10 (8 sub-signals blended)
    ("score_exif",        "REAL"),  # EXIF-derived sub-score 0-10 (aperture, ISO bonuses/penalties)
    ("composition_notes", "TEXT"),  # JSON array of max 3 actionable suggestions
    ("composition_sub",   "TEXT"),  # JSON dict of all 8 sub-signal scores for tuning
]

# Pass 1 cull scoring columns
_PASS1_CULL_COLUMNS: list[tuple[str, str]] = [
    ("cull_score",          "REAL"),   # Blended cull quality score 0-10
    ("cull_sub",            "TEXT"),   # JSON dict of sub-signal scores
    ("highlight_clipping",  "REAL"),   # % of blown pixels (250-255)
    ("shadow_clipping",     "REAL"),   # % of crushed pixels (0-5)
    ("noise_estimate",      "REAL"),   # Noise level estimate
]

# Pass 1 RAW support columns
_PASS1_RAW_COLUMNS: list[tuple[str, str]] = [
    ("raw_potential",       "TEXT"),    # LLM verdict: 'yes', 'no', or null
    ("raw_potential_notes", "TEXT"),    # Why — recrop suggestion, salvage notes
    ("phash",              "TEXT"),    # Perceptual hash for deduplication (survives pass3 tag overwrite)
]

# Pass 3 enrichment columns — rich 32b output fields
_PASS3_ENRICHMENT_COLUMNS: list[tuple[str, str]] = [
    ("description",        "TEXT"),   # 2-3 sentence narrative
    ("composition",        "TEXT"),   # compositional technique
    ("subjects",           "TEXT"),   # specific subjects as JSON array
    ("print_notes",        "TEXT"),   # why it works as a print
    ("technical_issues",   "TEXT"),   # motion blur, chromatic aberration, etc.
    ("emotional_impact",   "TEXT"),   # emotional impact statement
    ("pass3_model",        "TEXT"),   # model used: 'qwen2.5vl:7b' or 'qwen2.5vl:32b'
    ("texture_vocabulary", "TEXT"),   # JSON array of 3-5 texture words
    ("verb_seeds",         "TEXT"),   # JSON array of 3-5 active verbs/gerunds
    ("visual_tension",     "TEXT"),   # one short phrase on the productive contradiction
]

# Phase 7b: Print Business columns for images table
_PRINT_COLUMNS: list[tuple[str, str]] = [
    ("print_worthy",          "BOOLEAN DEFAULT FALSE"),
    ("print_score",           "REAL"),
    ("edition_title",         "TEXT"),
    ("edition_size",          "INTEGER"),
    ("editions_sold",         "INTEGER DEFAULT 0"),
    ("edition_retired",       "BOOLEAN DEFAULT FALSE"),
    ("pixieset_product_id",   "TEXT"),
    ("print_tier",            "TEXT"),
    ("print_technique",       "TEXT"),
    ("print_location_name",   "TEXT"),
    ("print_first_sale_at",   "DATETIME"),
    ("print_total_revenue",   "REAL DEFAULT 0"),
    ("print_times_sold",      "INTEGER DEFAULT 0"),
    ("gbp_pushed_at",         "DATETIME"),
]

# Social / Instagram grid columns for images table
_SOCIAL_COLUMNS: list[tuple[str, str]] = [
    ("grid_fit_score",  "REAL"),
    ("grid_fit_reason", "TEXT"),
    ("retag_queued",    "BOOLEAN DEFAULT FALSE"),
    ("retag_note",      "TEXT"),
    ("pixieset_url", "TEXT"),
]

# Calendar post scheduling columns
_CALENDAR_COLUMNS: list[tuple[str, str]] = [
    ("post_time", "TEXT"),          # 'morning' or 'evening'
    ("scheduled_at", "DATETIME"),   # exact UTC publish time
]

_ERROR_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS error_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    DATETIME DEFAULT CURRENT_TIMESTAMP,
    source       TEXT,
    severity     TEXT DEFAULT 'error',
    job_id       INTEGER,
    image_id     INTEGER,
    message      TEXT,
    resolved     BOOLEAN DEFAULT FALSE,
    resolved_at  DATETIME
);
"""

# Pipeline jobs columns added for error handling / heartbeat
_PIPELINE_JOBS_COLUMNS: list[tuple[str, str]] = [
    ("heartbeat_at", "DATETIME"),
    ("worker_id",    "INTEGER"),
]

# ---------------------------------------------------------------------------
# Website publishing (Lightroom publish service -> shp-site).
#
# Deliberately its own table rather than columns on images:
#   * one photograph can appear in two sections (a portrait used on both the
#     portraits and weddings pages), which columns cannot express;
#   * images.posted_at / posted_to belong to the Instagram queue. Overloading
#     them would make web-published photos vanish from that queue, since it
#     filters on `content_ready AND posted_at IS NULL`.
#
# lr_photo_uuid is Lightroom's per-photo uuid, NOT file_path: virtual copies
# all report the master's path, so a web crop kept as a virtual copy would
# collide with its master. UNIQUE(section, lr_photo_uuid) is the idempotency
# contract that stops a timed-out publish from allocating a second slug and
# putting the same photograph on the live site twice.
#
# layout is STORED, never recomputed. Measured against the live site: three
# landscape frames at identical 1.78 aspect carry two different classes, and a
# 0.80 portrait is `wide` in one slot and `tall` in another. `wide` is a
# full-width breath placed for rhythm, so it is a property of position in the
# sequence, not of the image. Recomputing it would destroy the hand-tuned order.
# ---------------------------------------------------------------------------
_WEB_SCHEMA = """
CREATE TABLE IF NOT EXISTS web_assets (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    section            TEXT NOT NULL,
    slug               TEXT NOT NULL,
    lr_photo_uuid      TEXT,
    image_id           INTEGER REFERENCES images(id),
    source_path        TEXT,
    file_name          TEXT NOT NULL,
    sha256             TEXT,
    width              INTEGER,
    height             INTEGER,
    layout             TEXT,
    alt_text           TEXT,
    caption            TEXT,
    sort_index         INTEGER NOT NULL,
    state              TEXT NOT NULL DEFAULT 'live',
    first_published_at DATETIME,
    last_published_at  DATETIME,
    removed_at         DATETIME,
    UNIQUE(section, slug)
);
CREATE INDEX IF NOT EXISTS idx_web_assets_section ON web_assets(section, sort_index);
CREATE UNIQUE INDEX IF NOT EXISTS idx_web_assets_uuid
    ON web_assets(section, lr_photo_uuid) WHERE lr_photo_uuid IS NOT NULL;

CREATE TABLE IF NOT EXISTS web_publish_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         DATETIME NOT NULL,
    section    TEXT,
    action     TEXT,
    added      INTEGER DEFAULT 0,
    removed    INTEGER DEFAULT 0,
    reordered  BOOLEAN DEFAULT FALSE,
    commit_sha TEXT,
    pushed     BOOLEAN DEFAULT FALSE,
    status     TEXT,
    detail     TEXT
);
"""

_OAUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service TEXT UNIQUE NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    expires_at DATETIME,
    scopes TEXT,
    metadata TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Safely add any missing columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _GUARDED_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_crm_columns(conn: sqlite3.Connection) -> None:
    """Safely add any missing CRM columns to their respective tables."""
    for table, columns in _CRM_COLUMNS.items():
        try:
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col_name, col_def in columns:
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                    print(f"[LENS] Added column: {table}.{col_name}")
        except Exception as e:
            print(f"[LENS] Warning migrating {table}: {e}")


def _migrate_print_columns(conn: sqlite3.Connection) -> None:
    """Safely add Phase 7b print business columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _PRINT_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_pass0_columns(conn: sqlite3.Connection) -> None:
    """Safely add Phase 10 Pass 0 metadata columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _PASS0_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_pass2_scoring_columns(conn: sqlite3.Connection) -> None:
    """Safely add Pass 2 scoring sub-signal columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _PASS2_SCORING_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_pass1_cull_columns(conn: sqlite3.Connection) -> None:
    """Safely add Pass 1 cull scoring columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _PASS1_CULL_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_pass1_raw_columns(conn: sqlite3.Connection) -> None:
    """Safely add RAW potential columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _PASS1_RAW_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_pass3_enrichment_columns(conn: sqlite3.Connection) -> None:
    """Safely add rich 32b output columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _PASS3_ENRICHMENT_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_social_columns(conn: sqlite3.Connection) -> None:
    """Safely add social/Instagram grid columns to the images table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(images)").fetchall()}
    for col_name, col_def in _SOCIAL_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE images ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: images.{col_name}")


def _migrate_calendar_columns(conn: sqlite3.Connection) -> None:
    """Safely add scheduling columns to the calendar_posts table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(calendar_posts)").fetchall()}
    for col_name, col_def in _CALENDAR_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE calendar_posts ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: calendar_posts.{col_name}")


def _migrate_pipeline_jobs_columns(conn: sqlite3.Connection) -> None:
    """Safely add heartbeat/worker columns to pipeline_jobs table."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_jobs)").fetchall()}
    for col_name, col_def in _PIPELINE_JOBS_COLUMNS:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE pipeline_jobs ADD COLUMN {col_name} {col_def}")
            print(f"[LENS] Added column: pipeline_jobs.{col_name}")


def log_error(conn: sqlite3.Connection, source: str, message: str,
              severity: str = "error", job_id: int = None, image_id: int = None) -> None:
    """Write an entry to the error_log table."""
    conn.execute(
        """INSERT INTO error_log (source, severity, job_id, image_id, message)
           VALUES (?, ?, ?, ?, ?)""",
        (source, severity, job_id, image_id, message),
    )


_WEB_COLUMNS: list[tuple[str, str]] = [
    # Per-image cache buster. Seeded as "2" to match the hand-written global
    # ?v=2 already deployed, then set to sha256[:8] whenever LENS republishes a
    # slug with different bytes. Stored per asset rather than global so a single
    # re-export does not invalidate all 24 images at once.
    ("cache_bust", "TEXT DEFAULT '2'"),
    # Perceptual hash of the DEPLOYED jpeg. Lets publish_photos recognise a
    # photo that is already on the site even when it arrives with a different
    # Lightroom uuid (a virtual copy, a re-import, a different export of the
    # same frame) and reuse its slot instead of adding a duplicate.
    ("phash", "TEXT"),
]


def _migrate_web_columns(conn) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(web_assets)")}
    for name, decl in _WEB_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE web_assets ADD COLUMN {name} {decl}")
            print(f"[LENS] Added column: web_assets.{name}")


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_CRM_SCHEMA)
        conn.executescript(_PHASE7_SCHEMA)
        conn.executescript(_PHASE7B_SCHEMA)
        conn.executescript(_PHASE9_SCHEMA)
        conn.executescript(_PHASE11_SCHEMA)
        conn.executescript(_OAUTH_SCHEMA)
        conn.executescript(_ERROR_LOG_SCHEMA)
        conn.executescript(_WEB_SCHEMA)
        _migrate_columns(conn)
        _migrate_crm_columns(conn)
        _migrate_print_columns(conn)
        _migrate_pass0_columns(conn)
        _migrate_pass1_cull_columns(conn)
        _migrate_pass1_raw_columns(conn)
        _migrate_pass2_scoring_columns(conn)
        _migrate_pass3_enrichment_columns(conn)
        _migrate_social_columns(conn)
        _migrate_calendar_columns(conn)
        _migrate_pipeline_jobs_columns(conn)
        _migrate_web_columns(conn)
    print(f"[LENS] Database initialized at {_DB_PATH}")
