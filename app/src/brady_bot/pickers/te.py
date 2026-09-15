from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.derive.adj_fpa import matchup_score
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer, WeekContext
from brady_bot.pickers.base import Picker
from brady_bot.scoring.shared import (
    baseline_for_team,
    depth_order_of,
    opponent_of,
    player_unavailable,
    qb_quality_label,
    qb_quality_score,
    rank_to_score,
    role_player_on_team,
    tiered_injury_penalty,
)


class TEPicker(Picker):
    position = Position.TE
    slots = 1

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["te"]
        self.mode = str(cfg.weights.global_cfg.get("matchup_normalization", "percentile"))
        self.denom = cfg.weights.calibre_denominators.get("TE", 29)

    def auto_start(self, ctx: WeekContext, player: Player, pool: list[Player]) -> ScoredPlayer | None:
        if player.player_id in ctx.static_ids.get("te_top4", set()):
            return ScoredPlayer(
                player=player, start_score=1.0, gate_result="auto_start", gate_reason="te_top4"
            )
        return None

    def gate(self, ctx: WeekContext, player: Player) -> ScoredPlayer | None:
        role = ctx.roles.get(player.player_id, "")
        if role == "TE1":
            return None

        team = player.team.upper()
        te1 = role_player_on_team(ctx, team, "TE1")
        if te1 is None:
            # fall back to roster depth order on same team
            team_tes = [p for p in ctx.roster if p.team == player.team and p.position == Position.TE]
            team_tes_sorted = sorted(
                team_tes, key=lambda p: depth_order_of(ctx, p.player_id, "TE") or 99
            )
            if team_tes_sorted and team_tes_sorted[0].player_id == player.player_id:
                return None
            if len(team_tes_sorted) >= 2 and player_unavailable(ctx, team_tes_sorted[0].player_id):
                if team_tes_sorted[1].player_id == player.player_id:
                    return None
        elif te1 == player.player_id:
            return None
        elif player_unavailable(ctx, te1):
            # promote next TE on team
            for pid, r in ctx.roles.items():
                if r.startswith("TE") and r != "TE1" and role_player_on_team(ctx, team, r) == pid:
                    if pid == player.player_id:
                        return None
            team_tes = [
                p
                for p in ctx.roster
                if p.team == player.team and p.position == Position.TE and p.player_id != te1
            ]
            team_tes_sorted = sorted(
                team_tes, key=lambda p: depth_order_of(ctx, p.player_id, "TE") or 99
            )
            if team_tes_sorted and team_tes_sorted[0].player_id == player.player_id:
                return None

        if role.startswith("TE") and role != "TE1":
            return ScoredPlayer(
                player=player, start_score=0.0, gate_result="eliminated", gate_reason="not_te1"
            )
        # if no role info, allow
        return None

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        rank = ctx.calibre_rank.get("TE", {}).get(player.player_id, 30)
        ranking = rank_to_score(rank, self.denom)
        qb = qb_quality_score(ctx, player.team)
        qb_raw = qb_quality_label(ctx, player.team)
        wr_inj = self._wr_injury(ctx, player)
        opp = opponent_of(ctx, player.team)
        mu = matchup_score(ctx.adj_fpa.get("TE", {}), opp or "", self.mode) if opp else 0.5
        sec = tiered_injury_penalty(ctx.injury_counts.get(opp or "", {}).get("SECONDARY", 0)) if opp else 0.5
        base = baseline_for_team(ctx, player.team)
        return [
            FactorScore(name="ranking", score=ranking, weight=self.w["ranking"]),
            FactorScore(name="qb_quality", raw_value=qb_raw, score=qb, weight=self.w["qb_quality"]),
            FactorScore(name="wr_injury", score=wr_inj, weight=self.w["wr_injury"]),
            FactorScore(name="matchup", score=mu, weight=self.w["matchup"]),
            FactorScore(name="secondary_injury", score=sec, weight=self.w["secondary_injury"]),
            FactorScore(name="baseline", score=base, weight=self.w["baseline"]),
        ]

    def _wr_injury(self, ctx: WeekContext, player: Player) -> float:
        """§8.4 Step 6 — top-down; multiple WR outs → 1.00 before WR2/WR3 rows."""
        team = player.team.upper()
        unavailable: list[str] = []
        for role in ("WR1", "WR2", "WR3"):
            pid = role_player_on_team(ctx, team, role)
            if pid and player_unavailable(ctx, pid):
                unavailable.append(role)
        if "WR1" in unavailable:
            return 1.0
        if len(unavailable) >= 2:
            return 1.0
        if "WR2" in unavailable:
            return 0.75
        if "WR3" in unavailable:
            return 0.60
        return 0.50
