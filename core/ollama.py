"""
core/ollama.py — LENS-specific Ollama client (thin wrapper around lens_core).

The OllamaClient implementation moved to `lens_core.vision.ollama_client`
2026-05-07. This file constructs a LENS-configured singleton that the rest
of LENS imports via `from core.ollama import ollama, get_mode, set_mode`.
"""

from __future__ import annotations

from pathlib import Path

from lens_core.vision.ollama_client import (
    OllamaClient,
    DEFAULT_VISION_CTX,
    ALL_32B_MODELS as _ALL_32B,
    get_mode as _generic_get_mode,
    set_mode as _generic_set_mode,
)

from core.config import settings


# LENS-specific mode flag location (must match what queue_manager and the
# auto-publisher already check on disk).
_MODE_FILE = Path("/tmp/lens_mode")


# Module-level singleton — preserves the existing `from core.ollama import ollama`
# import pattern across the LENS codebase.
ollama = OllamaClient(
    text_model=settings.text_model,
    vision_model=settings.vision_model,
    mode_flag_path=_MODE_FILE,
    base_url=settings.ollama_base_url,
    vision_ctx=DEFAULT_VISION_CTX,
)


def get_mode() -> str:
    """LENS mode helper — module-level for backward compatibility with
    callers like `services/post_scheduler.py`."""
    return _generic_get_mode(_MODE_FILE)


def set_mode(mode: str) -> None:
    _generic_set_mode(_MODE_FILE, mode)
