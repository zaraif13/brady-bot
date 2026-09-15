from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.derive.adj_fpa import matchup_score
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer, WeekContext
from brady_bot.pickers.base import Picker
from brady_bot.scoring.shared import (
    baseline_for_team,
    depth_order_of,
    is_mobile_qb,
    opponent_of,
    player_unavailable,
    role_player_on_team,
    tiered_injury_penalty,
)


class QBPicker(Picker):
    position = Position.QB
    slots = 1

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["qb"]
        self.threshold = float(cfg.weights.global_cfg.get("qb_dual_threat_rush_att_threshold", 4.0))
        self.mode = str(cfg.weights.global_cfg.get("matchup_normalization", "percentile"))

    def gate(self, ctx: WeekContext, player: Player) -> ScoredPlayer | None:
        """QB1 binary gate. Unknown depth → eliminate (fail closed)."""
        order = depth_order_of(ctx, player.player_id, "QB")
        role = ctx.roles.get(player.player_id, "")
        qb1 = ctx.qb1_by_team.get(player.team.upper()) or ctx.qb1_by_team.get(player.team)

        is_qb1 = (
            (order is not None and order == 1)
            or role == "QB1"
            or (qb1 is not None and qb1 == player.player_id)
        )
        if is_qb1:
            return None

        # Effective start: known QB1 unavailable and this player is next up
        if qb1 and player_unavailable(ctx, qb1):
            if (order is not None and order <= 2) or role in ("QB2", "QB1"):
                return None

        # Fail closed: unknown or non-QB1 depth → eliminate (never score a backup by accident)
        return ScoredPlayer(
            player=player,
            start_score=0.0,
            gate_result="eliminated",
            gate_reason="not_qb1",
        )

    def flags_for(self, ctx: WeekContext, player: Player) -> list[str]:
        _, derived = is_mobile_qb(ctx, player.player_id, self.threshold)
        flags = super().flags_for(ctx, player)
        return [*flags, "style_derived"] if derived else flags

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        # Style — qb_styles list primary; rush att/game only for unlisted QBs
        mobile, derived = is_mobile_qb(ctx, player.player_id, self.threshold)
        style = 1.0 if mobile else 0.0
        if player.player_id in ctx.qb_styles:
            style_raw = "qb_styles"
        elif derived:
            rush = ctx.rush_att_pg.get(player.player_id)
            style_raw = f"rush_att_pg={rush:.2f}" if rush is not None else "rush_att_pg"
        else:
            style_raw = "pocket"

        # Pass-catchers — healthy WR1/WR2/WR3/TE1 on QB's NFL team
        team = player.team.upper()
        healthy = 0
        elite = 0
        elite_ids = ctx.static_ids.get("elite_wrs", set()) | ctx.static_ids.get("elite_tes", set())
        for role in ("WR1", "WR2", "WR3", "TE1"):
            pid = role_player_on_team(ctx, team, role)
            if not pid:
                continue
            if player_unavailable(ctx, pid):
                continue
            healthy += 1
            if pid in elite_ids:
                elite += 1
        base_health = {4: 0.90, 3: 0.70, 2: 0.50, 1: 0.25, 0: 0.00}.get(healthy, 0.0)
        # Elite boost is uncapped by design (§8.1). Do not clamp here — the shared
        # finalize_score path is the only place that caps and sets score_capped.
        raw_pc = base_health + 0.10 * elite

        ol = tiered_injury_penalty(ctx.injury_counts.get(player.team, {}).get("OL", 0))
        opp = opponent_of(ctx, player.team)
        mu = matchup_score(ctx.adj_fpa.get("QB", {}), opp or "", self.mode) if opp else 0.5
        sec = tiered_injury_penalty(ctx.injury_counts.get(opp or "", {}).get("SECONDARY", 0)) if opp else 0.5
        base = baseline_for_team(ctx, player.team)
        return [
            FactorScore(name="style", raw_value=style_raw, score=style, weight=self.w["style"]),
            FactorScore(
                name="pass_catcher",
                raw_value=f"preclamp={raw_pc:.2f};healthy={healthy};elite={elite}",
                score=raw_pc,
                weight=self.w["pass_catcher"],
            ),
            FactorScore(name="oline", score=ol, weight=self.w["oline"]),
            FactorScore(name="matchup", raw_value=str(opp), score=mu, weight=self.w["matchup"]),
            FactorScore(name="secondary_injury", score=sec, weight=self.w["secondary_injury"]),
            FactorScore(name="baseline", score=base, weight=self.w["baseline"]),
        ]
