"""
API routes for managing LENS settings (.env file).
Reads/writes the .env file directly so changes persist across restarts.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

router = APIRouter()

_ENV_PATH = Path(__file__).parent.parent.parent / ".env"

# Keys that are safe to read/write from the dashboard
_ALLOWED_KEYS = {
    # Instagram
    "INSTAGRAM_ACCESS_TOKEN",
    "INSTAGRAM_ACCOUNT_ID",
    # Pixieset
    "PIXIESET_API_KEY",
    "PIXIESET_STORE_URL",
    # Scheduling
    "INSTAGRAM_MORNING_HOUR",
    "INSTAGRAM_EVENING_HOUR",
    # Business
    "PHOTOGRAPHER_NAME",
    "BUSINESS_NAME",
    "LOCATION",
    # Ollama
    "VISION_MODEL",
    "TEXT_MODEL",
    "SCHEDULING_TEXT_MODEL",
}

# Keys whose values should be masked when reading (show last 4 chars only)
_SENSITIVE_KEYS = {
    "INSTAGRAM_ACCESS_TOKEN",
    "PIXIESET_API_KEY",
}


def _read_env() -> dict[str, str]:
    """Read .env file into a dict."""
    result = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
    return result


def _write_env(data: dict[str, str]) -> None:
    """Write dict back to .env, preserving comments and unknown keys."""
    lines = []
    if _ENV_PATH.exists():
        existing_lines = _ENV_PATH.read_text().splitlines()
    else:
        existing_lines = []

    written_keys = set()
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in data:
                lines.append(f"{key}={data[key]}")
                written_keys.add(key)
            else:
                lines.append(line)
        else:
            lines.append(line)

    # Append any new keys not already in the file
    new_keys = set(data.keys()) - written_keys
    if new_keys:
        lines.append("")
        for key in sorted(new_keys):
            lines.append(f"{key}={data[key]}")

    _ENV_PATH.write_text("\n".join(lines) + "\n")


def _mask_value(key: str, value: str) -> str:
    """Mask sensitive values for display."""
    if key in _SENSITIVE_KEYS and value and len(value) > 4:
        return "****" + value[-4:]
    return value


@router.get("")
def get_settings():
    """Return all configurable settings with sensitive values masked."""
    env = _read_env()
    result = {}
    for key in _ALLOWED_KEYS:
        raw = env.get(key, "")
        result[key] = {
            "value": _mask_value(key, raw),
            "is_set": bool(raw),
            "sensitive": key in _SENSITIVE_KEYS,
        }
    return {"settings": result}


class UpdateSettingsRequest(BaseModel):
    settings: dict[str, str]


@router.post("")
def update_settings(req: UpdateSettingsRequest):
    """Update settings. Only allowed keys are accepted. Empty string = clear."""
    env = _read_env()
    updated = []

    for key, value in req.settings.items():
        if key not in _ALLOWED_KEYS:
            continue
        # Don't overwrite with masked placeholder
        if key in _SENSITIVE_KEYS and value.startswith("****"):
            continue
        env[key] = value
        updated.append(key)

    _write_env(env)
    return {"updated": updated, "message": f"Updated {len(updated)} settings. Restart services to apply."}


@router.post("/test/instagram")
def test_instagram():
    """Test Instagram API connection with current credentials."""
    env = _read_env()
    token = env.get("INSTAGRAM_ACCESS_TOKEN", "")
    account_id = env.get("INSTAGRAM_ACCOUNT_ID", "")
    if not token or not account_id:
        return {"status": "error", "message": "Instagram credentials not configured"}
    # Quick token validation via Graph API
    try:
        import httpx
        r = httpx.get(
            f"https://graph.facebook.com/v19.0/{account_id}",
            params={"fields": "id,username,media_count", "access_token": token},
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            return {"status": "ok", "username": data.get("username"), "media_count": data.get("media_count")}
        else:
            return {"status": "error", "message": r.json().get("error", {}).get("message", r.text[:200])}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/test/pixieset")
def test_pixieset():
    """Test Pixieset API connection with current credentials."""
    env = _read_env()
    api_key = env.get("PIXIESET_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "Pixieset API key not configured"}
    try:
        import httpx
        r = httpx.get(
            "https://api.pixieset.com/v1/collections",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if r.status_code == 200:
            return {"status": "ok", "message": "Connected to Pixieset"}
        else:
            return {"status": "error", "message": f"HTTP {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
