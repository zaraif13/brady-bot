"""True Depth Chart — flat QB/RB/WR/TE columns + Other Starter Injuries.

Published skill columns come from depth_table; RB/WR/TE pecking order is
re-derived from season-to-date usage (opportunity_share). QB always mirrors
the published chart. The right-rail unit counts live alongside the columns in
the same payload.
"""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from brady_bot.derive.depth_table import (
    SKILL_COLUMNS,
    TRUE_DEPTH_POSITIONS,
    DepthPlayer,
    SkillColumns,
    apply_out_demotion,
    build_skill_columns,
)
from brady_bot.derive.opportunity_share import (
    AllView,
    ShareRow,
    WeekView,
    build_all_view,
    build_week_view,
    is_bellcow,
)
from brady_bot.derive.other_starter_injuries import count_other_starter_injuries

POOL_POSITION = {"WR": "WR", "TE": "TE", "RB": "RB"}

MOVEMENT_UP = "up"
MOVEMENT_DOWN = "down"
MOVEMENT_NONE = "none"

_NO_PUBLISHED_RANK = 1 << 30


def _opportunity_annotation(
    pos_abb: str,
    player: DepthPlayer | None,
    week_shares_by_id: dict[str, ShareRow],
) -> dict:
    """Latest-week % + bellcow for True-mode cells only."""
    if player is None or not player.gsis_id:
        return {"opportunity_pct": None, "bellcow": False}
    share = week_shares_by_id.get(player.gsis_id)
    if share is None:
        return {"opportunity_pct": None, "bellcow": False}
    # Pool metric must match the column; a pass-catching RB's target share
    # never annotates a WR cell.
    if share.position != POOL_POSITION.get(pos_abb):
        return {"opportunity_pct": None, "bellcow": False}
    if pos_abb == "RB":
        pct = share.rush_share_pct
        return {"opportunity_pct": pct, "bellcow": is_bellcow(pct)}
    return {"opportunity_pct": share.target_share_pct, "bellcow": False}


@dataclass(frozen=True)
class _Candidate:
    player: DepthPlayer
    share: float | None
    qty: int
    published_rank: int | None


def _metric(share: ShareRow | None, pool_position: str) -> tuple[float | None, int]:
    if share is None:
        return None, 0
    if pool_position == "RB":
        return share.rush_share_pct, share.carries or 0
    return share.target_share_pct, share.targets or 0


def _rank_pool(candidates: list[_Candidate]) -> list[DepthPlayer]:
    ranked = [c for c in candidates if c.share is not None]
    unranked = [c for c in candidates if c.share is None]
    ranked.sort(
        key=lambda c: (
            -(c.share or 0.0),
            -c.qty,
            c.published_rank if c.published_rank is not None else _NO_PUBLISHED_RANK,
        )
    )
    unranked.sort(
        key=lambda c: c.published_rank if c.published_rank is not None else _NO_PUBLISHED_RANK
    )
    return [c.player for c in ranked + unranked]


def _build_true_group(
    published: list[DepthPlayer],
    pool_position: str,
    shares_by_id: dict[str, ShareRow],
) -> list[DepthPlayer]:
    seen = {p.gsis_id for p in published if p.gsis_id}
    candidates: list[_Candidate] = []
    for index, player in enumerate(published):
        share = shares_by_id.get(player.gsis_id or "")
        if share is not None and share.position != pool_position:
            share = None
        value, qty = _metric(share, pool_position)
        candidates.append(
            _Candidate(player=player, share=value, qty=qty, published_rank=index + 1)
        )

    for share in shares_by_id.values():
        if share.position != pool_position or share.player_id in seen:
            continue
        value, qty = _metric(share, pool_position)
        if value is None:
            continue
        candidates.append(
            _Candidate(
                player=DepthPlayer(
                    player_name=share.player,
                    gsis_id=share.player_id,
                    injury_mark=None,
                    published_flat_rank=0,
                ),
                share=value,
                qty=qty,
                published_rank=None,
            )
        )

    return apply_out_demotion(_rank_pool(candidates))


def _cell_payload(player: DepthPlayer | None) -> dict:
    if player is None:
        return {"player_name": None, "injury_mark": None}
    return {"player_name": player.player_name, "injury_mark": player.injury_mark}


def _movements_by_id(
    true_order: list[DepthPlayer], published_ranks: dict[str, int]
) -> dict[str, str]:
    out: dict[str, str] = {}
    for index, player in enumerate(true_order):
        pid = player.gsis_id
        if not pid:
            continue
        published_rank = published_ranks.get(pid)
        if published_rank is None:
            out[pid] = MOVEMENT_NONE
        elif index + 1 < published_rank:
            out[pid] = MOVEMENT_UP
        elif index + 1 > published_rank:
            out[pid] = MOVEMENT_DOWN
        else:
            out[pid] = MOVEMENT_NONE
    return out


def _column_entries(
    pos_abb: str,
    published: tuple[DepthPlayer, ...],
    shares_by_id: dict[str, ShareRow],
    week_shares_by_id: dict[str, ShareRow],
    has_usage: bool,
) -> list[dict]:
    eligible = pos_abb in TRUE_DEPTH_POSITIONS
    published_list = list(published)
    published_ranks = {
        p.gsis_id: i + 1 for i, p in enumerate(published_list) if p.gsis_id
    }

    true_order: list[DepthPlayer] | None = None
    movements: dict[str, str] = {}
    if eligible and has_usage:
        true_order = _build_true_group(
            published_list, POOL_POSITION[pos_abb], shares_by_id
        )
        movements = _movements_by_id(true_order, published_ranks)

    # Overflow: usage the published chart missed can lengthen the True column.
    length = len(published_list)
    if true_order is not None:
        length = max(length, len(true_order))

    entries: list[dict] = []
    for index in range(length):
        published_cell = published_list[index] if index < len(published_list) else None
        entry: dict = {
            "pos_rank": index + 1,
            "published": _cell_payload(published_cell),
        }
        if eligible:
            if true_order is None:
                true_cell = published_cell
            elif index < len(true_order):
                true_cell = true_order[index]
            else:
                true_cell = None
            movement = MOVEMENT_NONE
            if true_cell is not None and true_cell.gsis_id:
                movement = movements.get(true_cell.gsis_id, MOVEMENT_NONE)
            entry["true"] = {
                **_cell_payload(true_cell),
                "movement": movement,
                **_opportunity_annotation(pos_abb, true_cell, week_shares_by_id),
            }
        entries.append(entry)
    return entries


def build_payload(
    skill: SkillColumns,
    all_view: AllView,
    week_view: WeekView | None,
    *,
    week: int,
    other_starter_injuries: dict[str, int],
) -> dict:
    shares_by_id = {r.player_id: r for r in all_view.by_team(skill.team)}
    has_usage = bool(shares_by_id)
    opportunity_week = week_view.week if week_view and not week_view.is_empty() else None
    if opportunity_week is None and all_view.completed_weeks:
        opportunity_week = max(all_view.completed_weeks)
    week_shares_by_id = (
        {r.player_id: r for r in week_view.by_team(skill.team)}
        if week_view is not None
        else {}
    )
    columns = {
        pos: _column_entries(
            pos,
            skill.columns.get(pos, ()),
            shares_by_id,
            week_shares_by_id,
            has_usage,
        )
        for pos in SKILL_COLUMNS
    }
    return {
        "team": skill.team,
        "week": week,
        "has_usage_data": has_usage,
        "completed_weeks": list(all_view.completed_weeks),
        "opportunity_week": opportunity_week,
        "columns": columns,
        "other_starter_injuries": other_starter_injuries,
    }


def build_team_payload(
    depth_charts: pl.DataFrame,
    injuries: pl.DataFrame,
    player_stats: pl.DataFrame,
    team: str,
    *,
    week: int = 1,
    team_aliases: dict[str, str] | None = None,
) -> dict:
    skill = build_skill_columns(
        depth_charts, injuries, team, week=week, team_aliases=team_aliases
    )
    all_view = build_all_view(player_stats, team_aliases=team_aliases)
    week_view = None
    if all_view.completed_weeks:
        latest = max(all_view.completed_weeks)
        week_view = build_week_view(player_stats, latest, team_aliases=team_aliases)
    other = count_other_starter_injuries(
        depth_charts, injuries, skill.team, week=week, team_aliases=team_aliases
    )
    return build_payload(
        skill,
        all_view,
        week_view,
        week=week,
        other_starter_injuries=other,
    )
