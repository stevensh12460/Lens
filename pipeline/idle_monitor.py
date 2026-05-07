"""
Phase 11 — Idle Monitor
macOS idle time detection and processing mode management.
"""
import subprocess
from enum import Enum


class ProcessingMode(Enum):
    PAUSE = "pause"          # user active — stop workers
    THROTTLED = "throttled"  # 2+ min idle — 1 worker
    FULL = "full"            # 10+ min idle — 3 workers


def get_idle_seconds() -> float:
    """
    Query macOS IOHIDSystem for user idle time.
    Returns idle time in seconds; returns 0 on any error.
    """
    try:
        result = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "HIDIdleTime" in line:
                # Line looks like:  "HIDIdleTime" = 12345678901
                parts = line.split("=")
                if len(parts) == 2:
                    ns = int(parts[1].strip())
                    return ns / 1_000_000_000.0  # nanoseconds → seconds
    except Exception:
        pass
    return 0.0


def get_processing_mode() -> ProcessingMode:
    """Return the current processing mode based on system idle time."""
    idle = get_idle_seconds()
    if idle >= 600:
        return ProcessingMode.FULL
    if idle >= 120:
        return ProcessingMode.THROTTLED
    return ProcessingMode.PAUSE


def get_worker_count(mode: ProcessingMode) -> int:
    """Return the number of concurrent workers to use for a given mode."""
    if mode == ProcessingMode.FULL:
        return 3
    if mode == ProcessingMode.THROTTLED:
        return 1
    return 0


def get_idle_status() -> dict:
    """Return a full status dict describing current idle state and processing mode."""
    idle_seconds = get_idle_seconds()
    mode = get_processing_mode()
    worker_count = get_worker_count(mode)

    descriptions = {
        ProcessingMode.PAUSE: "User is active — pipeline paused",
        ProcessingMode.THROTTLED: "Light idle (2+ min) — 1 worker running",
        ProcessingMode.FULL: "Deep idle (10+ min) — full 3-worker processing",
    }

    return {
        "idle_seconds": round(idle_seconds, 1),
        "idle_minutes": round(idle_seconds / 60, 2),
        "mode": mode.value,
        "worker_count": worker_count,
        "description": descriptions[mode],
    }
