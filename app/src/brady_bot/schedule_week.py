"""Focus gameweek resolution from nflverse schedules."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import polars as pl

from brady_bot.normalizer import normalize_team
from brady_bot.players_index import NFL_TEAMS


def _reg_season(schedules: pl.DataFrame, season: int) -> pl.DataFrame:
    if schedules.is_empty():
        return schedules
    df = schedules
    if "season" in df.columns:
        df = df.filter(pl.col("season") == season)
    if "game_type" in df.columns:
        df = df.filter(pl.col("game_type") == "REG")
    return df


def _game_complete(row: dict) -> bool:
    home = row.get("home_score")
    away = row.get("away_score")
    return home is not None and away is not None


def resolve_focus_week(
    schedules: pl.DataFrame,
    season: int,
    now: Optional[datetime] = None,
) -> int:
    """
    Lowest REG week with at least one incomplete game.
    A game is complete when both home_score and away_score are non-null.
    If every REG game is complete, return the max week present.
    `now` is accepted for API symmetry / future use; completion is score-based.
    """
    _ = now or datetime.now(timezone.utc)
    df = _reg_season(schedules, season)
    if df.is_empty() or "week" not in df.columns:
        return 1

    weeks = sorted({int(w) for w in df["week"].to_list() if w is not None})
    if not weeks:
        return 1

    for week in weeks:
        wk = df.filter(pl.col("week") == week)
        incomplete = False
        for r in wk.to_dicts():
            if not _game_complete(r):
                incomplete = True
                break
        if incomplete:
            return week
    return weeks[-1]


def opponents_for_week(
    schedules: pl.DataFrame,
    season: int,
    week: int,
    aliases: dict[str, str],
) -> dict[str, str]:
    """Map team abbreviation -> opponent abbreviation, or BYE if not playing."""
    df = _reg_season(schedules, season)
    out: dict[str, str] = {t: "BYE" for t in NFL_TEAMS}
    if df.is_empty() or "week" not in df.columns:
        return out
    wk = df.filter(pl.col("week") == week)
    for r in wk.to_dicts():
        home = normalize_team(str(r.get("home_team") or ""), aliases)
        away = normalize_team(str(r.get("away_team") or ""), aliases)
        if not home or not away:
            continue
        out[home] = away
        out[away] = home
    return out


def bye_teams_for_week(
    schedules: pl.DataFrame,
    season: int,
    week: int,
    aliases: dict[str, str],
) -> list[str]:
    opps = opponents_for_week(schedules, season, week, aliases)
    return sorted(t for t, opp in opps.items() if opp == "BYE")
