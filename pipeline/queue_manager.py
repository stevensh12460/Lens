"""
Queue manager — job queue backed by pipeline_jobs table.
Pulls queued jobs, dispatches to the correct pipeline pass, tracks status.
Supports concurrent workers for pass1/pass2 with a DB write lock.
"""
import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

import time as _time

from core.database import get_db, log_error
from pipeline import pass0_metadata, pass1_cull, pass2_nima, pass3_tag, privacy_filter
from pipeline import priority_queue, nightly_report
from pipeline import social_evaluator
from lens_core.tz import now_et

logger = logging.getLogger("lens.queue")

_BATCH_SIZE = 50
_LLM_BATCH_SIZE = 20    # pass1_raw: ~9s/img, 20 images ≈ 3min batch
_P3_BATCH_SIZE = 1      # pass3: ~580s/img — process one at a time, unload between
_POLL_INTERVAL = 5  # seconds
_WORKERS = {"pass1": 6, "pass2": 2}  # concurrent workers per pass type (default 1)
_last_report_time = 0
_social_eval_counter = 0

# DB write lock — prevents concurrent SQLite writes from overlapping
_db_write_lock = threading.Lock()


SYNC_HANDLERS = {
    "pass0": pass0_metadata.process_batch,
    "pass1": pass1_cull.process_batch,        # fast sync cull — no LLM
    "pass2": pass2_nima.process_batch,
    "privacy": privacy_filter.process_batch,
}

ASYNC_HANDLERS = {
    "pass1_raw": pass1_cull.process_batch_async,  # LLM salvage review for raw_review images
    "pass3": pass3_tag.process_batch_async,
}


def enqueue(job_type: str, image_paths: list[Path], shoot_id: Optional[int] = None, priority: int = 5) -> list[int]:
    """
    Add jobs to the queue. Returns list of job IDs (mix of newly inserted and reused existing).

    Dedup contract: for any (job_type, image_id) pair, at most one row exists in
    pipeline_jobs with status in ('queued','running','complete'). If an existing row is
    found:
      - complete / running     → skip insert, return existing job_id
      - queued                 → upgrade priority if new > existing, return existing job_id
      - error w/ attempts>=3   → skip (terminal), return existing job_id
      - error w/ attempts<3    → treat as queued (upgrade priority, return existing)

    Paths whose image_id can't be resolved (image not yet in `images` table) fall back
    to a blind INSERT — rare; caller should normally register the image first.
    """
    job_ids = []
    with _db_write_lock, get_db() as conn:
        for path in image_paths:
            row = conn.execute(
                "SELECT id FROM images WHERE file_path = ?", (str(path),)
            ).fetchone()
            image_id = row["id"] if row else None

            if image_id is not None:
                existing = conn.execute(
                    """SELECT id, status, priority, attempts FROM pipeline_jobs
                       WHERE job_type = ? AND image_id = ?
                       AND status IN ('queued','running','complete','error')
                       ORDER BY id DESC LIMIT 1""",
                    (job_type, image_id),
                ).fetchone()

                if existing is not None:
                    existing_status = existing["status"]
                    existing_id = existing["id"]
                    existing_priority = existing["priority"] or 0
                    existing_attempts = existing["attempts"] or 0

                    if existing_status in ("complete", "running"):
                        logger.debug(f"[enqueue] dedup: {job_type} image_id={image_id} already {existing_status}, skipped")
                        job_ids.append(existing_id)
                        continue

                    if existing_status == "error" and existing_attempts >= 3:
                        logger.debug(f"[enqueue] dedup: {job_type} image_id={image_id} terminal error (attempts={existing_attempts}), skipped")
                        job_ids.append(existing_id)
                        continue

                    # queued or retryable error — upgrade priority if new is higher
                    if priority > existing_priority:
                        conn.execute(
                            "UPDATE pipeline_jobs SET priority = ? WHERE id = ?",
                            (priority, existing_id),
                        )
                        logger.debug(f"[enqueue] dedup: {job_type} image_id={image_id} priority {existing_priority}→{priority}, reused job_id={existing_id}")
                    else:
                        logger.debug(f"[enqueue] dedup: {job_type} image_id={image_id} already queued at priority {existing_priority}, reused")
                    job_ids.append(existing_id)
                    continue

            cursor = conn.execute(
                """INSERT INTO pipeline_jobs (job_type, shoot_id, image_id, status, priority)
                   VALUES (?, ?, ?, 'queued', ?)""",
                (job_type, shoot_id, image_id, priority),
            )
            job_ids.append(cursor.lastrowid)
    return job_ids


from core.ollama import get_mode

_PRIORITY_MODE_FILE = Path("/tmp/lens_priority_mode")
_PRIORITY_THRESHOLD = 10

# Pause flag — when present, main loop does NOTHING (no pass0/1/2/3, no promote, no social)
_PAUSED_FILE = Path("/tmp/lens_paused")


def is_priority_mode() -> bool:
    return _PRIORITY_MODE_FILE.exists()


def is_paused() -> bool:
    """True when the pipeline is user-paused. Main loop idles, in-flight work finishes."""
    return _PAUSED_FILE.exists()


async def _unload_llm() -> None:
    """Tell Ollama to release the model from RAM immediately after a batch completes.
    Frees ~20GB so the cull pass has full memory for rawpy decoding."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                "http://localhost:11434/api/generate",
                json={"model": "qwen2.5vl:32b", "keep_alive": 0, "prompt": ""},
            )
        logger.info("[llm] Model unloaded — RAM free for cull pass")
    except Exception as e:
        logger.warning(f"[llm] Unload request failed (non-fatal): {e}")


def _fetch_batch(job_type: str) -> list[dict]:
    # In priority mode, ALL passes only process high-priority jobs
    priority_filter = ""
    if is_priority_mode():
        priority_filter = f"AND j.priority >= {_PRIORITY_THRESHOLD}"

    _MAX_ATTEMPTS = 3
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT j.id, j.job_type, j.image_id, i.file_path
               FROM pipeline_jobs j
               LEFT JOIN images i ON j.image_id = i.id
               WHERE j.job_type = ? AND j.status = 'queued'
               AND j.attempts < {_MAX_ATTEMPTS}
               AND i.file_name NOT LIKE '.\\_%' ESCAPE '\\'
               AND COALESCE(i.pass1_status, 'pending') NOT IN ('fail', 'missing', 'sidecar', 'corrupt', 'video')
               {priority_filter}
               ORDER BY j.priority DESC, j.queued_at ASC
               LIMIT ?""",
            (job_type, _P3_BATCH_SIZE if job_type == "pass3" else _LLM_BATCH_SIZE if job_type == "pass1_raw" else _BATCH_SIZE),
        ).fetchall()
        return [dict(r) for r in rows]


def _mark_running(job_ids: list[int], worker_id: int = 0) -> None:
    now = now_et().isoformat()
    with _db_write_lock, get_db() as conn:
        placeholders = ",".join("?" * len(job_ids))
        conn.execute(
            f"UPDATE pipeline_jobs SET status = 'running', started_at = ?, heartbeat_at = ?, worker_id = ? WHERE id IN ({placeholders})",
            [now, now, worker_id, *job_ids],
        )


class _HeartbeatThread(threading.Thread):
    """Background thread that updates heartbeat_at every 30s for a set of job IDs.
    Allows the watchdog to distinguish stuck from slow-but-alive jobs."""

    def __init__(self, job_ids: list[int]):
        super().__init__(daemon=True)
        self._job_ids = job_ids
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.wait(30):
            try:
                with _db_write_lock, get_db() as conn:
                    placeholders = ",".join("?" * len(self._job_ids))
                    conn.execute(
                        f"UPDATE pipeline_jobs SET heartbeat_at = ? WHERE id IN ({placeholders}) AND status = 'running'",
                        [now_et().isoformat(), *self._job_ids],
                    )
            except Exception:
                pass  # non-fatal — watchdog will catch truly stuck jobs

    def stop(self):
        self._stop_event.set()


def _mark_complete(job_ids: list[int]) -> None:
    with _db_write_lock, get_db() as conn:
        placeholders = ",".join("?" * len(job_ids))
        conn.execute(
            f"UPDATE pipeline_jobs SET status = 'complete', completed_at = ? WHERE id IN ({placeholders})",
            [now_et().isoformat(), *job_ids],
        )


def _mark_error(job_id: int, error: str, job_type: str = "unknown", image_id: int = None) -> None:
    with _db_write_lock, get_db() as conn:
        conn.execute(
            "UPDATE pipeline_jobs SET status = 'error', error = ?, attempts = attempts + 1 WHERE id = ?",
            (error, job_id),
        )
        log_error(conn, source=job_type, message=error, job_id=job_id, image_id=image_id)


def _run_worker(job_type: str, worker_jobs: list[dict], worker_id: int) -> tuple[int, int]:
    """Process a single worker's batch. Returns (total, completed)."""
    valid_jobs = [j for j in worker_jobs if j.get("file_path")]
    invalid_jobs = [j for j in worker_jobs if not j.get("file_path")]

    for j in invalid_jobs:
        _mark_error(j["id"], "No file_path associated with job", job_type=job_type, image_id=j.get("image_id"))

    if not valid_jobs:
        return (0, 0)

    paths = [Path(j["file_path"]) for j in valid_jobs]
    job_ids = [j["id"] for j in valid_jobs]

    # Start heartbeat thread — updates heartbeat_at every 30s while processing
    hb = _HeartbeatThread(job_ids)
    hb.start()

    try:
        import time as _t
        _start = _t.time()
        results = SYNC_HANDLERS[job_type](paths)
        elapsed = _t.time() - _start
        print(f"[worker-{worker_id}] {job_type}: {len(results)} results in {elapsed:.1f}s", flush=True)
        completed = 0
        for job, result in zip(valid_jobs, results):
            if result.get("error"):
                _mark_error(job["id"], result.get("error", "processing error"), job_type=job_type, image_id=job.get("image_id"))
            else:
                _mark_complete([job["id"]])
                completed += 1
        return (len(paths), completed)
    except Exception as e:
        print(f"[worker-{worker_id}] {job_type}: EXCEPTION: {e}", flush=True)
        # Log critical worker crash
        with _db_write_lock, get_db() as conn:
            log_error(conn, source=job_type, severity="critical",
                      message=f"Worker {worker_id} crashed: {e}. Batch of {len(valid_jobs)} images affected.")
        for j in valid_jobs:
            _mark_error(j["id"], str(e), job_type=job_type, image_id=j.get("image_id"))
        return (len(paths), 0)
    finally:
        hb.stop()


def run_pass(job_type: str) -> int:
    """Drain the queue for sync passes (pass1, pass2, privacy).
    Uses concurrent workers for pass1/pass2 (configured in _WORKERS)."""
    if job_type not in SYNC_HANDLERS:
        return 0

    num_workers = _WORKERS.get(job_type, 1)

    # Fetch batches for all workers at once, mark all as running before dispatching
    all_jobs = []
    for w in range(num_workers):
        batch = _fetch_batch(job_type)
        if not batch:
            break
        _mark_running([j["id"] for j in batch], worker_id=w)
        all_jobs.append(batch)

    if not all_jobs:
        return 0

    total_fetched = sum(len(b) for b in all_jobs)
    print(f"[run_pass] {job_type}: fetched {total_fetched} jobs across {len(all_jobs)} worker(s)", flush=True)

    # Single worker — run directly, no threading overhead
    if len(all_jobs) == 1:
        total, completed = _run_worker(job_type, all_jobs[0], 0)
        print(f"[run_pass] {job_type}: {completed}/{total} succeeded", flush=True)
        return total

    # Multiple workers — run concurrently
    total_processed = 0
    total_completed = 0
    with ThreadPoolExecutor(max_workers=len(all_jobs)) as executor:
        futures = {
            executor.submit(_run_worker, job_type, batch, i): i
            for i, batch in enumerate(all_jobs)
        }
        for future in as_completed(futures):
            total, completed = future.result()
            total_processed += total
            total_completed += completed

    print(f"[run_pass] {job_type}: {total_completed}/{total_processed} succeeded ({len(all_jobs)} workers)", flush=True)
    return total_processed


async def run_pass_async(job_type: str) -> int:
    """Drain the queue for async passes (pass1_raw, pass3)."""
    if job_type not in ASYNC_HANDLERS:
        return 0
    jobs = _fetch_batch(job_type)
    if not jobs:
        return 0

    # Separate valid jobs (have file_path) from broken ones
    valid_jobs = [j for j in jobs if j.get("file_path")]
    invalid_jobs = [j for j in jobs if not j.get("file_path")]

    _mark_running([j["id"] for j in jobs])

    # Immediately error jobs with no file_path
    for j in invalid_jobs:
        _mark_error(j["id"], "No file_path associated with job", job_type=job_type, image_id=j.get("image_id"))

    if not valid_jobs:
        return 0

    paths = [Path(j["file_path"]) for j in valid_jobs]
    job_ids = [j["id"] for j in valid_jobs]

    # Start heartbeat for async jobs too
    hb = _HeartbeatThread(job_ids)
    hb.start()

    try:
        results = await ASYNC_HANDLERS[job_type](paths)
        completed = 0
        for job, result in zip(valid_jobs, results):
            if result.get("status") == "error" or result.get("error"):
                _mark_error(job["id"], result.get("error", "processing error"), job_type=job_type, image_id=job.get("image_id"))
            else:
                _mark_complete([job["id"]])
                completed += 1
        logger.info(f"[{job_type}] {completed}/{len(paths)} succeeded")
    except Exception as e:
        with _db_write_lock, get_db() as conn:
            log_error(conn, source=job_type, severity="critical",
                      message=f"Async batch crashed: {e}. {len(valid_jobs)} images affected.")
        for j in valid_jobs:
            _mark_error(j["id"], str(e), job_type=job_type, image_id=j.get("image_id"))
        logger.error(f"[{job_type}] batch error: {e}")
    finally:
        hb.stop()

    return len(paths)


def _auto_promote() -> int:
    """
    Promote images through the pipeline automatically.
    Strict sequential: ALL pass1 must finish before ANY pass2 starts,
    ALL pass2 must finish before ANY pass3 starts.
    This ensures full CPU for pass1/2, full GPU for pass3 — no resource fighting.
    Returns total jobs promoted.
    """
    promoted = 0
    # In priority mode, waterfall only considers priority jobs — normal jobs don't block promotion
    priority_filter = ""
    if is_priority_mode():
        priority_filter = f"AND priority >= {_PRIORITY_THRESHOLD}"

    with get_db() as conn:
        # raw_review images stay flagged — salvage manually via Images tab

        # Check if pass1 is fully drained (no queued or running pass1 jobs)
        p1_active = conn.execute(
            f"SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass1' AND status IN ('queued','running') {priority_filter}"
        ).fetchone()[0]

        # Only promote pass1 → pass2 when ALL pass1 is done
        if p1_active == 0:
            rows = conn.execute("""
                SELECT i.file_path, MAX(j.priority) as pri FROM images i
                LEFT JOIN pipeline_jobs j ON j.image_id = i.id AND j.job_type = 'pass1'
                WHERE i.pass1_status = 'pass' AND i.pass2_at IS NULL
                AND i.file_path NOT IN (
                    SELECT i2.file_path FROM pipeline_jobs j2
                    JOIN images i2 ON j2.image_id = i2.id
                    WHERE j2.job_type = 'pass2' AND j2.status IN ('queued','running','error')
                )
                GROUP BY i.file_path
                LIMIT 500
            """).fetchall()
            for row in rows:
                pri = row["pri"] if row["pri"] and row["pri"] > 5 else 5
                enqueue("pass2", [Path(row["file_path"])], priority=pri)
            promoted += len(rows)
            if rows:
                logger.info(f"[auto_promote] pass1 fully drained — promoted {len(rows)} to pass2")

        # Check if pass1 AND pass2 are fully drained before promoting to pass3
        # (pass3 only starts after ALL pass1 AND ALL pass2 are done)
        p2_active = conn.execute(
            f"SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass2' AND status IN ('queued','running') {priority_filter}"
        ).fetchone()[0]

        # Only promote pass2 → pass3 when ALL pass1 AND ALL pass2 are done
        # Tiered by composite score:
        #   >= 6.5 → priority 10 (processed first)
        #   6.0–6.5 → priority 3 (processes after top tier, overnight)
        #   < 6.0 → never promoted (not worth GPU time — viewable in Images tab, manual rescue available)
        if p1_active == 0 and p2_active == 0:
            # Tier 1: high-scoring images (>= 6.5) — priority 10
            tier1 = conn.execute("""
                SELECT i.file_path FROM images i
                WHERE i.pass2_at IS NOT NULL AND i.pass3_at IS NULL
                AND i.nima_composite >= 6.5
                AND i.file_path NOT IN (
                    SELECT i2.file_path FROM pipeline_jobs j2
                    JOIN images i2 ON j2.image_id = i2.id
                    WHERE j2.job_type = 'pass3' AND j2.status IN ('queued', 'running', 'error')
                )
                LIMIT 500
            """).fetchall()
            for row in tier1:
                enqueue("pass3", [Path(row["file_path"])], priority=10)
            promoted += len(tier1)

            # Tier 2: decent images (6.0–6.5) — priority 3 (after top tier)
            tier2 = conn.execute("""
                SELECT i.file_path FROM images i
                WHERE i.pass2_at IS NOT NULL AND i.pass3_at IS NULL
                AND i.nima_composite >= 6.0 AND i.nima_composite < 6.5
                AND i.file_path NOT IN (
                    SELECT i2.file_path FROM pipeline_jobs j2
                    JOIN images i2 ON j2.image_id = i2.id
                    WHERE j2.job_type = 'pass3' AND j2.status IN ('queued', 'running', 'error')
                )
                LIMIT 500
            """).fetchall()
            for row in tier2:
                enqueue("pass3", [Path(row["file_path"])], priority=3)
            promoted += len(tier2)

            if tier1 or tier2:
                logger.info(f"[auto_promote] pass2→pass3: {len(tier1)} high-priority (>=6.5), {len(tier2)} standard (6.0-6.5), skipped <6.0")

        # pass3 → privacy (boudoir or faces present)
        rows = conn.execute("""
            SELECT file_path FROM images
            WHERE pass3_at IS NOT NULL AND privacy_at IS NULL
            AND (genre = 'boudoir' OR faces_present = TRUE)
            AND file_path NOT IN (
                SELECT i.file_path FROM pipeline_jobs j
                JOIN images i ON j.image_id = i.id
                WHERE j.job_type = 'privacy' AND j.status IN ('queued','running','error')
            )
            LIMIT 500
        """).fetchall()
        paths = [Path(r["file_path"]) for r in rows]
        if paths:
            enqueue("privacy", paths, priority=3)
            promoted += len(paths)

    if promoted:
        logger.info(f"Auto-promoted {promoted} images to next pipeline stage")
    return promoted


def _reset_stuck_jobs() -> int:
    """
    Find jobs stuck in 'running' state with stale heartbeat and reset them.
    Uses heartbeat_at if available (5 min timeout), falls back to started_at (15 min).
    This handles cases where a worker crashes mid-batch.
    Returns number of jobs reset.
    """
    with get_db() as conn:
        # Jobs with heartbeat: stuck if heartbeat > 5 min old (worker stopped sending)
        r1 = conn.execute("""
            UPDATE pipeline_jobs
            SET status = 'queued', started_at = NULL, heartbeat_at = NULL, worker_id = NULL
            WHERE status = 'running'
            AND heartbeat_at IS NOT NULL
            AND heartbeat_at < datetime('now', '-5 minutes')
        """)
        count_hb = r1.rowcount

        # Jobs without heartbeat (legacy): stuck if started > 15 min ago
        r2 = conn.execute("""
            UPDATE pipeline_jobs
            SET status = 'queued', started_at = NULL
            WHERE status = 'running'
            AND heartbeat_at IS NULL
            AND started_at < datetime('now', '-15 minutes')
        """)
        count_legacy = r2.rowcount

        count = count_hb + count_legacy
        if count:
            log_error(conn, source="watchdog", severity="warning",
                      message=f"Reset {count} stuck jobs (heartbeat: {count_hb}, legacy: {count_legacy})")
    if count:
        logger.warning(f"[watchdog] Reset {count} stuck jobs back to queued (hb:{count_hb} legacy:{count_legacy})")
    return count


def _check_priority_complete() -> bool:
    """Check if all priority folder images have finished processing through all passes."""
    import json
    state_file = Path("/tmp/lens_priority_state.json")
    if not state_file.exists():
        return False
    try:
        state = json.loads(state_file.read_text())
        image_paths = state.get("image_paths", [])
    except Exception:
        return False
    if not image_paths:
        return True

    with get_db() as conn:
        placeholders = ",".join("?" * len(image_paths))
        total = len(image_paths)

        # Pass 1 done?
        pass1_done = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass1_status IS NOT NULL AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]
        if pass1_done < total:
            return False

        # Terminal images (won't continue to pass2/3)
        # raw_review is terminal in priority mode — salvage is skipped
        terminal = conn.execute(
            f"""SELECT COUNT(*) FROM images
                WHERE pass1_status IN ('fail', 'duplicate', 'raw_review', 'missing', 'sidecar', 'corrupt', 'video')
                AND file_path IN ({placeholders})""",
            image_paths
        ).fetchone()[0]

        need_all_passes = total - terminal
        if need_all_passes == 0:
            return True  # all culled/duplicated — done

        # Pass 3 done for all non-terminal images?
        pass3_done = conn.execute(
            f"SELECT COUNT(*) FROM images WHERE pass3_at IS NOT NULL AND file_path IN ({placeholders})",
            image_paths
        ).fetchone()[0]

        # Also count errored jobs so we don't wait forever
        errored_images = conn.execute(
            f"""SELECT COUNT(DISTINCT i.id) FROM images i
                JOIN pipeline_jobs j ON j.image_id = i.id
                WHERE j.status = 'error' AND j.priority >= {_PRIORITY_THRESHOLD}
                AND i.pass3_at IS NULL AND i.pass1_status NOT IN ('fail', 'duplicate', 'missing', 'sidecar', 'corrupt', 'video')
                AND i.file_path IN ({placeholders})""",
            image_paths
        ).fetchone()[0]

        return (pass3_done + errored_images) >= need_all_passes


async def _finish_priority_mode() -> None:
    """Clean up after priority processing completes: unload models, switch to off."""
    from core.ollama import set_mode
    print("[priority] All priority images complete — finishing up", flush=True)
    logger.info("[priority] All priority images complete — switching to off mode")

    # Remove state files
    Path("/tmp/lens_priority_state.json").unlink(missing_ok=True)
    _PRIORITY_MODE_FILE.unlink(missing_ok=True)

    # Unload LLM models
    try:
        await _unload_llm()
    except Exception as e:
        logger.error(f"[priority] Error unloading LLM: {e}")

    # Switch mode to off
    set_mode("off")
    print("[priority] Mode set to off — priority processing complete", flush=True)


async def run_full_pipeline_loop() -> None:
    """Continuously drain the queue for all passes in order."""
    global _last_report_time, _social_eval_counter
    logger.info("Queue manager started.")
    # On startup, clear any jobs left in 'running' from a previous crashed session
    with get_db() as conn:
        cleared = conn.execute(
            "UPDATE pipeline_jobs SET status='queued', started_at=NULL, heartbeat_at=NULL, worker_id=NULL WHERE status='running'"
        ).rowcount
        if cleared:
            log_error(conn, source="system", severity="warning",
                      message=f"Startup recovery: cleared {cleared} stale running jobs from previous session")
    if cleared:
        logger.warning(f"[startup] Cleared {cleared} stale running jobs from previous session")

    # Priority mode is now manually controlled only — no auto-restore on startup
    _paused_last = False
    while True:
        # Pause gate — skip ALL work while paused. In-flight batches already running
        # will complete on their own; we just don't fetch new ones.
        if is_paused():
            if not _paused_last:
                logger.info("[loop] PAUSED — idling until resumed")
                print("[loop] PAUSED — idling until resumed", flush=True)
                _paused_last = True
            await asyncio.sleep(_POLL_INTERVAL)
            continue
        if _paused_last:
            logger.info("[loop] RESUMED — returning to normal operation")
            print("[loop] RESUMED — returning to normal operation", flush=True)
            _paused_last = False

        print("[loop] === new iteration ===", flush=True)
        current_mode = get_mode()

        processed = 0
        _reset_stuck_jobs()

        # Pass 0 — opportunistic background enrichment (non-blocking, up to 100/cycle)
        try:
            pass0_count = pass0_metadata.process_all_unprocessed(limit=100)
            if pass0_count:
                logger.info(f"[pass0] background enrichment: {pass0_count} images")
        except Exception as e:
            logger.error(f"[pass0] background enrichment error: {e}")

        try:
            _auto_promote()
        except Exception as e:
            print(f"[auto_promote] error (will retry next loop): {e}", flush=True)

        # Social evaluator — run every 10th loop iteration to avoid overhead
        # auto_fill_calendar() is permanently disabled by user policy: never
        # auto-pick photos for the IG calendar (brand risk — see HANDOFF.md).
        # Only the scoring pass runs; calendar entries must be created manually.
        _social_eval_counter += 1
        if _social_eval_counter >= 10:
            _social_eval_counter = 0
            try:
                social_evaluator.evaluate_new_images()
            except Exception as e:
                logger.error(f"[social_evaluator] {e}")

        priority_mode = is_priority_mode()
        priority_filter = f"AND priority >= {_PRIORITY_THRESHOLD}" if priority_mode else ""

        # ── Sequential waterfall: finish each pass completely before the next ──
        # Check queued counts per pass to enforce ordering
        with get_db() as conn:
            p1_queued = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass1' AND status='queued' {priority_filter}"
            ).fetchone()[0]
            p2_queued = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass2' AND status='queued' {priority_filter}"
            ).fetchone()[0]
            p3_queued = conn.execute(
                f"SELECT COUNT(*) FROM pipeline_jobs WHERE job_type='pass3' AND status='queued' {priority_filter}"
            ).fetchone()[0]

        # --- Pass 1 (CPU cull) — always runs first ---
        if p1_queued > 0:
            processed += run_pass("pass1")
            if processed:
                logger.info(f"[waterfall] pass1: {p1_queued} queued — draining before pass2")

        # --- Pass 2 (NIMA scoring, CPU) — runs after pass1 fully drains ---
        elif p2_queued > 0:
            processed += run_pass("pass2")
            if processed:
                logger.info(f"[waterfall] pass2: {p2_queued} queued — draining before pass3")

        # --- Pass 3 (vision tagging, LLM) — runs after pass2 fully drains, needs auto or priority mode ---
        elif p3_queued > 0:
            if current_mode not in ("auto", "priority"):
                logger.debug(f"[waterfall] pass3: {p3_queued} queued — waiting for auto mode")
            else:
                _P3_TIMEOUT = 900
                try:
                    p3 = await asyncio.wait_for(run_pass_async("pass3"), timeout=_P3_TIMEOUT)
                    if p3:
                        processed += p3
                        await _unload_llm()
                except asyncio.TimeoutError:
                    logger.warning("[pass3] timed out — resetting running job")
                    with get_db() as conn:
                        conn.execute("UPDATE pipeline_jobs SET status='queued', started_at=NULL, heartbeat_at=NULL WHERE job_type='pass3' AND status='running'")
                        log_error(conn, source="pass3", severity="warning",
                                  message=f"Pass3 timed out after {_P3_TIMEOUT}s — job reset to queued")

        # --- Privacy pass — runs whenever there's work (low volume, fast) ---
        processed += run_pass("privacy")

        # --- Priority completion check ---
        if current_mode == "priority" and is_priority_mode():
            if _check_priority_complete():
                await _finish_priority_mode()

        if processed == 0:
            await asyncio.sleep(_POLL_INTERVAL)

        # Generate nightly report every hour
        if _time.time() - _last_report_time > 3600:
            try:
                report = nightly_report.generate_report()
                nightly_report.save_report(report)
                _last_report_time = _time.time()
            except Exception as e:
                logger.error(f"[nightly_report] {e}")


def queue_status() -> dict:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT job_type, status, COUNT(*) as count
               FROM pipeline_jobs GROUP BY job_type, status"""
        ).fetchall()
        return [dict(r) for r in rows]
