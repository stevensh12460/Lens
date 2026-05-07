"""
tests/eval_pass_scores.py

Pinned-sample pass-score evaluator. Two modes:

  python -m tests.eval_pass_scores --capture
      Locks in the current pass1/pass2/pass3 scores for a fixed sample of N
      images as the "baseline" — written to tests/baseline_scores.csv. Run this
      BEFORE making any pipeline change you want to measure.

  python -m tests.eval_pass_scores --compare
      Pulls current scores for the same sample IDs and writes
      tests/diff_<UTC-timestamp>.csv showing per-image, per-metric deltas vs.
      the baseline. Run this AFTER your pipeline change to see what moved.

Sample selection (run once, when capturing):
  - Stratified across NIMA tiers so the baseline covers low/mid/high quality
  - Default 50 images, ~10 per NIMA bucket: <5.5, 5.5-6.0, 6.0-6.5, 6.5-7.0, 7.0+
  - Persisted to tests/baseline_sample.json with id + file_path so we can
    detect missing rows on later runs

Re-running --capture overwrites the baseline. Use --recapture to refresh
the sample (different IDs); plain --capture uses the existing sample if
present.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import get_db


_TESTS_DIR = Path(__file__).resolve().parent
_BASELINE_CSV = _TESTS_DIR / "baseline_scores.csv"
_BASELINE_SAMPLE = _TESTS_DIR / "baseline_sample.json"

# Columns we evaluate. Order is also CSV column order.
_FIELDS = [
    "id",
    "file_name",
    "genre",
    # Pass 1
    "blur_score",
    "exposure_score",
    "cull_score",
    # Pass 2
    "nima_aesthetic",
    "nima_technical",
    "nima_composite",
    "score_composition",
    "score_exif",
    # Pass 3
    "quality_score",
    "portfolio_worthy",
    "content_ready",
    "print_worthy",
    "print_score",
]

# NIMA tiers for stratified sampling. Each (label, lo, hi) — half-open [lo, hi).
_NIMA_TIERS = [
    ("low",      0.0, 5.5),
    ("mid_low",  5.5, 6.0),
    ("mid",      6.0, 6.5),
    ("mid_high", 6.5, 7.0),
    ("high",     7.0, 100.0),
]


def _select_stratified_sample(per_tier: int) -> list[dict]:
    """Pick `per_tier` images from each NIMA tier where pass3 is complete."""
    out: list[dict] = []
    with get_db() as conn:
        for label, lo, hi in _NIMA_TIERS:
            rows = conn.execute(
                """SELECT id, file_path, file_name, nima_composite
                   FROM images
                   WHERE pass3_at IS NOT NULL
                     AND nima_composite >= ?
                     AND nima_composite < ?
                     AND file_name NOT GLOB '._*'
                   ORDER BY RANDOM() LIMIT ?""",
                (lo, hi, per_tier),
            ).fetchall()
            for r in rows:
                out.append({
                    "id": r["id"],
                    "file_path": r["file_path"],
                    "file_name": r["file_name"],
                    "tier": label,
                    "nima_at_capture": r["nima_composite"],
                })
    return out


def _load_sample() -> list[dict]:
    if not _BASELINE_SAMPLE.exists():
        return []
    return json.loads(_BASELINE_SAMPLE.read_text())


def _save_sample(sample: list[dict]) -> None:
    _BASELINE_SAMPLE.write_text(json.dumps(sample, indent=2))


def _read_scores_for(ids: list[int]) -> dict[int, dict]:
    """SELECT current scores for the given image_ids."""
    if not ids:
        return {}
    cols = ", ".join(_FIELDS)
    placeholders = ",".join("?" * len(ids))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {cols} FROM images WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def _write_csv(path: Path, rows: list[dict], extra_cols: list[str] = None) -> None:
    cols = list(_FIELDS) + (extra_cols or [])
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def cmd_capture(per_tier: int, recapture: bool) -> None:
    sample = _load_sample() if not recapture else []
    if not sample:
        print(f"[capture] selecting fresh stratified sample, {per_tier} per NIMA tier...")
        sample = _select_stratified_sample(per_tier)
        if not sample:
            print("[capture] ABORT: no images with pass3 completed in any tier")
            return
        _save_sample(sample)
        print(f"[capture] sample saved to {_BASELINE_SAMPLE} ({len(sample)} images)")
    else:
        print(f"[capture] reusing existing sample at {_BASELINE_SAMPLE} ({len(sample)} images)")

    ids = [s["id"] for s in sample]
    scores = _read_scores_for(ids)
    rows = []
    for s in sample:
        sc = scores.get(s["id"])
        if not sc:
            print(f"[capture] WARN: id={s['id']} not found in DB anymore (skipping)")
            continue
        rows.append(sc)

    _write_csv(_BASELINE_CSV, rows)
    captured_at = datetime.utcnow().isoformat()
    meta = {"captured_at": captured_at, "n": len(rows)}
    (_TESTS_DIR / "baseline_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[capture] wrote {len(rows)} rows -> {_BASELINE_CSV}")
    print(f"[capture] captured_at={captured_at}")


def cmd_compare() -> None:
    if not _BASELINE_CSV.exists():
        print(f"[compare] ABORT: no baseline at {_BASELINE_CSV}. Run --capture first.")
        return

    # Read baseline
    baseline: dict[int, dict] = {}
    with _BASELINE_CSV.open() as f:
        for row in csv.DictReader(f):
            try:
                baseline[int(row["id"])] = row
            except (ValueError, KeyError):
                continue

    ids = list(baseline.keys())
    current = _read_scores_for(ids)

    # Build delta rows
    diff_rows = []
    summary = {"improved": 0, "regressed": 0, "unchanged": 0, "missing": 0}
    numeric_metrics = [
        "blur_score", "exposure_score", "cull_score",
        "nima_aesthetic", "nima_technical", "nima_composite",
        "score_composition", "score_exif",
        "quality_score", "print_score",
    ]

    for img_id, base in baseline.items():
        cur = current.get(img_id)
        if not cur:
            summary["missing"] += 1
            continue
        row = {"id": img_id, "file_name": base.get("file_name", "")}
        any_changed = False
        any_improved = False
        any_regressed = False
        for metric in numeric_metrics:
            try:
                bv = float(base.get(metric) or "")
            except ValueError:
                bv = None
            cv = cur.get(metric)
            try:
                cv = float(cv) if cv is not None else None
            except (ValueError, TypeError):
                cv = None
            if bv is None or cv is None:
                row[metric] = ""
                row[f"{metric}_delta"] = ""
                continue
            delta = cv - bv
            row[metric] = f"{cv:.3f}"
            row[f"{metric}_delta"] = f"{delta:+.3f}"
            if abs(delta) >= 0.001:
                any_changed = True
                if delta > 0:
                    any_improved = True
                else:
                    any_regressed = True

        if any_improved and not any_regressed:
            row["status"] = "improved"
            summary["improved"] += 1
        elif any_regressed and not any_improved:
            row["status"] = "regressed"
            summary["regressed"] += 1
        elif any_improved and any_regressed:
            row["status"] = "mixed"
        elif any_changed:
            row["status"] = "changed"
        else:
            row["status"] = "unchanged"
            summary["unchanged"] += 1
        diff_rows.append(row)

    # Write diff CSV
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    diff_path = _TESTS_DIR / f"diff_{ts}.csv"
    cols = ["id", "file_name", "status"]
    for m in numeric_metrics:
        cols.extend([m, f"{m}_delta"])
    with diff_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in diff_rows:
            w.writerow(r)

    print(f"[compare] wrote {len(diff_rows)} rows -> {diff_path}")
    print(f"[compare] summary: improved={summary['improved']} regressed={summary['regressed']} "
          f"unchanged={summary['unchanged']} missing={summary['missing']}")


def main() -> None:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--capture", action="store_true", help="Save current scores as baseline")
    g.add_argument("--compare", action="store_true", help="Diff current scores vs baseline")
    p.add_argument("--per-tier", type=int, default=10,
                   help="Sample size per NIMA tier on first --capture (5 tiers; default 50 total)")
    p.add_argument("--recapture", action="store_true",
                   help="With --capture: pick a NEW random sample instead of reusing")
    args = p.parse_args()

    if args.capture:
        cmd_capture(per_tier=args.per_tier, recapture=args.recapture)
    elif args.compare:
        cmd_compare()


if __name__ == "__main__":
    main()
