from __future__ import annotations

from brady_bot.derive.qb_calibre import FALLBACK_FLAG as QB_CALIBRE_FALLBACK_FLAG
from brady_bot.models import InjuryRecord, Player, WeekContext

INJURY_ABBREV: dict[str, str] = {
    "Out": "O",
    "Doubtful": "D",
    "Questionable": "Q",
    "Probable": "P",
    "IR": "IR",
    "PUP": "PUP",
    "NFI": "NFI",
}


def rank_to_score(rank: int, denominator: int) -> float:
    return max(0.0, 1.0 - (rank - 1) / denominator)


def implied_total_score(total: float) -> float:
    if total >= 25:
        return 1.0
    if total >= 23:
        return 0.75
    if total >= 21:
        return 0.50
    if total >= 19:
        return 0.25
    return 0.0


def tiered_injury_penalty(missing: int) -> float:
    if missing <= 0:
        return 1.0
    if missing == 1:
        return 0.75
    if missing == 2:
        return 0.50
    return 0.25


def qb_calibre_tier(rank: int | None) -> float:
    if rank is None:
        return 0.0
    if rank <= 5:
        return 1.0
    if rank <= 12:
        return 0.75
    if rank <= 20:
        return 0.50
    if rank <= 28:
        return 0.25
    return 0.0


def team_of(ctx: WeekContext, player_id: str) -> str | None:
    t = ctx.player_teams.get(player_id)
    if t:
        return t.upper()
    for p in ctx.roster:
        if p.player_id == player_id:
            return p.team.upper()
    return None


def is_mobile_qb(
    ctx: WeekContext,
    player_id: str,
    threshold: float = 4.0,
) -> tuple[bool, bool]:
    """
    QB playing-style lookup: list first, rush-att fallback for unlisted only.
    Returns (mobile, style_derived).
    """
    if player_id in ctx.qb_styles:
        return bool(ctx.qb_styles[player_id]), False
    rush = ctx.rush_att_pg.get(player_id)
    if rush is not None:
        return rush >= threshold, True
    return False, False


def role_player_on_team(ctx: WeekContext, team: str, role: str) -> str | None:
    team = team.upper()
    for pid, r in ctx.roles.items():
        if r == role and team_of(ctx, pid) == team:
            return pid
    return None


def backup_qb_on_team(ctx: WeekContext, team: str, qb1: str | None) -> str | None:
    """Best available non-QB1 QB on team (QB2 then any QB*)."""
    team = team.upper()
    qb2 = role_player_on_team(ctx, team, "QB2")
    if qb2 and qb2 != qb1:
        return qb2
    for pid, role in ctx.roles.items():
        if role.startswith("QB") and role != "QB1" and team_of(ctx, pid) == team:
            if pid != qb1:
                return pid
    return None


def qb_calibre_of(ctx: WeekContext, player_id: str | None) -> tuple[int | None, bool]:
    """S12 calibre rank for a QB → (rank, derived_fallback).

    ``derived_fallback`` marks a QB absent from the static ranking whose rank came from
    ``derive_player_calibre`` instead (D21) — a deep-bench arm or a mid-season arrival.
    Warn-level information for the breakdown, never a halt.
    """
    if not player_id:
        return None, False
    rank = ctx.calibre_rank.get("QB", {}).get(player_id)
    return rank, player_id in ctx.qb_calibre_fallback


def qb_quality_inputs(ctx: WeekContext, team: str) -> tuple[str | None, int | None, bool, bool]:
    """Which QB §7.3 consulted for ``team`` → (qb_id, rank, capped, derived_fallback).

    Single source of the branch logic so the score and its breakdown label can never
    describe different quarterbacks.
    """
    team = team.upper()
    qb1 = ctx.qb1_by_team.get(team)
    if qb1 and player_unavailable(ctx, qb1):
        backup = backup_qb_on_team(ctx, team, qb1)
        rank, fallback = qb_calibre_of(ctx, backup)
        return backup, rank, True, fallback
    rank, fallback = qb_calibre_of(ctx, qb1)
    return qb1, rank, False, fallback


def qb_quality_score(ctx: WeekContext, team: str) -> float:
    """§7.3 — team-scoped QB1 / backup calibre. Rank source is S12 (D21)."""
    qb_id, rank, capped, _ = qb_quality_inputs(ctx, team)
    if capped:
        # Hard 0.50 cap whenever QB1 is out, however good the backup looks.
        return min(0.50, qb_calibre_tier(30 if rank is None else rank))
    if not qb_id:
        return 0.50
    return qb_calibre_tier(rank)


def qb_quality_label(ctx: WeekContext, team: str) -> str | None:
    """Breakdown label for §7.3, surfacing ``qb_calibre_derived_fallback`` when set."""
    qb_id, rank, capped, fallback = qb_quality_inputs(ctx, team)
    if not qb_id:
        return "no QB1 identified"
    parts = [f"{'backup' if capped else 'QB1'} calibre rank " + ("unranked" if rank is None else str(rank))]
    if capped:
        parts.append("QB1 out, capped 0.50")
    if fallback:
        parts.append(QB_CALIBRE_FALLBACK_FLAG)
    return "; ".join(parts)


def baseline_for_team(ctx: WeekContext, team: str) -> float:
    if ctx.odds_unavailable:
        return 0.50
    game = ctx.games.get(team.upper()) or ctx.games.get(team)
    if not game:
        return 0.50
    return implied_total_score(game.implied_total_for(team.upper()))


def opponent_of(ctx: WeekContext, team: str) -> str | None:
    game = ctx.games.get(team.upper())
    if not game:
        return None
    return game.opponent_of(team.upper())


def oline_quality_tier(rank: int) -> float:
    """RB O-line quality bands from S10 rank (1 = best). lineup-picker-OL.md."""
    if rank <= 5:
        return 1.0
    if rank <= 12:
        return 0.75
    if rank <= 20:
        return 0.50
    if rank <= 28:
        return 0.25
    return 0.0


def pos_rank_of(ctx: WeekContext, player: Player) -> int | None:
    """Pinned ``pos_rank`` at the player's own position, or None if unlisted (§5.9a)."""
    return ctx.pos_rank.get(player.position.value, {}).get(player.player_id)


def depth_order_of(
    ctx: WeekContext, player_id: str, position: str
) -> int | None:
    """Position-scoped depth order for gates. KR/PR never bleed into QB/RB/WR/TE."""
    return ctx.depth_chart_order.get(position.upper(), {}).get(player_id)


def snap_share_score(share: float) -> float:
    if share >= 0.60:
        return 1.0
    if share >= 0.50:
        return 0.80
    if share >= 0.30:
        return 0.20
    if share > 0:
        return 0.10
    return 0.0


def player_unavailable(ctx: WeekContext, player_id: str) -> bool:
    rec = ctx.injuries.get(player_id)
    return bool(rec and rec.is_unavailable)


def injury_abbrev(rec: InjuryRecord | None) -> str | None:
    if not rec or not rec.report_status:
        return None
    return INJURY_ABBREV.get(rec.report_status, rec.report_status)
