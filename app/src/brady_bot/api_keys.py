"""Persisted third-party API keys (superadmin-managed)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from brady_bot.paths import DATA_DIR

API_KEYS_PATH = DATA_DIR / "api_keys.json"

ODDS_API_ID = "the_odds_api"
ODDS_API_LABEL = "The Odds API"
# Seeded once when the store is first created / missing this entry.
_DEFAULT_ODDS_KEY = "454ab6970273d280e5d6919561f2e604"

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def mask_key(key: str) -> str:
    key = (key or "").strip()
    if not key:
        return "(empty)"
    if len(key) <= 4:
        return "****"
    return f"****…{key[-4:]}"


def load_apis(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or API_KEYS_PATH
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    if isinstance(raw, dict):
        return list(raw.get("apis") or [])
    if isinstance(raw, list):
        return raw
    return []


def save_apis(apis: list[dict[str, Any]], path: Path | None = None) -> None:
    p = path or API_KEYS_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"apis": apis}, indent=2) + "\n")


def ensure_seeded(path: Path | None = None) -> list[dict[str, Any]]:
    """Ensure the Odds API entry exists; seed the provided key if missing."""
    p = path or API_KEYS_PATH
    apis = load_apis(p)
    if any(a.get("id") == ODDS_API_ID for a in apis):
        return apis
    apis.append(
        {
            "id": ODDS_API_ID,
            "label": ODDS_API_LABEL,
            "key": _DEFAULT_ODDS_KEY,
            "updated_at": _utcnow(),
        }
    )
    save_apis(apis, p)
    return apis


def get_key(api_id: str, path: Path | None = None) -> str:
    ensure_seeded(path)
    for a in load_apis(path):
        if a.get("id") == api_id:
            return str(a.get("key") or "").strip()
    return ""


def public_api(entry: dict[str, Any], *, full_key: bool = False) -> dict[str, Any]:
    key = str(entry.get("key") or "")
    out: dict[str, Any] = {
        "id": entry.get("id"),
        "label": entry.get("label"),
        "key_masked": mask_key(key),
        "updated_at": entry.get("updated_at"),
        "builtin": entry.get("id") == ODDS_API_ID,
    }
    if full_key:
        out["key"] = key
    return out


def list_apis(path: Path | None = None) -> list[dict[str, Any]]:
    return [public_api(a) for a in ensure_seeded(path)]


def get_api(api_id: str, path: Path | None = None, *, full_key: bool = False) -> dict[str, Any]:
    ensure_seeded(path)
    for a in load_apis(path):
        if a.get("id") == api_id:
            return public_api(a, full_key=full_key)
    raise KeyError("API not found")


def create_api(
    api_id: str,
    label: str,
    key: str,
    path: Path | None = None,
) -> dict[str, Any]:
    ensure_seeded(path)
    api_id = (api_id or "").strip().lower()
    label = (label or "").strip()
    key = (key or "").strip()
    if not _ID_RE.match(api_id):
        raise ValueError("id must be lowercase letters/digits/underscores (start with a letter)")
    if not label:
        raise ValueError("label is required")
    if not key:
        raise ValueError("key is required")
    apis = load_apis(path)
    if any(a.get("id") == api_id for a in apis):
        raise ValueError("An API with that id already exists")
    entry = {
        "id": api_id,
        "label": label,
        "key": key,
        "updated_at": _utcnow(),
    }
    apis.append(entry)
    save_apis(apis, path)
    return public_api(entry, full_key=True)


def update_api(
    api_id: str,
    *,
    label: str | None = None,
    key: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    ensure_seeded(path)
    apis = load_apis(path)
    idx = next((i for i, a in enumerate(apis) if a.get("id") == api_id), None)
    if idx is None:
        raise KeyError("API not found")
    entry = dict(apis[idx])
    if label is not None:
        label = label.strip()
        if not label:
            raise ValueError("label cannot be empty")
        entry["label"] = label
    if key is not None:
        entry["key"] = key.strip()
    entry["updated_at"] = _utcnow()
    apis[idx] = entry
    save_apis(apis, path)
    return public_api(entry, full_key=True)


def delete_api(api_id: str, path: Path | None = None) -> None:
    ensure_seeded(path)
    if api_id == ODDS_API_ID:
        raise ValueError("Cannot delete The Odds API entry; update the key instead")
    apis = load_apis(path)
    new_apis = [a for a in apis if a.get("id") != api_id]
    if len(new_apis) == len(apis):
        raise KeyError("API not found")
    save_apis(new_apis, path)
