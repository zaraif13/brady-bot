from __future__ import annotations

import polars as pl

from brady_bot.config import LeagueConfig
from brady_bot.sources.schema import (
    PS_CARRIES,
    PS_FG_MADE_0_19,
    PS_FG_MADE_20_29,
    PS_FG_MADE_30_39,
    PS_FG_MADE_40_49,
    PS_FG_MADE_50_59,
    PS_FG_MADE_60,
    PS_FG_MISSED_0_19,
    PS_FG_MISSED_20_29,
    PS_PASSING_2PT,
    PS_PASSING_INTERCEPTIONS,
    PS_PASSING_TDS,
    PS_PASSING_YARDS,
    PS_PAT_MADE,
    PS_PAT_MISSED,
    PS_RECEIVING_2PT,
    PS_RECEIVING_FUMBLES_LOST,
    PS_RECEIVING_TDS,
    PS_RECEIVING_YARDS,
    PS_RECEPTIONS,
    PS_RUSHING_2PT,
    PS_RUSHING_FUMBLES_LOST,
    PS_RUSHING_TDS,
    PS_RUSHING_YARDS,
    PS_TARGETS,
)

STAT_COLS = [
    "completions",
    "attempts",
    PS_PASSING_YARDS,
    PS_PASSING_TDS,
    PS_PASSING_INTERCEPTIONS,
    "sacks",
    "sack_yards",
    "passing_air_yards",
    "passing_yards_after_catch",
    "passing_first_downs",
    "passing_epa",
    PS_PASSING_2PT,
    "pacr",
    "dakota",
    PS_CARRIES,
    PS_RUSHING_YARDS,
    PS_RUSHING_TDS,
    "rushing_fumbles",
    PS_RUSHING_FUMBLES_LOST,
    "rushing_first_downs",
    "rushing_epa",
    PS_RUSHING_2PT,
    PS_RECEPTIONS,
    PS_TARGETS,
    PS_RECEIVING_YARDS,
    PS_RECEIVING_TDS,
    "receiving_fumbles",
    PS_RECEIVING_FUMBLES_LOST,
    "receiving_air_yards",
    "receiving_yards_after_catch",
    "receiving_first_downs",
    "receiving_epa",
    PS_RECEIVING_2PT,
    PS_FG_MADE_0_19,
    PS_FG_MADE_20_29,
    PS_FG_MADE_30_39,
    PS_FG_MADE_40_49,
    PS_FG_MADE_50_59,
    PS_FG_MADE_60,
    PS_FG_MISSED_0_19,
    PS_FG_MISSED_20_29,
    PS_PAT_MADE,
    PS_PAT_MISSED,
]


def fantasy_points_expr(scoring: dict[str, float]) -> pl.Expr:
    """League fantasy points per player-game. Null stats → 0 before arithmetic."""
    py = pl.col(PS_PASSING_YARDS).fill_null(0) / scoring.get("passing_yards_per_point", 30)
    ptd = pl.col(PS_PASSING_TDS).fill_null(0) * scoring.get("passing_td", 5)
    ints = pl.col(PS_PASSING_INTERCEPTIONS).fill_null(0) * scoring.get("interception", -2)
    ry = pl.col(PS_RUSHING_YARDS).fill_null(0) / scoring.get("rushing_yards_per_point", 10)
    rtd = pl.col(PS_RUSHING_TDS).fill_null(0) * scoring.get("rushing_td", 6)
    recy = pl.col(PS_RECEIVING_YARDS).fill_null(0) / scoring.get("receiving_yards_per_point", 10)
    rectd = pl.col(PS_RECEIVING_TDS).fill_null(0) * scoring.get("receiving_td", 6)
    rec = pl.col(PS_RECEPTIONS).fill_null(0) * scoring.get("reception", 0.5)
    fum = (
        pl.col(PS_RUSHING_FUMBLES_LOST).fill_null(0)
        + pl.col(PS_RECEIVING_FUMBLES_LOST).fill_null(0)
    ) * scoring.get("fumble_lost", -2)
    twopt = (
        pl.col(PS_PASSING_2PT).fill_null(0)
        + pl.col(PS_RUSHING_2PT).fill_null(0)
        + pl.col(PS_RECEIVING_2PT).fill_null(0)
    ) * scoring.get("two_point_conversion", 2)
    # Kicker — distance buckets + PAT; short-miss penalties (league-rules.md)
    fg = (
        pl.col(PS_FG_MADE_0_19).fill_null(0) * scoring.get("fg_0_19", 1)
        + pl.col(PS_FG_MADE_20_29).fill_null(0) * scoring.get("fg_20_29", 2)
        + pl.col(PS_FG_MADE_30_39).fill_null(0) * scoring.get("fg_30_39", 3)
        + pl.col(PS_FG_MADE_40_49).fill_null(0) * scoring.get("fg_40_49", 4)
        + (
            pl.col(PS_FG_MADE_50_59).fill_null(0)
            + pl.col(PS_FG_MADE_60).fill_null(0)
        )
        * scoring.get("fg_50_plus", 5)
    )
    fg_miss = (
        pl.col(PS_FG_MISSED_0_19).fill_null(0) * scoring.get("fg_missed_0_19", -2)
        + pl.col(PS_FG_MISSED_20_29).fill_null(0) * scoring.get("fg_missed_20_29", -1)
    )
    pat = pl.col(PS_PAT_MADE).fill_null(0) * scoring.get("pat_made", 1)
    pat_miss = pl.col(PS_PAT_MISSED).fill_null(0) * scoring.get("pat_missed", -1)
    return (
        py + ptd + ints + ry + rtd + recy + rectd + rec + fum + twopt + fg + fg_miss + pat + pat_miss
    ).alias("fantasy_points")


def ensure_stat_cols(df: pl.DataFrame) -> pl.DataFrame:
    out = df
    for c in STAT_COLS:
        if c not in out.columns:
            out = out.with_columns(pl.lit(0.0).alias(c))
    return out


def score_player_games(df: pl.DataFrame, cfg: LeagueConfig) -> pl.DataFrame:
    df = ensure_stat_cols(df)
    return df.with_columns(fantasy_points_expr(cfg.scoring))
