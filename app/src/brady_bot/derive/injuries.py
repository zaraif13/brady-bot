from __future__ import annotations

from typing import Literal, Optional

import polars as pl

from brady_bot.models import InjuryRecord
from brady_bot.sources.schema import (
    DEPTH_GSIS_ID,
    DEPTH_POS_ABB,
    DEPTH_POS_RANK,
    DEPTH_STARTER_RANK,
    DEPTH_TEAM,
    INJ_GSIS_ID,
    INJ_PRACTICE_STATUS,
    INJ_REPORT_STATUS,
    INJ_WEEK,
    UNIT_POS_ABB,
)

# Unit membership from Step 0 confirmed pos_abb values (schema.UNIT_POS_ABB)
OL_POS = set(UNIT_POS_ABB["OL"])
SECONDARY = set(UNIT_POS_ABB["SECONDARY"])
FRONT_SEVEN = set(UNIT_POS_ABB["FRONT_SEVEN"])
FRONT_SEVEN_INTERIOR = set(UNIT_POS_ABB["FRONT_SEVEN_INTERIOR"])

ReportStatus = Literal["Out", "Doubtful", "Questionable", "Probable", "IR", "PUP", "NFI"]
PracticeStatus = Literal["DNP", "Limited", "Full"]


def normalize_report_status(raw: Optional[str]) -> Optional[ReportStatus]:
    """Map nflverse / depth-chart injury labels per injury_status.md."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    # Exact / abbreviation first
    exact = {
        "o": "Out",
        "out": "Out",
        "d": "Doubtful",
        "doubtful": "Doubtful",
        "q": "Questionable",
        "questionable": "Questionable",
        "p": "Probable",
        "probable": "Probable",
        "ir": "IR",
        "injured reserve": "IR",
        "pup": "PUP",
        "physically unable to perform": "PUP",
        "nfi": "NFI",
        "non-football injury": "NFI",
        "non football injury": "NFI",
    }
    if low in exact:
        return exact[low]  # type: ignore[return-value]
    # Substring / verbose nflverse forms
    if "injured reserve" in low or low.endswith("/ir") or "/ir" in low:
        return "IR"
    if "physically unable" in low or "pup" in low:
        return "PUP"
    if "non-football" in low or "non football" in low or "nfi" in low:
        return "NFI"
    if "doubt" in low:
        return "Doubtful"
    if "question" in low:
        return "Questionable"
    if "probable" in low:
        return "Probable"
    if low == "out" or low.startswith("out ") or " out" in f" {low}":
        return "Out"
    if "out" in low and "doubt" not in low and "without" not in low:
        return "Out"
    return None


def normalize_practice_status(raw: Optional[str]) -> Optional[PracticeStatus]:
    """Map nflverse practice participation strings to DNP / Limited / Full."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    if low in ("dnp", "limited", "full"):
        return low.upper() if low == "dnp" else low.capitalize()  # type: ignore[return-value]
    if "did not participate" in low or low == "dnp" or "dnp" in low:
        return "DNP"
    if "limited" in low:
        return "Limited"
    if "full" in low:
        return "Full"
    return None


def is_unavailable(report_status: Optional[str], practice_status: Optional[str]) -> bool:
    rs = normalize_report_status(report_status)
    ps = normalize_practice_status(practice_status)
    # Unknown Questionable practice string → conservative unavailable (tech spec)
    if rs == "Questionable" and practice_status is not None and ps is None:
        return True
    rec = InjuryRecord(player_id="x", report_status=rs, practice_status=ps)
    return rec.is_unavailable


def build_injury_map(injuries: pl.DataFrame, week: int) -> dict[str, InjuryRecord]:
    if injuries.is_empty():
        return {}
    df = injuries
    if INJ_WEEK in df.columns:
        df = df.filter(pl.col(INJ_WEEK) == week)
    id_col = INJ_GSIS_ID if INJ_GSIS_ID in df.columns else ("player_id" if "player_id" in df.columns else None)
    if id_col is None:
        return {}
    out: dict[str, InjuryRecord] = {}
    for r in df.to_dicts():
        pid = str(r.get(id_col) or "")
        if not pid:
            continue
        rs_raw = r.get(INJ_REPORT_STATUS) or r.get("injury_status")
        ps_raw = r.get(INJ_PRACTICE_STATUS)
        rs = normalize_report_status(str(rs_raw) if rs_raw is not None else None)
        ps = normalize_practice_status(str(ps_raw) if ps_raw is not None else None)
        # Skip healthy / unmarked rows
        if rs is None and ps is None:
            continue
        out[pid] = InjuryRecord(player_id=pid, report_status=rs, practice_status=ps)
    return out


def pin_depth_to_latest_week(depth_charts: pl.DataFrame, week: int) -> pl.DataFrame:
    """Pin depth chart to the latest snapshot per team.

    Live nflreadpy depth charts have no ``week`` column — they carry a ``dt``
    timestamp. Prefer per-team max ``dt`` so a team whose feed lags the global
    max is not dropped. Legacy frames with ``week`` still pin to max week ≤ target.
    """
    if depth_charts.is_empty():
        return depth_charts
    if "week" in depth_charts.columns:
        dc = depth_charts.filter(pl.col("week") <= week)
        if dc.is_empty():
            return dc
        max_week = int(dc["week"].max())
        return dc.filter(pl.col("week") == max_week)
    if "dt" in depth_charts.columns and DEPTH_TEAM in depth_charts.columns:
        maxima = depth_charts.group_by(DEPTH_TEAM).agg(pl.col("dt").max().alias("_max_dt"))
        return (
            depth_charts.join(maxima, on=DEPTH_TEAM, how="inner")
            .filter(pl.col("dt") == pl.col("_max_dt"))
            .drop("_max_dt")
        )
    if "dt" in depth_charts.columns:
        max_dt = depth_charts["dt"].max()
        if max_dt is not None:
            return depth_charts.filter(pl.col("dt") == max_dt)
    return depth_charts


def derive_injury_counts(
    injuries: pl.DataFrame,
    depth_charts: pl.DataFrame,
    team: str,
    unit: str,
    week: int,
) -> int:
    positions = set(UNIT_POS_ABB.get(unit, frozenset()))
    dc = pin_depth_to_latest_week(depth_charts, week)
    if DEPTH_TEAM in dc.columns:
        dc = dc.filter(pl.col(DEPTH_TEAM).cast(pl.Utf8).str.to_uppercase() == team.upper())
    # Step 0: starters are pos_rank == 1 (not depth_chart_order)
    if DEPTH_POS_RANK in dc.columns:
        dc = dc.filter(pl.col(DEPTH_POS_RANK) == DEPTH_STARTER_RANK)
    elif "depth_chart_order" in or_cols(dc):
        dc = dc.filter(pl.col("depth_chart_order") == 1)
    pos_col = DEPTH_POS_ABB if DEPTH_POS_ABB in dc.columns else (
        "position" if "position" in dc.columns else ("pos" if "pos" in dc.columns else None)
    )
    if pos_col:
        dc = dc.filter(pl.col(pos_col).cast(pl.Utf8).str.to_uppercase().is_in(list(positions)))
    id_col = DEPTH_GSIS_ID if DEPTH_GSIS_ID in dc.columns else ("player_id" if "player_id" in dc.columns else None)
    if id_col is None:
        return 0
    # Unique starters — multi-week depth must not inflate counts
    starters = {str(x) for x in dc[id_col].to_list() if x}
    inj_map = build_injury_map(injuries, week)
    return sum(1 for pid in starters if pid in inj_map and inj_map[pid].is_unavailable)


def or_cols(df: pl.DataFrame) -> set[str]:
    return set(df.columns)


def count_all_units(
    injuries: pl.DataFrame,
    depth_charts: pl.DataFrame,
    teams: list[str],
    week: int,
) -> dict[str, dict[str, int]]:
    units = ["OL", "SECONDARY", "FRONT_SEVEN", "FRONT_SEVEN_INTERIOR", "DEFENSE_ALL"]
    out: dict[str, dict[str, int]] = {}
    for team in teams:
        out[team] = {
            u: derive_injury_counts(injuries, depth_charts, team, u, week) for u in units
        }
    return out
