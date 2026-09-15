"""Opportunity Share "All" view — docs/depth-chart/opportunity_share.md Steps 1, 3b/3c, 7.

Only the two metrics the True Depth Chart consumes are built here: season-to-date
Target Share (WR/TE pecking order) and Rush Share (RB pecking order). Red-zone
share needs play-by-play and is explicitly out of scope for this version.

The averaging convention is the whole point of this module and the easiest thing
to get silently wrong: a player's "All" share is the **mean of their weekly
shares over the weeks they actually qualified in**, never a season-total ratio
and never an average that folds missed weeks in as 0%.
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from brady_bot.normalizer import normalize_team
from brady_bot.sources.schema import (
    PS_CARRIES,
    PS_PLAYER_ID,
    PS_PLAYER_NAME,
    PS_POSITION,
    PS_SEASON_TYPE,
    PS_TARGET_SHARE,
    PS_TARGETS,
    PS_TEAM,
    PS_WEEK,
)

REGULAR_SEASON = "REG"

# opportunity_share.md Step 8 — hard cutoff on the active rush_share_pct view.
BELLCOW_RUSH_SHARE_PCT = 60.0


@dataclass(frozen=True)
class ShareRow:
    """One player's usage on one team (All-view average or a single week)."""

    team: str
    player_id: str
    player: str
    position: str
    target_share_pct: float | None
    targets: int | None
    gp_tgt: int
    rush_share_pct: float | None
    carries: int | None
    gp_rsh: int


@dataclass(frozen=True)
class AllView:
    """Season-to-date share table, indexed for per-team lookups."""

    rows: tuple[ShareRow, ...]
    completed_weeks: tuple[int, ...]

    def by_team(self, team: str) -> list[ShareRow]:
        return [r for r in self.rows if r.team == team]

    def is_empty(self) -> bool:
        return not self.rows


@dataclass(frozen=True)
class WeekView:
    """Single-week share table (latest gameweek annotations)."""

    week: int
    rows: tuple[ShareRow, ...]

    def by_team(self, team: str) -> list[ShareRow]:
        return [r for r in self.rows if r.team == team]

    def is_empty(self) -> bool:
        return not self.rows


def _round1(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def _regular_season_frame(player_stats: pl.DataFrame) -> pl.DataFrame:
    if player_stats.is_empty():
        return player_stats
    df = player_stats
    if PS_SEASON_TYPE in df.columns:
        df = df.filter(pl.col(PS_SEASON_TYPE) == REGULAR_SEASON)
    df = df.filter(pl.col(PS_TEAM).is_not_null() & pl.col(PS_PLAYER_ID).is_not_null())
    if df.is_empty():
        return df
    return df.with_columns(
        pl.col(PS_TARGETS).fill_null(0),
        pl.col(PS_CARRIES).fill_null(0),
    )


def _merge_week_rows(
    tgt_rows: list[dict],
    rsh_rows: list[dict],
    aliases: dict[str, str],
) -> list[ShareRow]:
    """Merge target + rush populations for one week into ShareRow list."""
    acc: dict[tuple[str, str], dict] = {}

    def slot(row: dict) -> dict:
        team = normalize_team(str(row[PS_TEAM]), aliases)
        key = (team, str(row[PS_PLAYER_ID]))
        entry = acc.get(key)
        if entry is None:
            entry = {
                "team": team,
                "player_id": str(row[PS_PLAYER_ID]),
                "player": str(row.get(PS_PLAYER_NAME) or ""),
                "position": str(row.get(PS_POSITION) or ""),
                "target_share_pct": None,
                "targets": None,
                "rush_share_pct": None,
                "carries": None,
            }
            acc[key] = entry
        if row.get(PS_PLAYER_NAME):
            entry["player"] = str(row[PS_PLAYER_NAME])
        if row.get(PS_POSITION):
            entry["position"] = str(row[PS_POSITION])
        return entry

    for row in tgt_rows:
        entry = slot(row)
        pct = row.get("target_share_pct")
        if pct is not None:
            entry["target_share_pct"] = float(pct)
            entry["targets"] = int(row.get(PS_TARGETS) or 0)

    for row in rsh_rows:
        entry = slot(row)
        pct = row.get("rush_share_pct")
        if pct is not None:
            entry["rush_share_pct"] = float(pct)
            entry["carries"] = int(row.get(PS_CARRIES) or 0)

    rows = [
        ShareRow(
            team=e["team"],
            player_id=e["player_id"],
            player=e["player"],
            position=e["position"],
            target_share_pct=_round1(e["target_share_pct"]),
            targets=e["targets"],
            gp_tgt=1 if e["target_share_pct"] is not None else 0,
            rush_share_pct=_round1(e["rush_share_pct"]),
            carries=e["carries"],
            gp_rsh=1 if e["rush_share_pct"] is not None else 0,
        )
        for e in acc.values()
    ]
    rows.sort(key=lambda r: (r.team, r.player_id))
    return rows


def build_week_view(
    player_stats: pl.DataFrame,
    week: int,
    team_aliases: dict[str, str] | None = None,
) -> WeekView:
    """Single-week Target Share / Rush Share (opportunity_share.md Steps 3b/3c)."""
    aliases = team_aliases or {}
    df = _regular_season_frame(player_stats)
    if df.is_empty():
        return WeekView(week=week, rows=())

    df = df.filter(pl.col(PS_WEEK) == week)
    if df.is_empty():
        return WeekView(week=week, rows=())

    rows = _merge_week_rows(
        _weekly_target_share(df).to_dicts(),
        _weekly_rush_share(df).to_dicts(),
        aliases,
    )
    return WeekView(week=week, rows=tuple(rows))


def is_bellcow(rush_share_pct: float | None) -> bool:
    """RB bellcow flag — rush share >= 60.0 (hard cutoff)."""
    return rush_share_pct is not None and rush_share_pct >= BELLCOW_RUSH_SHARE_PCT


def _weekly_target_share(df: pl.DataFrame) -> pl.DataFrame:
    """Step 3b — population is any player with targets > 0 that week."""
    tgt = df.filter(pl.col(PS_TARGETS) > 0)
    if tgt.is_empty():
        return tgt.select(
            [PS_WEEK, PS_TEAM, PS_PLAYER_ID, PS_PLAYER_NAME, PS_POSITION, PS_TARGETS]
        ).with_columns(pl.lit(None, dtype=pl.Float64).alias("target_share_pct"))

    if PS_TARGET_SHARE in tgt.columns:
        share = pl.col(PS_TARGET_SHARE) * 100
    else:
        # nflreadpy ships target_share natively; derive the identical value if a
        # cached frame predates the column.
        team_targets = pl.col(PS_TARGETS).sum().over([PS_WEEK, PS_TEAM])
        share = pl.col(PS_TARGETS) / team_targets * 100

    return tgt.with_columns(share.round(1).alias("target_share_pct")).select(
        [
            PS_WEEK,
            PS_TEAM,
            PS_PLAYER_ID,
            PS_PLAYER_NAME,
            PS_POSITION,
            PS_TARGETS,
            "target_share_pct",
        ]
    )


def _weekly_rush_share(df: pl.DataFrame) -> pl.DataFrame:
    """Step 3c — RB carries over the team's carries by *every* rusher that week."""
    team_carries = pl.col(PS_CARRIES).sum().over([PS_WEEK, PS_TEAM])
    rb = df.with_columns(team_carries.alias("_team_carries")).filter(
        (pl.col(PS_POSITION) == "RB") & (pl.col(PS_CARRIES) > 0)
    )
    return rb.with_columns(
        (pl.col(PS_CARRIES) / pl.col("_team_carries") * 100).round(1).alias("rush_share_pct")
    ).select(
        [
            PS_WEEK,
            PS_TEAM,
            PS_PLAYER_ID,
            PS_PLAYER_NAME,
            PS_POSITION,
            PS_CARRIES,
            "rush_share_pct",
        ]
    )


def build_all_view(
    player_stats: pl.DataFrame,
    team_aliases: dict[str, str] | None = None,
) -> AllView:
    """Season-to-date Target Share / Rush Share per (team, player).

    ``player_stats`` is one season of ``nflreadpy.load_player_stats`` output.
    Postseason rows are dropped; everything else is derived in memory.
    """
    aliases = team_aliases or {}
    df = _regular_season_frame(player_stats)
    if df.is_empty():
        return AllView(rows=(), completed_weeks=())

    completed_weeks = tuple(sorted(int(w) for w in df[PS_WEEK].unique().to_list()))

    tgt_rows = _weekly_target_share(df).to_dicts()
    rsh_rows = _weekly_rush_share(df).to_dicts()

    # Step 7 — group each metric by (team, player) and average over that
    # player's own qualifying weeks. A week with no row is absent, not a zero.
    acc: dict[tuple[str, str], dict] = {}

    def slot(row: dict) -> dict:
        team = normalize_team(str(row[PS_TEAM]), aliases)
        key = (team, str(row[PS_PLAYER_ID]))
        entry = acc.get(key)
        if entry is None:
            entry = {
                "team": team,
                "player_id": str(row[PS_PLAYER_ID]),
                "latest_week": -1,
                "player": "",
                "position": "",
                "tgt_pcts": [],
                "targets": 0,
                "rsh_pcts": [],
                "carries": 0,
            }
            acc[key] = entry
        week = int(row[PS_WEEK])
        if week >= entry["latest_week"]:
            entry["latest_week"] = week
            entry["player"] = str(row.get(PS_PLAYER_NAME) or entry["player"])
            entry["position"] = str(row.get(PS_POSITION) or entry["position"])
        return entry

    for row in tgt_rows:
        entry = slot(row)
        pct = row.get("target_share_pct")
        if pct is not None:
            entry["tgt_pcts"].append(float(pct))
            entry["targets"] += int(row.get(PS_TARGETS) or 0)

    for row in rsh_rows:
        entry = slot(row)
        pct = row.get("rush_share_pct")
        if pct is not None:
            entry["rsh_pcts"].append(float(pct))
            entry["carries"] += int(row.get(PS_CARRIES) or 0)

    rows: list[ShareRow] = []
    for entry in acc.values():
        tgt_pcts = entry["tgt_pcts"]
        rsh_pcts = entry["rsh_pcts"]
        rows.append(
            ShareRow(
                team=entry["team"],
                player_id=entry["player_id"],
                player=entry["player"],
                position=entry["position"],
                target_share_pct=_round1(sum(tgt_pcts) / len(tgt_pcts)) if tgt_pcts else None,
                targets=entry["targets"] if tgt_pcts else None,
                gp_tgt=len(tgt_pcts),
                rush_share_pct=_round1(sum(rsh_pcts) / len(rsh_pcts)) if rsh_pcts else None,
                carries=entry["carries"] if rsh_pcts else None,
                gp_rsh=len(rsh_pcts),
            )
        )

    rows.sort(key=lambda r: (r.team, r.player_id))
    return AllView(rows=tuple(rows), completed_weeks=completed_weeks)
