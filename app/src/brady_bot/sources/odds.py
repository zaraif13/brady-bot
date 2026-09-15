from __future__ import annotations

import os
from typing import Any

import httpx

from brady_bot import api_keys as api_keys_mod
from brady_bot.sources.cache import CacheStore

ODDS_TTL = 6 * 3600
# NFL regular-season / playoff games only — never all-sports or Super Bowl futures.
ODDS_SPORT_KEY = "americanfootball_nfl"
ODDS_URL = f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEY}/odds"
SPORTS_URL = "https://api.the-odds-api.com/v4/sports/"


def resolve_odds_api_key(path=None) -> str:
    """Prefer admin-managed store, then ODDS_API_KEY env."""
    stored = api_keys_mod.get_key(api_keys_mod.ODDS_API_ID, path)
    if stored:
        return stored
    return os.getenv("ODDS_API_KEY", "").strip()


def _soft_http_error(response: httpx.Response) -> str | None:
    """Return a short user-facing message for known Odds API failures."""
    if response.status_code == 429:
        return "Odds API quota exhausted"
    body = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            code = str(payload.get("error_code") or "")
            msg = str(payload.get("message") or "")
            if code == "INVALID_KEY" or "not valid" in msg.lower() or response.status_code in (401, 403):
                return "Odds API key invalid; using schedule lines"
            if msg:
                return f"Odds unavailable: {msg}"
    except Exception:
        body = (response.text or "")[:200]
    if response.status_code in (401, 403):
        return "Odds API key invalid; using schedule lines"
    return f"Odds unavailable: HTTP {response.status_code}" + (f" {body}" if body else "")


def check_odds_api_key(api_key: str) -> dict[str, Any]:
    """
    Health-check the key against /v4/sports/ and require americanfootball_nfl.
    Does not fetch odds for other sports.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return {"ok": False, "message": "API key is empty"}
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(SPORTS_URL, params={"apiKey": api_key})
        if r.status_code != 200:
            soft = _soft_http_error(r)
            return {"ok": False, "message": soft or f"HTTP {r.status_code}"}
        sports = r.json()
        if not isinstance(sports, list):
            return {"ok": False, "message": "Unexpected sports catalog response"}
        nfl = next((s for s in sports if s.get("key") == ODDS_SPORT_KEY), None)
        if not nfl:
            return {
                "ok": False,
                "message": f"Sport key {ODDS_SPORT_KEY} (NFL) not found in catalog",
            }
        active = nfl.get("active")
        title = nfl.get("title") or "NFL"
        if active is False:
            return {
                "ok": True,
                "message": f"Key valid; {title} ({ODDS_SPORT_KEY}) present but inactive",
            }
        return {
            "ok": True,
            "message": f"Key valid; {title} ({ODDS_SPORT_KEY}) available",
        }
    except Exception as e:
        return {"ok": False, "message": f"Odds test failed: {e}"}


def fetch_odds(
    cache: CacheStore,
    *,
    no_cache: bool = False,
    refresh_odds: bool = False,
    keys_path=None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """
    Returns (events, unavailable, warning_message).
    --no-cache does NOT refresh odds unless refresh_odds is True.
    Fetches only americanfootball_nfl spreads/totals (not Super Bowl futures).
    """
    key = "odds_nfl"
    bypass = refresh_odds  # only explicit odds refresh bypasses
    if not bypass:
        cached = cache.get_json(key, ODDS_TTL)
        if cached is not None:
            return cached, False, None
        # even with no_cache for other sources, prefer stale odds over new request
        if no_cache and not refresh_odds:
            stale = cache.get_json_stale(key)
            if stale is not None:
                return stale, False, None

    api_key = resolve_odds_api_key(keys_path)
    if not api_key:
        stale = cache.get_json_stale(key)
        if stale is not None:
            return stale, False, "ODDS_API_KEY missing; using cached odds"
        return [], True, "ODDS_API_KEY missing; using schedule lines for baselines where available"

    def loader():
        params = {
            "apiKey": api_key,
            "regions": "us",
            "markets": "spreads,totals",
            "oddsFormat": "american",
        }
        with httpx.Client(timeout=30.0) as client:
            r = client.get(ODDS_URL, params=params)
            if r.status_code != 200:
                soft = _soft_http_error(r)
                raise RuntimeError(soft or f"HTTP {r.status_code}")
            return r.json()

    try:
        payload, stale = cache.fetch_json(key, ODDS_TTL, loader, no_cache=bypass)
        return payload, False, ("stale odds cache" if stale else None)
    except Exception as e:
        stale = cache.get_json_stale(key)
        err = str(e)
        if stale is not None:
            return stale, False, f"Odds fetch failed ({err}); using stale cache"
        if "quota" in err.lower():
            return [], True, "Odds API quota exhausted"
        if "invalid" in err.lower() or "INVALID_KEY" in err:
            return [], True, "Odds API key invalid; using schedule lines"
        if err.startswith("Odds "):
            return [], True, err
        return [], True, f"Odds unavailable: {err}"


def average_odds_to_games(events: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """team full name -> {game_total, spread, home, away, implied totals} using averaged books."""
    out: dict[str, dict[str, float | str]] = {}
    for ev in events or []:
        # Defensive: ignore any non-NFL events if a mixed cache ever appears
        sport = ev.get("sport_key")
        if sport and sport != ODDS_SPORT_KEY:
            continue
        home = ev.get("home_team")
        away = ev.get("away_team")
        if not home or not away:
            continue
        spreads: list[float] = []
        totals: list[float] = []
        for book in ev.get("bookmakers") or []:
            for market in book.get("markets") or []:
                mkey = market.get("key")
                outcomes = market.get("outcomes") or []
                if mkey == "spreads":
                    for o in outcomes:
                        if o.get("name") == home and o.get("point") is not None:
                            spreads.append(float(o["point"]))
                if mkey == "totals":
                    for o in outcomes:
                        if o.get("name") == "Over" and o.get("point") is not None:
                            totals.append(float(o["point"]))
        if not totals:
            continue
        total = sum(totals) / len(totals)
        spread = sum(spreads) / len(spreads) if spreads else 0.0
        # home spread from home team's line: negative = favorite
        if spread <= 0:
            home_imp = (total / 2.0) + (abs(spread) / 2.0)
            away_imp = (total / 2.0) - (abs(spread) / 2.0)
        else:
            home_imp = (total / 2.0) - (abs(spread) / 2.0)
            away_imp = (total / 2.0) + (abs(spread) / 2.0)
        payload = {
            "home": home,
            "away": away,
            "game_total": total,
            "spread": spread,
            "home_implied_total": home_imp,
            "away_implied_total": away_imp,
            "game_id": str(ev.get("id") or f"{away}@{home}"),
        }
        out[str(home)] = payload  # type: ignore
        out[str(away)] = payload  # type: ignore
    return out  # type: ignore
