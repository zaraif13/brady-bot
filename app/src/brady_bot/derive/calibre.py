from __future__ import annotations

import polars as pl

from brady_bot.config import LeagueConfig
from brady_bot.fantasy import score_player_games
from brady_bot.sources.schema import PS_PLAYER_ID, PS_POSITION


def derive_player_calibre(
    player_stats: pl.DataFrame,
    position: str,
    season: int,
    through_week: int,
    cfg: LeagueConfig,
    min_games: int = 3,
) -> dict[str, int]:
    if player_stats.is_empty():
        return {}
    df = player_stats
    id_col = PS_PLAYER_ID if PS_PLAYER_ID in df.columns else "gsis_id"
    if "season" in df.columns:
        cur = df.filter(pl.col("season") == season)
        if "week" in cur.columns:
            cur = cur.filter(pl.col("week") <= through_week)
    else:
        cur = df
    if "season_type" in cur.columns:
        cur = cur.filter(pl.col("season_type") == "REG")
    if PS_POSITION in cur.columns:
        if position == "RB":
            cur = cur.filter(pl.col(PS_POSITION).is_in(["RB", "FB"]))
        else:
            cur = cur.filter(pl.col(PS_POSITION) == position)

    if cur.is_empty():
        return {}

    cur = score_player_games(cur, cfg)
    g = cur.group_by(id_col).agg(
        pl.col("fantasy_points").mean().alias("ppg"),
        pl.len().alias("games"),
    )

    prior_map: dict[str, float] = {}
    if "season" in df.columns:
        prior = df.filter(pl.col("season") == season - 1)
        if "season_type" in prior.columns:
            prior = prior.filter(pl.col("season_type") == "REG")
        if PS_POSITION in prior.columns:
            if position == "RB":
                prior = prior.filter(pl.col(PS_POSITION).is_in(["RB", "FB"]))
            else:
                prior = prior.filter(pl.col(PS_POSITION) == position)
        if prior.height:
            prior = score_player_games(prior, cfg)
            pg = prior.group_by(id_col).agg(pl.col("fantasy_points").mean().alias("ppg"))
            prior_map = {str(r[id_col]): float(r["ppg"]) for r in pg.to_dicts()}

    scores: dict[str, float] = {}
    for r in g.to_dicts():
        pid = str(r[id_col])
        if int(r["games"]) >= min_games:
            scores[pid] = float(r["ppg"])
        elif pid in prior_map:
            scores[pid] = prior_map[pid]
        else:
            scores[pid] = -999.0

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return {pid: i + 1 for i, (pid, _) in enumerate(ordered)}
