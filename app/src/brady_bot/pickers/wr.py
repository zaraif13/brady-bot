from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.derive.adj_fpa import matchup_score
from brady_bot.derive.depth import blend_depth_score, depth_blend_label, posrank_score
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer, WeekContext
from brady_bot.pickers.base import Picker
from brady_bot.scoring.shared import (
    baseline_for_team,
    opponent_of,
    player_unavailable,
    pos_rank_of,
    qb_quality_label,
    qb_quality_score,
    rank_to_score,
    role_player_on_team,
    team_of,
    tiered_injury_penalty,
)


class WRPicker(Picker):
    position = Position.WR
    slots = 2

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["wr"]
        self.mode = str(cfg.weights.global_cfg.get("matchup_normalization", "percentile"))
        self.denom = cfg.weights.calibre_denominators.get("WR", 59)

    def auto_start(self, ctx: WeekContext, player: Player, pool: list[Player]) -> ScoredPlayer | None:
        if player.player_id in ctx.static_ids.get("wr_top5", set()):
            return ScoredPlayer(
                player=player, start_score=1.0, gate_result="auto_start", gate_reason="wr_top5"
            )
        return None

    # Identical to the pos_rank table in §5.9a — same measure, two sources. Published
    # depth order carries it early, realized target order from Week 5, so the blend
    # needs no scale conversion.
    DEPTH_SCORES = {"WR1": 1.0, "WR2": 0.60, "WR3": 0.25}

    def _depth_chart(self, ctx: WeekContext, player: Player) -> tuple[float, str]:
        """Step 3, 20% — only the *source* of the role changes across the season."""
        rank = pos_rank_of(ctx, player)
        posrank = posrank_score(rank, "WR")
        # Current-season target-share role; ctx.roles stays blended for identification.
        usage_role = (ctx.roles_current or ctx.roles).get(player.player_id, "WR4+")
        usage = self.DEPTH_SCORES.get(usage_role, 0.0)
        label = depth_blend_label(
            ctx.week,
            pos_rank=rank,
            position="WR",
            posrank=posrank,
            usage_label=usage_role,
            usage=usage,
        )
        return blend_depth_score(ctx.week, posrank, usage), label

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        depth, depth_raw = self._depth_chart(ctx, player)
        rank = ctx.calibre_rank.get("WR", {}).get(player.player_id, 60)
        ranking = rank_to_score(rank, self.denom)
        qb = qb_quality_score(ctx, player.team)
        qb_raw = qb_quality_label(ctx, player.team)
        teammate = self._teammate(ctx, player)
        opp = opponent_of(ctx, player.team)
        mu = matchup_score(ctx.adj_fpa.get("WR", {}), opp or "", self.mode) if opp else 0.5
        sec = tiered_injury_penalty(ctx.injury_counts.get(opp or "", {}).get("SECONDARY", 0)) if opp else 0.5
        base = baseline_for_team(ctx, player.team)
        return [
            FactorScore(name="depth_chart", raw_value=depth_raw, score=depth, weight=self.w["depth_chart"]),
            FactorScore(name="qb_quality", raw_value=qb_raw, score=qb, weight=self.w["qb_quality"]),
            FactorScore(name="ranking", score=ranking, weight=self.w["ranking"]),
            FactorScore(name="teammate_injury", score=teammate, weight=self.w["teammate_injury"]),
            FactorScore(name="matchup", score=mu, weight=self.w["matchup"]),
            FactorScore(name="secondary_injury", score=sec, weight=self.w["secondary_injury"]),
            FactorScore(name="baseline", score=base, weight=self.w["baseline"]),
        ]

    def _teammate(self, ctx: WeekContext, player: Player) -> float:
        """§8.3 teammate injury — starting WR / elite TE primary; WR3 / non-elite TE secondary."""
        team = player.team.upper()
        elite_tes = ctx.static_ids.get("elite_tes", set())
        primary_out = 0
        secondary_out = 0

        for role in ("WR1", "WR2"):
            pid = role_player_on_team(ctx, team, role)
            if pid and pid != player.player_id and player_unavailable(ctx, pid):
                primary_out += 1

        wr3 = role_player_on_team(ctx, team, "WR3")
        if wr3 and wr3 != player.player_id and player_unavailable(ctx, wr3):
            secondary_out += 1

        for pid, role in ctx.roles.items():
            if not str(role).startswith("TE"):
                continue
            if team_of(ctx, pid) != team:
                continue
            if not player_unavailable(ctx, pid):
                continue
            if pid in elite_tes:
                primary_out += 1
            else:
                secondary_out += 1

        if primary_out + secondary_out >= 2:
            return 1.0
        if primary_out >= 1:
            return 1.0
        if secondary_out >= 1:
            return 0.75
        return 0.50
