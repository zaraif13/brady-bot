from __future__ import annotations

import polars as pl


def blend_weights(week: int) -> tuple[float, float]:
    """Return (prior_weight, current_weight)."""
    table = {
        1: (1.0, 0.0),
        2: (0.75, 0.25),
        3: (0.50, 0.50),
        4: (0.25, 0.75),
    }
    return table.get(week, (0.0, 1.0))


def blend_rates(prior: float, current: float, week: int) -> float:
    pw, cw = blend_weights(week)
    if pw == 0:
        return current
    if cw == 0:
        return prior
    return prior * pw + current * cw


def is_blended_week(week: int) -> bool:
    return week <= 4


def prior_season_week_window(max_reg_week: int, n: int = 4) -> tuple[int, int]:
    """Inclusive [lo, hi] for the last n REG fantasy weeks of a prior season."""
    if max_reg_week < 1:
        return (1, 1)
    hi = int(max_reg_week)
    lo = max(1, hi - n + 1)
    return (lo, hi)


def rb_prior_snap_week_window(max_reg_week: int) -> tuple[int, int]:
    """Prior-season weeks 10–18 for RB snap-share blending (§5.10)."""
    hi = min(18, int(max_reg_week)) if max_reg_week >= 1 else 18
    return (10, hi)


def max_reg_week_from_frames(
    season: int,
    *frames: pl.DataFrame,
    schedule_game_type: str = "REG",
) -> int:
    """
    Resolve max REG week for a season from schedules (preferred) or stats frames.
    Defaults to 18 when no week column data is present.
    """
    for df in frames:
        if df is None or df.is_empty() or "week" not in df.columns:
            continue
        d = df
        if "season" in d.columns:
            d = d.filter(pl.col("season") == season)
        if "game_type" in d.columns:
            d = d.filter(pl.col("game_type") == schedule_game_type)
        elif "season_type" in d.columns:
            d = d.filter(pl.col("season_type") == schedule_game_type)
        if d.is_empty() or "week" not in d.columns:
            continue
        mx = d["week"].max()
        if mx is not None:
            return int(mx)
    return 18


def filter_weeks(
    df: pl.DataFrame,
    *,
    season: int | None = None,
    week_lo: int | None = None,
    week_hi: int | None = None,
) -> pl.DataFrame:
    """Filter a frame to season and inclusive week range when columns exist."""
    if df.is_empty():
        return df
    d = df
    if season is not None and "season" in d.columns:
        d = d.filter(pl.col("season") == season)
    if "week" in d.columns:
        if week_lo is not None:
            d = d.filter(pl.col("week") >= week_lo)
        if week_hi is not None:
            d = d.filter(pl.col("week") <= week_hi)
    return d
