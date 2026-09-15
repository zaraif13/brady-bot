"""Path helpers rooted at the app directory."""
from __future__ import annotations

from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = MODULE_ROOT / "config"
DATA_DIR = MODULE_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
