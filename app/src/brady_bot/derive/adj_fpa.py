from __future__ import annotations

import polars as pl

from brady_bot.config import LeagueConfig
from brady_bot.derive.blending import (
    blend_rates,
    is_blended_week,
    max_reg_week_from_frames,
    prior_season_week_window,
)
from brady_bot.fantasy import score_player_games
from brady_bot.normalizer import normalize_team
from brady_bot.sources.schema import PS_OPPONENT_TEAM, PS_POSITION


class AdjFpaError(Exception):
    pass


def _normalize_rate_keys(
    rates: dict[str, float], aliases: dict[str, str] | None
) -> dict[str, float]:
    if not aliases:
        return {str(k).upper(): v for k, v in rates.items()}
    out: dict[str, float] = {}
    for k, v in rates.items():
        out[normalize_team(str(k), aliases)] = v
    return out


def _filter_position(df: pl.DataFrame, position: str) -> pl.DataFrame:
    if PS_POSITION not in df.columns:
        return df
    if position == "RB":
        return df.filter(pl.col(PS_POSITION).is_in(["RB", "FB"]))
    return df.filter(pl.col(PS_POSITION) == position)


def _rates_for_season(
    player_stats: pl.DataFrame,
    position: str,
    season: int,
    through_week: int | None,
    cfg: LeagueConfig,
    *,
    week_lo: int | None = None,
) -> dict[str, float]:
    """Per-opponent Adj FPA rates (ppg − league mean). Empty if insufficient data."""
    df = player_stats
    if df.is_empty():
        return {}
    if "season" in df.columns:
        df = df.filter(pl.col("season") == season)
    if "season_type" in df.columns:
        df = df.filter(pl.col("season_type") == "REG")
    if through_week is not None and through_week <= 0:
        return {}
    if "week" in df.columns:
        if week_lo is not None:
            df = df.filter(pl.col("week") >= week_lo)
        if through_week is not None and through_week > 0:
            df = df.filter(pl.col("week") <= through_week)

    df = _filter_position(df, position)
    if df.is_empty():
        return {}

    df = score_player_games(df, cfg)

    opp_col = None
    for c in (PS_OPPONENT_TEAM, "opponent", "defteam"):
        if c in df.columns:
            opp_col = c
            break
    if opp_col is None:
        raise AdjFpaError("player_stats missing opponent team column")

    week_col = "week" if "week" in df.columns else None
    grouped = df.group_by(opp_col).agg(
        pl.col("fantasy_points").sum().alias("fp"),
        pl.col(week_col).n_unique().alias("games") if week_col else pl.len().alias("games"),
    )
    grouped = grouped.with_columns((pl.col("fp") / pl.col("games")).alias("ppg"))
    if grouped.height == 0:
        return {}

    mean = float(grouped["ppg"].mean())
    return {str(r[opp_col]): float(r["ppg"]) - mean for r in grouped.to_dicts()}


def derive_adj_fpa(
    player_stats: pl.DataFrame,
    schedules: pl.DataFrame,
    position: str,
    season: int,
    through_week: int,
    cfg: LeagueConfig,
    *,
    week: int | None = None,
    prior_week_lo: int | None = None,
    prior_week_hi: int | None = None,
    team_aliases: dict[str, str] | None = None,
) -> dict[str, float]:
    """
    Adj FPA by opponent team. For Weeks 1–4, blend prior-season last-4 REG weeks
    with current-season rates through completed weeks. Does not change matchup
    weight or percentile scoring.
    """
    blend_week = week if week is not None else through_week
    current = _normalize_rate_keys(
        _rates_for_season(player_stats, position, season, through_week, cfg),
        team_aliases,
    )

    if not is_blended_week(blend_week):
        if len(current) < 32:
            raise AdjFpaError(f"Adj FPA for {position} has {len(current)} teams, expected 32")
        return current

    if prior_week_lo is None or prior_week_hi is None:
        max_reg = max_reg_week_from_frames(season - 1, schedules, player_stats)
        prior_week_lo, prior_week_hi = prior_season_week_window(max_reg)

    prior = _normalize_rate_keys(
        _rates_for_season(
            player_stats,
            position,
            season - 1,
            prior_week_hi,
            cfg,
            week_lo=prior_week_lo,
        ),
        team_aliases,
    )
    if len(prior) < 32 and len(current) < 32:
        raise AdjFpaError(
            f"Adj FPA for {position} has prior={len(prior)} current={len(current)} teams, expected 32"
        )

    teams = set(prior) | set(current)
    if len(teams) < 32 and len(prior) >= 32:
        teams = set(prior)
    if len(teams) < 32:
        raise AdjFpaError(f"Adj FPA for {position} blended to {len(teams)} teams, expected 32")

    result: dict[str, float] = {}
    for team in teams:
        p = prior.get(team)
        c = current.get(team)
        if p is None and c is None:
            continue
        if p is None:
            result[team] = c  # type: ignore[assignment]
        elif c is None:
            result[team] = p
        else:
            result[team] = blend_rates(p, c, blend_week)

    if len(result) < 32:
        raise AdjFpaError(f"Adj FPA for {position} has {len(result)} teams after blend, expected 32")
    return result


def matchup_score(adj_fpa: dict[str, float], team: str, mode: str = "percentile") -> float:
    key = team.upper() if team else team
    if key not in adj_fpa:
        # try raw then fail soft
        if team not in adj_fpa:
            return 0.5
        key = team
    if mode == "linear":
        return max(0.0, min(1.0, (adj_fpa[key] + 10.0) / 20.0))
    # percentile: rank 1 = lowest FPA = strongest D → score 0
    ordered = sorted(adj_fpa.items(), key=lambda kv: kv[1])  # ascending FPA
    ranks = {t: i + 1 for i, (t, _) in enumerate(ordered)}
    rank = ranks.get(key, 16)
    return (rank - 1) / 31.0
