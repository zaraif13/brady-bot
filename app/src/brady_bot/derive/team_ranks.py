"""Team-level ranks from S3 (and S2 for QB turnovers). Tech spec §5.4–§5.7."""
from __future__ import annotations

import polars as pl

from brady_bot.derive.blending import (
    blend_rates,
    is_blended_week,
    max_reg_week_from_frames,
    prior_season_week_window,
)
from brady_bot.models import TeamStats
from brady_bot.normalizer import normalize_team
from brady_bot.sources.schema import (
    PS_PASSING_INTERCEPTIONS,
    PS_POSITION,
    PS_RUSHING_FUMBLES_LOST,
    PS_TEAM,
    TS_ATTEMPTS,
    TS_CARRIES,
    TS_FG_MADE,
    TS_OPPONENT_TEAM,
    TS_PASSING_INTERCEPTIONS,
    TS_PASSING_TDS,
    TS_PASSING_YARDS,
    TS_PAT_MADE,
    TS_RUSHING_TDS,
    TS_RUSHING_YARDS,
    TS_TEAM,
)


class TeamRanksError(Exception):
    """Team-rank derivation produced fewer than 32 teams."""


def _rank_desc(values: dict[str, float]) -> dict[str, int]:
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    return {t: i + 1 for i, (t, _) in enumerate(ordered)}


def _rank_asc(values: dict[str, float]) -> dict[str, int]:
    ordered = sorted(values.items(), key=lambda kv: kv[1])
    return {t: i + 1 for i, (t, _) in enumerate(ordered)}


def _clamp(r: int) -> int:
    return max(1, min(32, int(r)))


def _filter_season_weeks(
    df: pl.DataFrame,
    season: int,
    through_week: int,
    *,
    week_lo: int | None = None,
) -> pl.DataFrame:
    if df.is_empty():
        return df
    d = df
    if "season" in d.columns:
        d = d.filter(pl.col("season") == season)
    if "week" in d.columns:
        if week_lo is not None:
            d = d.filter(pl.col("week") >= week_lo)
        d = d.filter(pl.col("week") <= through_week)
    if "season_type" in d.columns:
        d = d.filter(pl.col("season_type") == "REG")
    return d


def _mean_by_team(
    df: pl.DataFrame,
    value_expr: pl.Expr,
    *,
    team_col: str = TS_TEAM,
) -> dict[str, float]:
    if df.is_empty() or team_col not in df.columns:
        return {}
    g = df.group_by(team_col).agg(value_expr.alias("v"))
    return {str(r[team_col]): float(r["v"] or 0) for r in g.to_dicts()}


def _offense_yards_pg(df: pl.DataFrame) -> dict[str, float]:
    """Total offensive yards per game = pass + rush."""
    if TS_PASSING_YARDS not in df.columns or TS_RUSHING_YARDS not in df.columns:
        return {}
    return _mean_by_team(
        df,
        (pl.col(TS_PASSING_YARDS).fill_null(0) + pl.col(TS_RUSHING_YARDS).fill_null(0)).mean(),
    )


def _offense_points_pg(df: pl.DataFrame) -> dict[str, float]:
    """Approx offensive points from TDs + FG/PAT (no drive table in V1)."""
    needed = (TS_PASSING_TDS, TS_RUSHING_TDS)
    if any(c not in df.columns for c in needed):
        return {}
    pts = (
        pl.col(TS_PASSING_TDS).fill_null(0) * 6
        + pl.col(TS_RUSHING_TDS).fill_null(0) * 6
    )
    if TS_FG_MADE in df.columns:
        pts = pts + pl.col(TS_FG_MADE).fill_null(0) * 3
    if TS_PAT_MADE in df.columns:
        pts = pts + pl.col(TS_PAT_MADE).fill_null(0) * 1
    return _mean_by_team(df, pts.mean())


def _yards_allowed_pg(df: pl.DataFrame) -> dict[str, float]:
    """Defense yards allowed = opponents' offensive yards (spec §4.4 fallback)."""
    if TS_OPPONENT_TEAM not in df.columns:
        return {}
    if TS_PASSING_YARDS not in df.columns or TS_RUSHING_YARDS not in df.columns:
        return {}
    # Row is team's offense vs opponent_team → opponent_team allowed these yards
    return _mean_by_team(
        df,
        (pl.col(TS_PASSING_YARDS).fill_null(0) + pl.col(TS_RUSHING_YARDS).fill_null(0)).mean(),
        team_col=TS_OPPONENT_TEAM,
    )


def _yards_allowed_per_play(df: pl.DataFrame) -> dict[str, float]:
    """Defense calibre proxy: yards allowed per opponent offensive play."""
    if TS_OPPONENT_TEAM not in df.columns:
        return {}
    need = (TS_PASSING_YARDS, TS_RUSHING_YARDS, TS_ATTEMPTS, TS_CARRIES)
    if any(c not in df.columns for c in need):
        return {}
    g = df.group_by(TS_OPPONENT_TEAM).agg(
        (pl.col(TS_PASSING_YARDS).fill_null(0) + pl.col(TS_RUSHING_YARDS).fill_null(0))
        .sum()
        .alias("yds"),
        (pl.col(TS_ATTEMPTS).fill_null(0) + pl.col(TS_CARRIES).fill_null(0)).sum().alias("plays"),
    )
    out: dict[str, float] = {}
    for r in g.to_dicts():
        plays = float(r["plays"] or 0)
        if plays <= 0:
            continue
        out[str(r[TS_OPPONENT_TEAM])] = float(r["yds"] or 0) / plays
    return out


def _qb_turnovers_pg(
    player_stats: pl.DataFrame,
    team_stats: pl.DataFrame,
    season: int,
    through_week: int,
    *,
    week_lo: int | None = None,
) -> dict[str, float]:
    """INTs + fumbles lost per game. Prefer S2 QB rows; fall back to S3 team cols."""
    if not player_stats.is_empty():
        ps = _filter_season_weeks(player_stats, season, through_week, week_lo=week_lo)
        if PS_POSITION in ps.columns:
            ps = ps.filter(pl.col(PS_POSITION) == "QB")
        team_c = PS_TEAM if PS_TEAM in ps.columns else (
            "recent_team" if "recent_team" in ps.columns else None
        )
        if team_c and not ps.is_empty():
            ints = (
                pl.col(PS_PASSING_INTERCEPTIONS).fill_null(0)
                if PS_PASSING_INTERCEPTIONS in ps.columns
                else pl.lit(0)
            )
            fum = (
                pl.col(PS_RUSHING_FUMBLES_LOST).fill_null(0)
                if PS_RUSHING_FUMBLES_LOST in ps.columns
                else pl.lit(0)
            )
            return _mean_by_team(ps.with_columns((ints + fum).alias("to")), pl.col("to").mean(), team_col=team_c)

    ts = _filter_season_weeks(team_stats, season, through_week, week_lo=week_lo)
    if TS_PASSING_INTERCEPTIONS not in ts.columns:
        return {}
    fum_col = "fumbles_lost_total" if "fumbles_lost_total" in ts.columns else None
    expr = pl.col(TS_PASSING_INTERCEPTIONS).fill_null(0)
    if fum_col:
        expr = expr + pl.col(fum_col).fill_null(0)
    return _mean_by_team(ts, expr.mean())


def _normalize_keys(raw: dict[str, float], aliases: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for t, v in raw.items():
        key = normalize_team(str(t), aliases) if aliases else str(t).upper()
        out[key] = v
    return out


def _blend_maps(
    cur: dict[str, float],
    prior: dict[str, float],
    week: int,
    *,
    blended: bool,
) -> dict[str, float]:
    if not blended:
        return cur
    teams = set(cur) | set(prior)
    return {
        t: blend_rates(prior.get(t, cur.get(t, 0.0)), cur.get(t, prior.get(t, 0.0)), week)
        for t in teams
    }


def derive_team_ranks(
    team_stats: pl.DataFrame,
    player_stats: pl.DataFrame,
    season: int,
    through_week: int,
    prior_team_stats: pl.DataFrame | None = None,
    *,
    blend_week: int | None = None,
    prior_week_lo: int | None = None,
    prior_week_hi: int | None = None,
    team_aliases: dict[str, str] | None = None,
) -> dict[str, TeamStats]:
    """
    Team ranks per §5.4. Always returns exactly 32 teams or raises TeamRanksError.

    Defense yards / YPP use opponents' offensive rows (no defense_yards column in S3).
    """
    week = blend_week if blend_week is not None else through_week
    blended = is_blended_week(week)
    aliases = team_aliases or {}

    if blended and (prior_week_lo is None or prior_week_hi is None):
        frames = [f for f in (prior_team_stats, team_stats, player_stats) if f is not None]
        max_reg = max_reg_week_from_frames(season - 1, *frames)
        prior_week_lo, prior_week_hi = prior_season_week_window(max_reg)

    cur_ts = _filter_season_weeks(team_stats, season, through_week)
    prior_ts = pl.DataFrame()
    if blended and prior_team_stats is not None:
        prior_ts = _filter_season_weeks(
            prior_team_stats,
            season - 1,
            prior_week_hi or 18,
            week_lo=prior_week_lo,
        )

    def metric(fn) -> dict[str, float]:
        cur = _normalize_keys(fn(cur_ts), aliases)
        if not blended or prior_ts.is_empty():
            return cur
        prior = _normalize_keys(fn(prior_ts), aliases)
        return _blend_maps(cur, prior, week, blended=True)

    off_ypg = metric(_offense_yards_pg)
    pts_pg = metric(_offense_points_pg)
    def_ypg = metric(_yards_allowed_pg)
    ypp_allowed = metric(_yards_allowed_per_play)

    rz: dict[str, float] = {}
    for t in set(off_ypg) | set(pts_pg):
        yards = off_ypg.get(t, 0.0)
        pts = pts_pg.get(t, 0.0)
        if yards <= 0:
            continue
        rz[t] = pts / (yards / 100.0)

    turnovers = _normalize_keys(
        _qb_turnovers_pg(player_stats, team_stats, season, through_week),
        aliases,
    )
    if blended and prior_team_stats is not None:
        prior_to = _normalize_keys(
            _qb_turnovers_pg(
                player_stats,
                prior_team_stats,
                season - 1,
                prior_week_hi or 18,
                week_lo=prior_week_lo,
            ),
            aliases,
        )
        turnovers = _blend_maps(turnovers, prior_to, week, blended=True)

    # Core S3-derived maps must each cover the league.
    # O-line quality is S10 (config/oline_ranks.yaml), not derived here.
    core = {
        "offense_yards_pg": off_ypg,
        "yards_allowed_pg": def_ypg,
        "scoring_efficiency": rz,
        "yards_allowed_per_play": ypp_allowed,
    }
    for name, mp in core.items():
        if len(mp) < 32:
            raise TeamRanksError(
                f"Team ranks metric {name!r} has {len(mp)} teams, expected 32 "
                f"(blended={blended}, through_week={through_week})"
            )

    all_teams = sorted(set(off_ypg))
    if len(all_teams) != 32:
        raise TeamRanksError(
            f"Team ranks has {len(all_teams)} teams, expected 32 "
            f"(blended={blended}, through_week={through_week})"
        )
    # Ensure every core map uses the same team set
    for name, mp in core.items():
        missing = [t for t in all_teams if t not in mp]
        if missing:
            raise TeamRanksError(
                f"Team ranks metric {name!r} missing teams {missing[:5]}…"
            )
    for t in all_teams:
        turnovers.setdefault(t, 0.0)

    off_rank = _rank_desc(off_ypg)
    def_rank = _rank_asc(def_ypg)
    rz_rank = _rank_asc(rz)  # rank 1 = least efficient (kicker-friendly)
    def_cal = _rank_asc(ypp_allowed)  # rank 1 = fewest yards/play allowed
    # Rank 1 = most turnovers (worst) so DEF "top-10 qb_turnover_rank" = worst ball security
    qb_to = _rank_desc(turnovers)

    return {
        t: TeamStats(
            team=t,
            season=season,
            through_week=through_week,
            blended=blended,
            offense_rank=_clamp(off_rank[t]),
            total_defense_rank=_clamp(def_rank[t]),
            scoring_efficiency_rank=_clamp(rz_rank[t]),
            defense_calibre_rank=_clamp(def_cal[t]),
            qb_turnover_rank=_clamp(qb_to[t]),
        )
        for t in all_teams
    }
