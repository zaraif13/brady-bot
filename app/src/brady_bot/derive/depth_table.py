"""Skill-position depth columns for the True Depth Chart page.

Produces flat pecking-order lists for QB / RB / WR / TE only (one column each),
with injury marks and `O` demotion applied within each position. The old ESPN
multi-row Offense/Defense/Special Teams grid is not used on this page.

Published `pos_rank` is already a flat rank within each `pos_abb` group (WR1–WR6
across multiple ESPN rows still share one WR column here).
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from brady_bot.derive.injuries import normalize_report_status, pin_depth_to_latest_week
from brady_bot.normalizer import normalize_team
from brady_bot.sources.schema import (
    DEPTH_GSIS_ID,
    DEPTH_PLAYER_NAME,
    DEPTH_POS_ABB,
    DEPTH_POS_RANK,
    DEPTH_TEAM,
    INJ_GSIS_ID,
    INJ_REPORT_STATUS,
    INJ_WEEK,
)

# Display column order on the True Depth Chart page.
SKILL_COLUMNS = ("QB", "RB", "WR", "TE")
SKILL_POSITIONS = frozenset(SKILL_COLUMNS)

# Re-ranked by usage in True Depth Chart mode; QB always mirrors published.
TRUE_DEPTH_POSITIONS = frozenset({"WR", "TE", "RB"})

# Only these three ever render. "Probable" is suppressed — treated as healthy.
MARK_BY_STATUS = {"Out": "O", "Doubtful": "D", "Questionable": "Q"}
DEMOTING_MARKS = frozenset({"O"})


@dataclass(frozen=True)
class DepthPlayer:
    player_name: str
    gsis_id: str | None
    injury_mark: str | None
    published_flat_rank: int


@dataclass(frozen=True)
class SkillColumns:
    """One team's QB/RB/WR/TE published columns, post O-demotion."""

    team: str
    columns: dict[str, tuple[DepthPlayer, ...]]

    def is_empty(self) -> bool:
        return not any(self.columns.get(pos) for pos in SKILL_COLUMNS)


def injury_marks_by_player(
    injuries: pl.DataFrame,
    *,
    week: int | None = None,
) -> dict[str, str]:
    """gsis_id -> O/D/Q from the focus week, else latest week ≤ focus (or max)."""
    if injuries.is_empty() or INJ_REPORT_STATUS not in injuries.columns:
        return {}
    df = injuries
    if INJ_WEEK in df.columns:
        weeks = [int(w) for w in df[INJ_WEEK].to_list() if w is not None]
        if weeks:
            if week is not None:
                eligible = [w for w in weeks if w <= week]
                target = max(eligible) if eligible else max(weeks)
            else:
                target = max(weeks)
            df = df.filter(pl.col(INJ_WEEK) == target)
    id_col = INJ_GSIS_ID if INJ_GSIS_ID in df.columns else "player_id"
    if id_col not in df.columns:
        return {}

    out: dict[str, str] = {}
    for row in df.select([id_col, INJ_REPORT_STATUS]).to_dicts():
        pid = str(row.get(id_col) or "")
        if not pid:
            continue
        mark = MARK_BY_STATUS.get(normalize_report_status(row.get(INJ_REPORT_STATUS)) or "")
        if mark:
            out[pid] = mark
    return out


def apply_out_demotion(players: list[DepthPlayer]) -> list[DepthPlayer]:
    """Move `O` players to the bottom; everyone below them shifts up one slot."""
    healthy = [p for p in players if p.injury_mark not in DEMOTING_MARKS]
    demoted = [p for p in players if p.injury_mark in DEMOTING_MARKS]
    return healthy + demoted


def _team_rows(depth_charts: pl.DataFrame, team: str, aliases: dict[str, str]) -> list[dict]:
    if depth_charts.is_empty():
        return []
    cols = depth_charts.columns
    required = {DEPTH_TEAM, DEPTH_POS_ABB, DEPTH_POS_RANK}
    if not required.issubset(cols):
        return []
    return [
        r
        for r in depth_charts.to_dicts()
        if normalize_team(str(r.get(DEPTH_TEAM) or ""), aliases) == team
    ]


def build_skill_columns(
    depth_charts: pl.DataFrame,
    injuries: pl.DataFrame,
    team: str,
    *,
    week: int = 1,
    team_aliases: dict[str, str] | None = None,
    pinned: bool = False,
) -> SkillColumns:
    """Flat QB/RB/WR/TE lists for one team, injury-marked and O-demoted."""
    aliases = team_aliases or {}
    team = normalize_team(team, aliases)
    empty = {pos: () for pos in SKILL_COLUMNS}
    if depth_charts.is_empty():
        return SkillColumns(team=team, columns=empty)

    pinned_df = depth_charts if pinned else pin_depth_to_latest_week(depth_charts, week)
    rows = _team_rows(pinned_df, team, aliases)
    if not rows:
        return SkillColumns(team=team, columns=empty)

    marks = injury_marks_by_player(injuries, week=week)

    by_pos: dict[str, list[dict]] = {pos: [] for pos in SKILL_COLUMNS}
    for row in rows:
        pos_abb = str(row.get(DEPTH_POS_ABB) or "").strip()
        if pos_abb not in SKILL_POSITIONS:
            continue
        by_pos[pos_abb].append(row)

    columns: dict[str, tuple[DepthPlayer, ...]] = {}
    for pos in SKILL_COLUMNS:
        ordered = sorted(by_pos[pos], key=lambda r: int(r[DEPTH_POS_RANK]))
        players = [
            DepthPlayer(
                player_name=str(r.get(DEPTH_PLAYER_NAME) or "").strip(),
                gsis_id=str(r[DEPTH_GSIS_ID]) if r.get(DEPTH_GSIS_ID) else None,
                injury_mark=marks.get(str(r.get(DEPTH_GSIS_ID) or "")),
                published_flat_rank=int(r[DEPTH_POS_RANK]),
            )
            for r in ordered
            if str(r.get(DEPTH_PLAYER_NAME) or "").strip()
        ]
        columns[pos] = tuple(apply_out_demotion(players))

    return SkillColumns(team=team, columns=columns)
