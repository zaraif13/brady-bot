"""Other Starter Injuries — O/D starter counts for OL / DL / LBs / DBs.

Used by the True Depth Chart right rail. This is intentionally narrower than
lineup scoring's `count_all_units` / `is_unavailable`: only report_status Out
or Doubtful, only the exact pos_abb sets below, and only `pos_rank == 1`.
"""
from __future__ import annotations

import polars as pl

from brady_bot.derive.injuries import normalize_report_status, pin_depth_to_latest_week
from brady_bot.normalizer import normalize_team
from brady_bot.sources.schema import (
    DEPTH_GSIS_ID,
    DEPTH_POS_ABB,
    DEPTH_POS_RANK,
    DEPTH_STARTER_RANK,
    DEPTH_TEAM,
    INJ_GSIS_ID,
    INJ_REPORT_STATUS,
    INJ_WEEK,
)

# Exact sets from the Simplified Depth Chart plan — do not widen to lineup units.
OTHER_STARTER_UNITS: dict[str, frozenset[str]] = {
    "OL": frozenset({"LT", "LG", "C", "RG", "RT"}),
    "DL": frozenset({"LDE", "LDT", "RDT", "RDE", "NT"}),
    "LBs": frozenset({"WLB", "MLB", "SLB", "LILB", "RILB"}),
    "DBs": frozenset({"LCB", "RCB", "NB", "SS", "FS"}),
}

UNIT_ORDER = ("OL", "DL", "LBs", "DBs")
COUNTING_STATUSES = frozenset({"Out", "Doubtful"})


def _injury_week_frame(injuries: pl.DataFrame, week: int) -> pl.DataFrame:
    """Focus week if present; else latest available week ≤ focus."""
    if injuries.is_empty() or INJ_WEEK not in injuries.columns:
        return injuries
    weeks = [int(w) for w in injuries[INJ_WEEK].to_list() if w is not None]
    if not weeks:
        return injuries
    eligible = [w for w in weeks if w <= week]
    target = max(eligible) if eligible else max(weeks)
    return injuries.filter(pl.col(INJ_WEEK) == target)


def _out_or_doubtful_ids(injuries: pl.DataFrame, week: int) -> set[str]:
    df = _injury_week_frame(injuries, week)
    if df.is_empty() or INJ_REPORT_STATUS not in df.columns:
        return set()
    id_col = INJ_GSIS_ID if INJ_GSIS_ID in df.columns else "player_id"
    if id_col not in df.columns:
        return set()
    out: set[str] = set()
    for row in df.select([id_col, INJ_REPORT_STATUS]).to_dicts():
        pid = str(row.get(id_col) or "")
        if not pid:
            continue
        if normalize_report_status(row.get(INJ_REPORT_STATUS)) in COUNTING_STATUSES:
            out.add(pid)
    return out


def count_other_starter_injuries(
    depth_charts: pl.DataFrame,
    injuries: pl.DataFrame,
    team: str,
    *,
    week: int = 1,
    team_aliases: dict[str, str] | None = None,
) -> dict[str, int]:
    """Return {OL, DL, LBs, DBs} counts of injured starters for one team."""
    aliases = team_aliases or {}
    team = normalize_team(team, aliases)
    zeros = {label: 0 for label in UNIT_ORDER}
    if depth_charts.is_empty():
        return zeros

    pinned = pin_depth_to_latest_week(depth_charts, week)
    if pinned.is_empty() or DEPTH_TEAM not in pinned.columns:
        return zeros

    team_rows = [
        r
        for r in pinned.to_dicts()
        if normalize_team(str(r.get(DEPTH_TEAM) or ""), aliases) == team
    ]
    if not team_rows:
        return zeros

    injured = _out_or_doubtful_ids(injuries, week)
    if not injured:
        return zeros

    counts = {label: 0 for label in UNIT_ORDER}
    seen_per_unit: dict[str, set[str]] = {label: set() for label in UNIT_ORDER}

    for row in team_rows:
        pos_abb = str(row.get(DEPTH_POS_ABB) or "").strip()
        try:
            rank = int(row.get(DEPTH_POS_RANK))
        except (TypeError, ValueError):
            continue
        if rank != DEPTH_STARTER_RANK:
            continue
        pid = str(row.get(DEPTH_GSIS_ID) or "")
        if not pid or pid not in injured:
            continue
        for label, abbs in OTHER_STARTER_UNITS.items():
            if pos_abb in abbs and pid not in seen_per_unit[label]:
                seen_per_unit[label].add(pid)
                counts[label] += 1
                break

    return counts
