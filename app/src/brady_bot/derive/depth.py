"""Depth chart position scoring — tech spec §5.9a / §5.10.1, lineup-picker-DEPTH-CHART.md.

``pos_rank`` is the **early-season scoring anchor** for RB Step 3 (30%), WR Step 3
(20%) and FLEX Step 2 (40%). It fades 100% → 0% across Weeks 1–4; from Week 5 real
usage carries the factor alone and depth position contributes nothing to any score
(pipeline non-negotiable #8c).

Ranks are converted to cardinal scores on [0.0, 1.0] **before** any arithmetic, which
is why blending them does not violate non-negotiable #5 (D17). The forbidden operation
is averaging the raw ordinals — the midpoint of rank 1 and rank 3 is not "rank 2's
worth of value" — and that never happens here.
"""
from __future__ import annotations

import polars as pl

from brady_bot.derive.blending import blend_weights, is_blended_week
from brady_bot.derive.injuries import pin_depth_to_latest_week
from brady_bot.sources.schema import (
    DEPTH_GSIS_ID,
    DEPTH_POS_ABB,
    DEPTH_POS_RANK,
    PS_PLAYER_ID,
)

# §5.9a. RB1→RB2 drops 0.70 — the steepest fall in the system, because the RB1/RB2
# gap is a cliff, not a slope. WR falls off gently: three-receiver sets give WR2 and
# WR3 recurring roles. TE is effectively binary, matching the TE picker's gate.
POSRANK_SCORES: dict[str, dict[int, float]] = {
    "RB": {1: 1.00, 2: 0.30},
    "WR": {1: 1.00, 2: 0.60, 3: 0.25},
    "TE": {1: 1.00},
}

# Scored positions only. QB keeps a binary `pos_rank == 1` gate and K / D-ST have no
# depth factor; `pos_rank` is still read for them to identify starters for gates and
# injury unit counts, but never scored.
SCORED_POSITIONS: frozenset[str] = frozenset(POSRANK_SCORES)

# Identity lookups for gates (QB/TE) and depth scoring. Special-teams slots (KR/PR)
# are intentionally excluded — a flat last-row-wins map lets KR3 overwrite RB1.
GATE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})

# pos_abb values that roll up to each position group. FB shares the RB room.
_POS_GROUPS: dict[str, tuple[str, ...]] = {
    "QB": ("QB",),
    "RB": ("RB", "FB"),
    "WR": ("WR",),
    "TE": ("TE",),
}

NO_DEPTH_ENTRY = "no_depth_entry"


def posrank_score(pos_rank: int | None, position: str) -> float:
    """Depth chart rank → cardinal score on [0.0, 1.0] (§5.9a).

    Applies to RB, WR and TE only; any other position returns 0.00 because it has no
    depth-based factor. ``None`` means the player is absent from the depth chart and
    scores 0.00 — callers surface that as ``no_depth_entry`` so absence stays
    distinguishable from a real demotion, which may be a data gap instead.

    Ranks below the table floor (RB3+, WR4+, TE2+) score 0.00, never an interpolation:
    once a player is outside the meaningful rotation, depth position carries no
    positive signal (D20).
    """
    table = POSRANK_SCORES.get(position.upper())
    if table is None or pos_rank is None:
        return 0.0
    return table.get(int(pos_rank), 0.0)


def posrank_weights(week: int) -> tuple[float, float]:
    """``(w_posrank, w_usage)`` — 100/0 in Week 1 through 0/100 from Week 5 (§5.10.1).

    Identical schedule to the standard early-season blend: ``pos_rank`` occupies the
    slot prior-season usage used to hold.
    """
    return blend_weights(week)


def posrank_active(week: int) -> bool:
    """True while ``pos_rank`` still carries scoring weight (Weeks 1–4)."""
    return is_blended_week(week)


def blend_depth_score(week: int, posrank: float, usage: float) -> float:
    """``(w_posrank × posrank) + (w_usage × usage)``. Both terms are [0,1] scores."""
    w_posrank, w_usage = posrank_weights(week)
    return (w_posrank * posrank) + (w_usage * usage)


def posrank_label(pos_rank: int | None, position: str) -> str:
    """Breakdown token for the CLI: ``RB1``, ``WR3``, or ``no_depth_entry``."""
    if pos_rank is None:
        return NO_DEPTH_ENTRY
    return f"{position.upper()}{int(pos_rank)}"


def depth_blend_label(
    week: int,
    *,
    pos_rank: int | None,
    position: str,
    posrank: float,
    usage_label: str,
    usage: float,
) -> str:
    """Spell out both components so a 20–40% factor is never a bare number."""
    w_posrank, w_usage = posrank_weights(week)
    depth = posrank_label(pos_rank, position)
    if w_usage <= 0:
        return f"{depth} {posrank:.2f} (wk{week})"
    if w_posrank <= 0:
        return usage_label
    return (
        f"{depth} {posrank:.2f}@{w_posrank:.0%} + "
        f"{usage_label} {usage:.2f}@{w_usage:.0%}"
    )


def _derive_ranks_by_position(
    depth_charts: pl.DataFrame,
    week: int,
    positions: frozenset[str],
    *,
    overrides: dict[str, tuple[str, int]] | None = None,
) -> dict[str, dict[str, int]]:
    """Pinned ``pos_rank`` maps for the requested position groups.

    Special-teams slots (KR/PR) and OL/DB abbreviations outside ``positions`` are
    skipped, so a KR3 row cannot overwrite an RB1 — the flat last-row-wins failure.
    Within a group the best (lowest) rank wins.
    """
    out: dict[str, dict[str, int]] = {pos: {} for pos in positions}
    groups = {pos: abbs for pos, abbs in _POS_GROUPS.items() if pos in positions}

    pinned = pin_depth_to_latest_week(depth_charts, max(week, 1))
    if not pinned.is_empty():
        id_col = DEPTH_GSIS_ID if DEPTH_GSIS_ID in pinned.columns else PS_PLAYER_ID
        rank_col = DEPTH_POS_RANK if DEPTH_POS_RANK in pinned.columns else (
            "depth_chart_order" if "depth_chart_order" in pinned.columns else None
        )
        if id_col in pinned.columns and rank_col and DEPTH_POS_ABB in pinned.columns:
            group_of = {abb: pos for pos, abbs in groups.items() for abb in abbs}
            for r in pinned.select([id_col, DEPTH_POS_ABB, rank_col]).to_dicts():
                pid, abb, rank = r.get(id_col), r.get(DEPTH_POS_ABB), r.get(rank_col)
                if pid is None or abb is None or rank is None:
                    continue
                pos = group_of.get(str(abb).upper())
                if pos is None:
                    continue
                pid = str(pid)
                rank = int(rank)
                prev = out[pos].get(pid)
                if prev is None or rank < prev:
                    out[pos][pid] = rank

    for pid, (pos, rank) in (overrides or {}).items():
        pos = pos.upper()
        if pos in out:
            out[pos][pid] = int(rank)
    return out


def derive_pos_ranks(
    depth_charts: pl.DataFrame,
    week: int,
    *,
    overrides: dict[str, tuple[str, int]] | None = None,
    aliases: dict[str, str] | None = None,
) -> dict[str, dict[str, int]]:
    """Pinned ``pos_rank`` per scored position: ``{position: {gsis_id: rank}}``.

    **Pinning is mandatory** (non-negotiable #8b). ``load_depth_charts()`` has no
    ``week`` column, only a ``dt`` timestamp, so every read filters to each team's max
    ``dt`` first — an unpinned read silently resolves a rank from weeks earlier.

    Ranks are grouped by position so a player charted at two slots cannot contaminate
    the other's lookup; within a group the best (lowest) rank wins.

    S11 ``depth_overrides`` are applied last and always win, including for a player the
    published chart omits entirely.
    """
    _ = aliases
    return _derive_ranks_by_position(
        depth_charts, week, SCORED_POSITIONS, overrides=overrides
    )


def derive_depth_chart_order(
    depth_charts: pl.DataFrame,
    week: int,
) -> dict[str, dict[str, int]]:
    """Pinned depth order for gate identity: ``{QB|RB|WR|TE: {gsis_id: rank}}``.

    Same position scoping as ``derive_pos_ranks``, plus QB for the binary gate.
    KR/PR and other non-gate slots are excluded so they cannot overwrite a starter's
    rank the way a flat last-row-wins ``{gsis_id: rank}`` map did.
    """
    return _derive_ranks_by_position(depth_charts, week, GATE_POSITIONS)