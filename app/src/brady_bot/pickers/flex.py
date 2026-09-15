from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.derive.adj_fpa import matchup_score
from brady_bot.derive.depth import blend_depth_score, depth_blend_label, posrank_score
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer, WeekContext
from brady_bot.pickers.base import Picker
from brady_bot.scoring.shared import (
    QB_CALIBRE_FALLBACK_FLAG,
    backup_qb_on_team,
    baseline_for_team,
    opponent_of,
    player_unavailable,
    pos_rank_of,
    qb_calibre_of,
    role_player_on_team,
    team_of,
)

# lineup-picker-FLEX.md / tech §8.7 — never RB/WR/TE Start Score factors
FLEX_FACTOR_NAMES = frozenset(
    {"opportunity", "matchup", "situation", "player_calibre", "baseline"}
)


class FlexPicker(Picker):
    """Cross-position FLEX slot. Recomputes Flex Score; ignores positional module scores."""

    position = Position.RB  # mixed pool; equation is FLEX-only
    slots = 1

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["flex"]
        self.mode = str(cfg.weights.global_cfg.get("matchup_normalization", "percentile"))
        self.pools = cfg.weights.flex_pool_sizes

    def select(self, ctx: WeekContext, candidates: list[Player]) -> tuple[list[ScoredPlayer], list[ScoredPlayer]]:
        # Candidates are bare Player objects — never carry RB/WR/TE start_score into ranking
        starters, rest = super().select(ctx, candidates)
        for scored in starters + rest:
            if scored.factors:
                names = {f.name for f in scored.factors}
                if not names <= FLEX_FACTOR_NAMES:
                    raise RuntimeError(
                        f"FLEX scored with non-FLEX factors: {names - FLEX_FACTOR_NAMES}"
                    )
        return starters, rest

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        """Flex Score per lineup-picker-FLEX.md (not RB/WR/TE equations)."""
        opp_factor, opp_raw = self._opportunity_factor(ctx, player)
        opp = opponent_of(ctx, player.team)
        pos = player.position.value
        mu = matchup_score(ctx.adj_fpa.get(pos, {}), opp or "", self.mode) if opp else 0.5
        situ, situ_raw = self._situation(ctx, player)
        cal = self._calibre(ctx, player)
        base = baseline_for_team(ctx, player.team)
        return [
            FactorScore(
                name="opportunity",
                raw_value=opp_raw,
                score=opp_factor,
                weight=self.w["opportunity"],
            ),
            FactorScore(name="matchup", score=mu, weight=self.w["matchup"]),
            FactorScore(
                name="situation", raw_value=situ_raw, score=situ, weight=self.w["situation"]
            ),
            FactorScore(name="player_calibre", score=cal, weight=self.w["player_calibre"]),
            FactorScore(name="baseline", score=base, weight=self.w["baseline"]),
        ]

    def _opportunity_factor(
        self, ctx: WeekContext, player: Player
    ) -> tuple[float, str | None]:
        """Step 2, 40% — cross-position ``pos_rank`` early, usage table from Week 5.

        The heaviest single factor anywhere in the system, so in Week 1 the FLEX pick is
        driven almost entirely by depth chart position: a WR2 (0.60) beats an RB2 (0.30)
        before anything else is considered.

        TE is included. ``pos_rank`` scores TE1 a flat 1.00 while the usage table splits
        TE1 into 1.00 (injured WRs) and 0.70 (healthy WRs) — the two tables differ on
        purpose, because WR health is a live condition a preseason depth chart cannot
        express. It only enters once the usage component carries weight.
        """
        pos = player.position.value
        rank = pos_rank_of(ctx, player)
        posrank = posrank_score(rank, pos)
        roles_usage = ctx.roles_current or ctx.roles
        usage = self._opportunity(ctx, player, roles_usage, ctx.snap_share)
        usage_label = self._opportunity_label(ctx, player, roles_usage, ctx.snap_share)
        label = depth_blend_label(
            ctx.week,
            pos_rank=rank,
            position=pos,
            posrank=posrank,
            usage_label=usage_label,
            usage=usage,
        )
        return blend_depth_score(ctx.week, posrank, usage), label

    def _opportunity_label(
        self,
        ctx: WeekContext,
        player: Player,
        roles: dict[str, str],
        shares: dict[str, float],
    ) -> str:
        if player.position == Position.RB:
            share = shares.get(player.player_id)
            return f"snap={share:.0%}" if share is not None else "inactive"
        if player.position == Position.WR:
            return roles.get(player.player_id, "WR4+")
        return roles.get(player.player_id, "TE2")

    def _opportunity(
        self,
        ctx: WeekContext,
        player: Player,
        roles: dict[str, str],
        shares: dict[str, float],
    ) -> float:
        """Week 5+ usage table, unchanged from lineup-picker-FLEX.md Step 2.

        No depth-chart fallback for RB: routing an unlisted back through his ``pos_rank``
        here would leak depth position past Week 4 (non-negotiable #8c).
        """
        if player.position == Position.RB:
            share = shares.get(player.player_id)
            if share is None:
                return 0.0
            if share >= 0.60:
                return 1.0
            if share >= 0.50:
                return 0.80
            if share >= 0.30:
                return 0.40
            return 0.10
        if player.position == Position.WR:
            role = roles.get(player.player_id, "WR4+")
            return {"WR1": 1.0, "WR2": 0.65, "WR3": 0.30}.get(role, 0.0)
        if roles.get(player.player_id) != "TE1":
            return 0.30
        team = player.team.upper()
        wr_out = any(
            (pid := role_player_on_team(ctx, team, role)) and player_unavailable(ctx, pid)
            for role in ("WR1", "WR2")
        )
        return 1.0 if wr_out else 0.70

    def _situation(self, ctx: WeekContext, player: Player) -> tuple[float, str | None]:
        """Step 4, 15% — O-line health for RBs, QB quality for WR/TE candidates."""
        team = player.team.upper()
        if player.position == Position.RB:
            # QB health never applies to RBs: a backup still hands off on first and second
            # down, and may lean on the run game more, not less.
            ol = ctx.injury_counts.get(player.team, {}).get("OL", 0)
            score = 1.0 if ol == 0 else (0.75 if ol == 1 else 0.50)
            other_out = 0
            for pid, role in ctx.roles.items():
                if not str(role).startswith("RB") or pid == player.player_id:
                    continue
                if team_of(ctx, pid) == team and player_unavailable(ctx, pid):
                    other_out += 1
            if other_out >= 2:
                score = min(1.0, score + 0.25)
            return score, None

        # Same S12 rank WR/TE Step 5 and DEF Step 2 read, through FLEX's own table (D21).
        qb1 = ctx.qb1_by_team.get(team)
        raw: str | None = None
        if qb1 and player_unavailable(ctx, qb1):
            backup = backup_qb_on_team(ctx, team, qb1)
            rank, fallback = qb_calibre_of(ctx, backup)
            backup_rank = 30 if rank is None else rank
            score = 0.50 if backup_rank <= 20 else 0.25
            raw = f"QB1 out, backup calibre rank {backup_rank}"
        elif qb1 and qb1 in ctx.injuries and ctx.injuries[qb1].report_status == "Questionable":
            score = 0.75
            _, fallback = qb_calibre_of(ctx, qb1)
            raw = "QB1 questionable but playing"
        else:
            score = 1.0
            rank, fallback = qb_calibre_of(ctx, qb1)
            if qb1:
                raw = f"QB1 active, calibre rank {'unranked' if rank is None else rank}"
        if fallback:
            raw = f"{raw}; {QB_CALIBRE_FALLBACK_FLAG}" if raw else QB_CALIBRE_FALLBACK_FLAG

        pc_out = 0
        for role in ("WR1", "WR2", "WR3", "TE1"):
            pid = role_player_on_team(ctx, team, role)
            if pid and pid != player.player_id and player_unavailable(ctx, pid):
                pc_out += 1
        if pc_out >= 2:
            score = min(1.0, score + 0.25)
            raw = f"{raw}; {pc_out} pass-catchers out" if raw else f"{pc_out} pass-catchers out"
        return score, raw

    def _calibre(self, ctx: WeekContext, player: Player) -> float:
        pos = player.position.value
        pool = self.pools.get(pos, 40)
        rank = ctx.calibre_rank.get(pos, {}).get(player.player_id, pool)
        pct = 1.0 - (rank - 1) / pool
        if pct > 0.95:
            return 1.0
        if pct >= 0.90:
            return 0.90
        if pct >= 0.75:
            return 0.75
        if pct >= 0.50:
            return 0.50
        if pct >= 0.25:
            return 0.25
        if pct >= 0.10:
            return 0.10
        return 0.0
