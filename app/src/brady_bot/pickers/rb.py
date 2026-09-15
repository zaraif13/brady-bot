from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.derive.adj_fpa import matchup_score
from brady_bot.derive.depth import blend_depth_score, depth_blend_label, posrank_score
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer, WeekContext
from brady_bot.pickers.base import Picker, apply_start_score_cap
from brady_bot.scoring.shared import (
    baseline_for_team,
    opponent_of,
    player_unavailable,
    pos_rank_of,
    rank_to_score,
    oline_quality_tier,
    snap_share_score,
    team_of,
    tiered_injury_penalty,
)


class RBPicker(Picker):
    position = Position.RB
    slots = 2

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["rb"]
        self.mode = str(cfg.weights.global_cfg.get("matchup_normalization", "percentile"))
        self.denom = cfg.weights.calibre_denominators.get("RB", 39)
        rb_raw = (cfg.weights.raw.get("rb") or {})
        self.tier2_bonus = float(rb_raw.get("tier2_bonus", 0.30))

    def auto_start(self, ctx: WeekContext, player: Player, pool: list[Player]) -> ScoredPlayer | None:
        tier1 = ctx.static_ids.get("rb_tier1", set())
        if player.player_id in tier1:
            return ScoredPlayer(
                player=player, start_score=1.0, gate_result="auto_start", gate_reason="rb_tier1"
            )
        return None

    def finalize_score(
        self, ctx: WeekContext, player: Player, weighted_sum: float
    ) -> tuple[float, float, list[str]]:
        bonus = (
            self.tier2_bonus
            if player.player_id in ctx.static_ids.get("rb_tier2", set())
            else 0.0
        )
        start, flags = apply_start_score_cap(weighted_sum, bonus)
        if bonus > 0:
            flags = ["tier2_bonus", *flags]
        return start, bonus, flags

    def _usage(self, ctx: WeekContext, player: Player) -> tuple[float, str]:
        """Week 5+ half of Step 3 — current-season snap share through the tier table.

        Deliberately has no depth-chart fallback. Routing an unlisted back through his
        ``pos_rank`` here would keep depth position influencing the factor after Week 4,
        which is exactly the leak non-negotiable #8c forbids. No snap rows means
        inactive, which the tier table scores 0.00.
        """
        share = ctx.snap_share.get(player.player_id)
        if share is None:
            return 0.0, "inactive"
        return snap_share_score(share), f"snap={share:.0%}"

    def _depth_chart(self, ctx: WeekContext, player: Player) -> tuple[float, str]:
        """Step 3, 30% — ``pos_rank`` early, snap share from Week 5 (§5.10.1, D19)."""
        rank = pos_rank_of(ctx, player)
        posrank = posrank_score(rank, "RB")
        usage, usage_label = self._usage(ctx, player)
        label = depth_blend_label(
            ctx.week,
            pos_rank=rank,
            position="RB",
            posrank=posrank,
            usage_label=usage_label,
            usage=usage,
        )
        return blend_depth_score(ctx.week, posrank, usage), label

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        depth, depth_raw = self._depth_chart(ctx, player)
        rank = ctx.calibre_rank.get("RB", {}).get(player.player_id, 40)
        ranking = rank_to_score(rank, self.denom)
        team = player.team.upper()
        ol_rank = ctx.oline_ranks.get(team)
        if ol_rank is None:
            ol_rank = ctx.oline_ranks.get(player.team, 16)
        ol_inj = ctx.injury_counts.get(player.team, {}).get("OL", 0)
        if not ol_inj and team != player.team:
            ol_inj = ctx.injury_counts.get(team, {}).get("OL", 0)
        mult = {0: 1.0, 1: 0.75, 2: 0.50}.get(ol_inj, 0.25)
        oline = oline_quality_tier(int(ol_rank)) * mult
        teammate = self._teammate(ctx, player)
        opp = opponent_of(ctx, player.team)
        mu = matchup_score(ctx.adj_fpa.get("RB", {}), opp or "", self.mode) if opp else 0.5
        front = tiered_injury_penalty(
            ctx.injury_counts.get(opp or "", {}).get("FRONT_SEVEN_INTERIOR", 0)
        ) if opp else 0.5
        base = baseline_for_team(ctx, player.team)
        factors = [
            FactorScore(name="depth_chart", raw_value=depth_raw, score=depth, weight=self.w["depth_chart"]),
            FactorScore(name="ranking", raw_value=f"rank={rank}", score=ranking, weight=self.w["ranking"]),
            FactorScore(
                name="oline",
                raw_value=f"rank={ol_rank};ol_out={ol_inj}",
                score=oline,
                weight=self.w["oline"],
            ),
            FactorScore(name="teammate_injury", score=teammate, weight=self.w["teammate_injury"]),
            FactorScore(name="matchup", score=mu, weight=self.w["matchup"]),
            FactorScore(name="front_seven_injury", score=front, weight=self.w["front_seven_injury"]),
            FactorScore(name="baseline", score=base, weight=self.w["baseline"]),
        ]
        return factors

    def _teammate(self, ctx: WeekContext, player: Player) -> float:
        """§8.2 — NFL-team backfield injuries via roles + player_teams."""
        role = ctx.roles.get(player.player_id, "RB2")
        team = player.team.upper()
        unavailable_roles: list[str] = []
        for pid, r in ctx.roles.items():
            if not str(r).startswith("RB") or pid == player.player_id:
                continue
            if team_of(ctx, pid) != team:
                continue
            if player_unavailable(ctx, pid):
                unavailable_roles.append(str(r))
        if role == "RB1" and "RB2" in unavailable_roles:
            return 0.75
        if role == "RB2" and "RB1" in unavailable_roles:
            return 1.0
        if role.startswith("RB") and len(unavailable_roles) >= 2:
            return 1.0
        return 0.50
