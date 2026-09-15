from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from brady_bot import auth as auth_mod
from brady_bot import api_keys as api_keys_mod
from brady_bot.config import load_config
from brady_bot.derive.context import build_week_context
from brady_bot.derive.injuries import build_injury_map
from brady_bot.derive.opportunity_board import build_team_board, completed_weeks
from brady_bot.derive.true_depth import build_team_payload
from brady_bot.models import Player, Position
from brady_bot.normalizer import normalize_team
from brady_bot.optimizer import optimize_lineup
from brady_bot.paths import DATA_DIR, MODULE_ROOT, ensure_dirs
from brady_bot.players_index import NFL_TEAMS, TEAM_NAMES, PlayersIndex
from brady_bot.predictions import append_predictions
from brady_bot.schedule_week import (
    bye_teams_for_week,
    opponents_for_week,
    resolve_focus_week,
)
from brady_bot.sources.cache import CacheStore
from brady_bot.sources import nflverse
from brady_bot.sources.odds import check_odds_api_key

load_dotenv(MODULE_ROOT / ".env")
ensure_dirs()
api_keys_mod.ensure_seeded()

SESSION_SECRET = os.environ.get("BRADY_SESSION_SECRET", "brady-bot-dev-session-secret")

_PUBLIC_API = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/admin/unlock"),
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        if path.startswith("/api/") and (method, path) not in _PUBLIC_API:
            if path.startswith("/api/admin/"):
                # Admin CRUD needs unlock only (allows creating the first user before login)
                if not request.session.get("admin"):
                    return JSONResponse({"detail": "Admin unlock required"}, status_code=403)
            elif not request.session.get("user"):
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return await call_next(request)


app = FastAPI(title="Brady Bot", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="brady_session",
    same_site="lax",
)

_cfg = load_config()
_cache = CacheStore()
_index: PlayersIndex | None = None
_roster_ui_path = DATA_DIR / "roster_ui.json"
# Overridable in tests
users_path = auth_mod.USERS_PATH
api_keys_path = api_keys_mod.API_KEYS_PATH


def get_index() -> PlayersIndex:
    global _index
    if _index is None:
        _index = PlayersIndex.build(_cache, _cfg.team_aliases)
    return _index


def _session_username(request: Request) -> str | None:
    user = request.session.get("user") or {}
    return user.get("username")


def _is_superadmin(request: Request) -> bool:
    username = _session_username(request)
    return bool(
        username
        and auth_mod.normalize_username(username) == auth_mod.SUPERADMIN_USERNAME
    )


def _require_superadmin(request: Request) -> None:
    if not _is_superadmin(request):
        raise HTTPException(403, "Superadmin only")


class SlotPlayer(BaseModel):
    slot: str
    player: Optional[dict[str, Any]] = None


class RosterPayload(BaseModel):
    week: Optional[int] = None
    bn_extra: int = 0
    ir_extra: int = 0
    slots: list[SlotPlayer] = Field(default_factory=list)


class PickPayload(RosterPayload):
    week: int = 1
    no_cache: bool = False
    refresh_odds: bool = False


class LoginPayload(BaseModel):
    username: str
    password: str


class AdminUnlockPayload(BaseModel):
    password: str


class UserCreatePayload(BaseModel):
    username: str
    password: str


class UserUpdatePayload(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None


class ApiCreatePayload(BaseModel):
    id: str
    label: str
    key: str


class ApiUpdatePayload(BaseModel):
    label: Optional[str] = None
    key: Optional[str] = None


@app.get("/api/health")
def health():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}


@app.post("/api/auth/login")
def auth_login(payload: LoginPayload, request: Request):
    user = auth_mod.authenticate(payload.username, payload.password, users_path)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    request.session.clear()
    request.session["user"] = {
        "id": user["id"],
        "username": user["username"],
    }
    return {"ok": True, "user": auth_mod.public_user(user)}


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {
        "user": user,
        "admin": bool(request.session.get("admin")),
        "is_superadmin": _is_superadmin(request),
    }


@app.post("/api/admin/unlock")
def admin_unlock(payload: AdminUnlockPayload, request: Request):
    if not auth_mod.check_admin_password(payload.password):
        raise HTTPException(403, "Invalid admin password")
    request.session["admin"] = True
    return {"ok": True}


@app.get("/api/admin/users")
def admin_list_users():
    return {"users": [auth_mod.public_user(u) for u in auth_mod.load_users(users_path)]}


@app.post("/api/admin/users")
def admin_create_user(payload: UserCreatePayload):
    try:
        user = auth_mod.create_user(payload.username, payload.password, users_path)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return auth_mod.public_user(user)


@app.put("/api/admin/users/{user_id}")
def admin_update_user(user_id: str, payload: UserUpdatePayload):
    if payload.username is None and payload.password is None:
        raise HTTPException(400, "Provide username and/or password to update")
    try:
        user = auth_mod.update_user(
            user_id,
            username=payload.username,
            password=payload.password,
            path=users_path,
        )
    except KeyError as e:
        raise HTTPException(404, "User not found") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return auth_mod.public_user(user)


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(user_id: str):
    try:
        auth_mod.delete_user(user_id, users_path)
    except KeyError as e:
        raise HTTPException(404, "User not found") from e
    return {"ok": True}


@app.get("/api/admin/apis")
def admin_list_apis(request: Request):
    _require_superadmin(request)
    return {"apis": api_keys_mod.list_apis(api_keys_path)}


@app.get("/api/admin/apis/{api_id}")
def admin_get_api(api_id: str, request: Request):
    _require_superadmin(request)
    try:
        return api_keys_mod.get_api(api_id, api_keys_path, full_key=True)
    except KeyError as e:
        raise HTTPException(404, "API not found") from e


@app.post("/api/admin/apis")
def admin_create_api(payload: ApiCreatePayload, request: Request):
    _require_superadmin(request)
    try:
        return api_keys_mod.create_api(
            payload.id, payload.label, payload.key, api_keys_path
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.put("/api/admin/apis/{api_id}")
def admin_update_api(api_id: str, payload: ApiUpdatePayload, request: Request):
    _require_superadmin(request)
    if payload.label is None and payload.key is None:
        raise HTTPException(400, "Provide label and/or key to update")
    try:
        return api_keys_mod.update_api(
            api_id,
            label=payload.label,
            key=payload.key,
            path=api_keys_path,
        )
    except KeyError as e:
        raise HTTPException(404, "API not found") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/admin/apis/{api_id}")
def admin_delete_api(api_id: str, request: Request):
    _require_superadmin(request)
    try:
        api_keys_mod.delete_api(api_id, api_keys_path)
    except KeyError as e:
        raise HTTPException(404, "API not found") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@app.post("/api/admin/apis/the_odds_api/test")
def admin_test_odds_api(request: Request):
    _require_superadmin(request)
    key = api_keys_mod.get_key(api_keys_mod.ODDS_API_ID, api_keys_path)
    return check_odds_api_key(key)


def _focus_meta() -> dict[str, Any]:
    season = _cfg.league.season
    schedules = nflverse.load_schedules(_cache, [season])
    week = resolve_focus_week(schedules, season)
    opponents_by_team = opponents_for_week(schedules, season, week, _cfg.team_aliases)
    bye_teams = bye_teams_for_week(schedules, season, week, _cfg.team_aliases)
    # Full report labels for roster/lineup card badges (Out, Questionable, …)
    injuries_by_player: dict[str, str] = {}
    try:
        injuries_df = nflverse.load_injuries(_cache, [season])
        inj_map = build_injury_map(injuries_df, week)
        for pid, rec in inj_map.items():
            if rec.report_status:
                injuries_by_player[pid] = rec.report_status
    except Exception:
        injuries_by_player = {}
    return {
        "week": week,
        "season": season,
        "opponents_by_team": opponents_by_team,
        "bye_teams": bye_teams,
        "injuries_by_player": injuries_by_player,
    }


@app.get("/api/meta/week")
def meta_week():
    """Focus week = lowest REG week with any incomplete game (null scores)."""
    try:
        return _focus_meta()
    except Exception:
        return {
            "week": 1,
            "season": _cfg.league.season,
            "opponents_by_team": {},
            "bye_teams": [],
            "injuries_by_player": {},
        }


@app.post("/api/refresh")
def refresh_data():
    """Force nflverse sources to refetch now, bypassing their normal cache TTL.

    Odds are deliberately excluded — same convention as lineup pick's plain
    no_cache flag — since refreshing odds burns paid API quota and needs the
    explicit refresh_odds opt-in instead.
    """
    season = _cfg.league.season
    loaders = {
        "schedules": nflverse.load_schedules,
        "player_stats": nflverse.load_player_stats,
        "team_stats": nflverse.load_team_stats,
        "snap_counts": nflverse.load_snap_counts,
        "injuries": nflverse.load_injuries,
        "depth_charts": nflverse.load_depth_charts,
        "pbp": nflverse.load_pbp,
    }
    sources: dict[str, str] = {}
    for name, loader in loaders.items():
        try:
            loader(_cache, [season], no_cache=True)
            sources[name] = "ok"
        except Exception as e:
            sources[name] = f"error: {e}"
    return {
        "season": season,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
    }


@app.get("/api/players/search")
def players_search(q: str = "", slot: str = "BN"):
    if len(q.strip()) < 2:
        return []
    hits = get_index().search(q, slot)
    return [h.as_dict() for h in hits]


@app.get("/api/roster")
def get_roster():
    if _roster_ui_path.exists():
        return json.loads(_roster_ui_path.read_text())
    return {"bn_extra": 0, "ir_extra": 0, "slots": []}


@app.put("/api/roster")
def put_roster(payload: RosterPayload):
    _roster_ui_path.write_text(payload.model_dump_json(indent=2))
    return {"ok": True}


def _players_from_payload(payload: RosterPayload) -> tuple[list[Player], set[str]]:
    idx = get_index()
    players: list[Player] = []
    ir_ids: set[str] = set()
    seen: set[str] = set()
    for entry in payload.slots:
        if not entry.player:
            continue
        pid = entry.player.get("player_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        p = idx.to_player(pid)
        if not p:
            # build from payload
            pos = entry.player.get("position", "WR")
            p = Player(
                player_id=pid,
                name=entry.player.get("name", pid),
                team=entry.player.get("team", ""),
                position=Position(pos if pos != "DST" else "DEF"),
                headshot=entry.player.get("headshot"),
            )
        if entry.slot.startswith("IR"):
            ir_ids.add(pid)
        players.append(p)
    return players, ir_ids


@app.post("/api/lineup/pick")
def pick_lineup(payload: PickPayload):
    players, ir_ids = _players_from_payload(payload)
    if not players:
        raise HTTPException(400, "Roster is empty")
    try:
        # Always use server focus week so UI and engine stay aligned
        schedules = nflverse.load_schedules(
            _cache, [_cfg.league.season], no_cache=payload.no_cache
        )
        focus_week = resolve_focus_week(schedules, _cfg.league.season)
        ctx = build_week_context(
            players,
            _cfg,
            focus_week,
            _cache,
            no_cache=payload.no_cache,
            refresh_odds=payload.refresh_odds,
        )
        lineup = optimize_lineup(ctx, _cfg, ir_ids=ir_ids)
        append_predictions(lineup)
        return lineup.model_dump()
    except Exception as e:
        raise HTTPException(500, str(e)) from e


# Static files last
app.mount("/assets", StaticFiles(directory=str(MODULE_ROOT / "assets")), name="assets")
app.mount("/js", StaticFiles(directory=str(MODULE_ROOT / "js")), name="js")

@app.get("/api/true-depth")
def true_depth_list():
    """All 32 teams, always — every team has a published chart to fall back on."""
    return {
        "teams": [
            {"code": code, "name": TEAM_NAMES.get(code, code)} for code in NFL_TEAMS
        ]
    }


@app.get("/api/true-depth/{team}")
def true_depth_team(team: str):
    """Live artifact payload built from nflreadpy at request time."""
    code = normalize_team(team.strip().upper(), _cfg.team_aliases)
    if code not in set(NFL_TEAMS):
        raise HTTPException(404, f"Unknown team {code}")

    season = _cfg.league.season
    try:
        depth_charts = nflverse.load_depth_charts(_cache, [season])
        injuries = nflverse.load_injuries(_cache, [season])
        player_stats = nflverse.load_player_stats(_cache, [season])
    except Exception as e:
        raise HTTPException(502, f"nflreadpy unavailable: {e}") from e

    try:
        schedules = nflverse.load_schedules(_cache, [season])
        week = resolve_focus_week(schedules, season)
    except Exception:
        week = 1

    payload = build_team_payload(
        depth_charts,
        injuries,
        player_stats,
        code,
        week=week,
        team_aliases=_cfg.team_aliases,
    )
    columns = payload.get("columns") or {}
    if not any(columns.get(pos) for pos in ("QB", "RB", "WR", "TE")):
        raise HTTPException(
            404, f"No published depth chart available for {code} yet this season"
        )
    payload["team_name"] = TEAM_NAMES.get(code, code)
    payload["season"] = season
    return payload


@app.get("/")
def index():
    return FileResponse(MODULE_ROOT / "index.html")


@app.get("/true-depth")
@app.get("/true-depth.html")
def true_depth_page():
    return FileResponse(MODULE_ROOT / "true-depth.html")


@app.get("/api/opportunity-share")
def opportunity_share_meta():
    """Season, completed weeks, and team list for the Opportunity Share filters."""
    season = _cfg.league.season
    weeks: list[int] = []
    try:
        player_stats = nflverse.load_player_stats(_cache, [season])
        weeks = list(completed_weeks(player_stats))
    except Exception:
        weeks = []
    return {
        "season": season,
        "completed_weeks": weeks,
        "teams": [
            {"code": code, "name": TEAM_NAMES.get(code, code)} for code in NFL_TEAMS
        ],
    }


@app.get("/api/opportunity-share/{team}")
def opportunity_share_team(team: str, view: str = "all"):
    """One-team Opportunity Share board for view=all or a completed week number."""
    code = normalize_team(team.strip().upper(), _cfg.team_aliases)
    if code not in set(NFL_TEAMS):
        raise HTTPException(404, f"Unknown team {code}")

    season = _cfg.league.season
    try:
        player_stats = nflverse.load_player_stats(_cache, [season])
        pbp = nflverse.load_pbp(_cache, [season])
    except Exception as e:
        raise HTTPException(502, f"nflreadpy unavailable: {e}") from e

    view_key = (view or "all").strip().lower()
    try:
        payload = build_team_board(
            player_stats,
            pbp,
            code,
            view_key,
            season=season,
            team_aliases=_cfg.team_aliases,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    if not payload.get("rows"):
        label = "season to date" if view_key == "all" else f"week {view_key}"
        raise HTTPException(
            404, f"No opportunity share data for {code} ({label}) yet"
        )

    payload["team_name"] = TEAM_NAMES.get(code, code)
    return payload


@app.get("/opportunity-share")
@app.get("/opportunity-share.html")
def opportunity_share_page():
    return FileResponse(MODULE_ROOT / "opportunity-share.html")


@app.get("/login")
@app.get("/login.html")
def login_page():
    return FileResponse(MODULE_ROOT / "login.html")


@app.get("/atlas.css")
def atlas_css():
    return FileResponse(MODULE_ROOT / "atlas.css", media_type="text/css")


@app.get("/custom.css")
def custom_css():
    return FileResponse(MODULE_ROOT / "custom.css", media_type="text/css")
