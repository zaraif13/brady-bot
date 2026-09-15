from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.models import FactorScore, Player, Position, WeekContext
from brady_bot.pickers.base import Picker
from brady_bot.scoring.shared import (
    QB_CALIBRE_FALLBACK_FLAG,
    backup_qb_on_team,
    is_mobile_qb,
    opponent_of,
    player_unavailable,
    qb_calibre_of,
    rank_to_score,
    role_player_on_team,
    team_of,
    tiered_injury_penalty,
)


class DefensePicker(Picker):
    position = Position.DEF
    slots = 1

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["def"]
        self.denom = cfg.weights.calibre_denominators.get("DEF", 31)
        self.qb_mobile_threshold = float(
            cfg.weights.global_cfg.get("qb_dual_threat_rush_att_threshold", 4.0)
        )

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        opp = opponent_of(ctx, player.team)
        opp_qb, opp_qb_raw = self._opp_qb(ctx, opp)
        opp_skill = self._opp_skill(ctx, opp)
        opp_ol = self._opp_ol(ctx, opp)
        own_inj = tiered_injury_penalty(ctx.injury_counts.get(player.team, {}).get("DEFENSE_ALL", 0))
        base = self._baseline(ctx, opp)
        ts = ctx.team_stats.get(player.team)
        cal = rank_to_score(ts.defense_calibre_rank if ts else 16, self.denom)
        return [
            FactorScore(
                name="opp_qb", raw_value=opp_qb_raw, score=opp_qb, weight=self.w["opp_qb"]
            ),
            FactorScore(name="opp_skill", score=opp_skill, weight=self.w["opp_skill"]),
            FactorScore(name="opp_oline", score=opp_ol, weight=self.w["opp_oline"]),
            FactorScore(name="defensive_injury", score=own_inj, weight=self.w["defensive_injury"]),
            FactorScore(name="baseline", score=base, weight=self.w["baseline"]),
            FactorScore(name="defense_calibre", score=cal, weight=self.w["defense_calibre"]),
        ]

    def _opp_qb(self, ctx: WeekContext, opp: str | None) -> tuple[float, str | None]:
        """§8.6 opposing QB — top-down, first match wins.

        Reads the same S12 rank as WR/TE Step 5 and FLEX Step 4, inverted: a bad or
        unavailable opposing QB is good news for your defence (D21). One ranking means
        this factor and those three can never disagree about the same quarterback.
        """
        if not opp:
            return 0.50, None
        opp = opp.upper()
        qb1 = ctx.qb1_by_team.get(opp)

        def label(text: str, qb_id: str | None) -> str:
            _, fallback = qb_calibre_of(ctx, qb_id)
            return f"{text}; {QB_CALIBRE_FALLBACK_FLAG}" if fallback else text

        if qb1 and player_unavailable(ctx, qb1):
            backup = backup_qb_on_team(ctx, opp, qb1)
            backup_rank, _ = qb_calibre_of(ctx, backup)
            shown = "unranked" if backup_rank is None else backup_rank
            if backup_rank is None or backup_rank >= 29:
                return 1.0, label(f"opp QB1 out, backup rank {shown}", backup)
            if backup_rank >= 15:
                return 0.85, label(f"opp QB1 out, backup rank {shown}", backup)
            # Capable backup (rank 1–14) still favors DEF vs injured starter
            return 0.85, label(f"opp QB1 out, capable backup rank {shown}", backup)

        if not qb1:
            return 0.50, "no opposing QB1 identified"

        ts = ctx.team_stats.get(opp)
        if ts and ts.qb_turnover_rank <= 10:
            return 0.80, label("opp QB1 playing, top-10 turnover rate", qb1)

        rank, _ = qb_calibre_of(ctx, qb1)
        if rank is None:
            rank = 16
        mobile, _ = is_mobile_qb(ctx, qb1, self.qb_mobile_threshold)
        raw = label(f"opp QB1 playing, calibre rank {rank}" + (", mobile" if mobile else ""), qb1)
        if rank <= 5 and mobile:
            return 0.0, raw
        if rank <= 5:
            return 0.15, raw
        if rank <= 12:
            return 0.35, raw
        if rank <= 20:
            return 0.50, raw
        return 0.65, raw

    def _opp_skill(self, ctx: WeekContext, opp: str | None) -> float:
        """§8.6 opposing skill injuries — top-down role table."""
        if not opp:
            return 0.50
        opp = opp.upper()

        def out(role: str) -> bool:
            pid = role_player_on_team(ctx, opp, role)
            return bool(pid and player_unavailable(ctx, pid))

        wr1_out = out("WR1")
        wr2_out = out("WR2")
        wr3_out = out("WR3")
        te1_out = out("TE1")
        rb1_out = out("RB1")

        if wr1_out and wr2_out and te1_out:
            return 1.0
        if wr1_out and (wr2_out or te1_out):
            return 0.85
        if wr1_out:
            return 0.70
        if rb1_out:
            return 0.65
        if wr2_out or wr3_out or te1_out:
            return 0.55

        # No significant injuries — check elite WR/TE on opp team
        elite = ctx.static_ids.get("elite_wrs", set()) | ctx.static_ids.get("elite_tes", set())
        for pid in elite:
            if team_of(ctx, pid) == opp and not player_unavailable(ctx, pid):
                return 0.25
        return 0.50

    def _opp_ol(self, ctx: WeekContext, opp: str | None) -> float:
        """Opposing O-line weakness — S10 rank inverted. lineup-picker-OL.md Step 4."""
        if not opp:
            return 0.50
        opp_u = opp.upper()
        ol_rank = ctx.oline_ranks.get(opp_u, ctx.oline_ranks.get(opp))
        if ol_rank is None:
            return 0.50
        ol_out = ctx.injury_counts.get(opp_u, {}).get("OL", 0)
        if not ol_out:
            ol_out = ctx.injury_counts.get(opp, {}).get("OL", 0)
        # Top-down; first match wins
        if ol_rank >= 29 and ol_out >= 2:
            return 1.0
        if ol_rank >= 23 or ol_out >= 2:
            return 0.85
        if ol_rank >= 23:
            return 0.70
        if ol_out == 1:
            return 0.60
        if 13 <= ol_rank <= 22:
            return 0.50
        if ol_rank <= 5:
            return 0.10
        if ol_rank <= 12:
            return 0.25
        return 0.50

    def _baseline(self, ctx: WeekContext, opp: str | None) -> float:
        if not opp:
            return 0.50
        game = ctx.games.get(opp) or ctx.games.get(opp.upper())
        if not game:
            return 0.50
        total = game.implied_total_for(opp)
        if total < 17:
            return 1.0
        if total < 20:
            return 0.85
        if total < 23:
            return 0.65
        if total < 26:
            return 0.40
        if total < 29:
            return 0.20
        return 0.0
