from __future__ import annotations

from brady_bot.config import AppConfig
from brady_bot.models import FactorScore, Player, Position, WeekContext
from brady_bot.pickers.base import Picker
from brady_bot.scoring.shared import opponent_of


class KickerPicker(Picker):
    position = Position.K
    slots = 1

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.w = cfg.weights.positions["k"]

    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        ts = ctx.team_stats.get(player.team)
        off = self._offense_tier(ts.offense_rank if ts else 16)
        # RZ inefficiency: rank 1 = least efficient = best for kicker
        rz = self._rz_tier(ts.scoring_efficiency_rank if ts else 16)
        opp = opponent_of(ctx, player.team)
        opp_ts = ctx.team_stats.get(opp or "")
        opp_def = self._opp_def_tier(opp_ts.total_defense_rank if opp_ts else 16)
        game = ctx.games.get(player.team)
        total = game.game_total if game else 44.0
        env = self._env(total)
        krank = ctx.calibre_rank.get("K", {}).get(player.player_id, 20)
        kcal = self._k_calibre(krank)
        return [
            FactorScore(name="team_offense", score=off, weight=self.w["team_offense"]),
            FactorScore(name="red_zone", raw_value="rank1=least_efficient", score=rz, weight=self.w["red_zone"]),
            FactorScore(name="opp_defense", score=opp_def, weight=self.w["opp_defense"]),
            FactorScore(name="game_environment", raw_value=f"total={total}", score=env, weight=self.w["game_environment"]),
            FactorScore(name="kicker_calibre", score=kcal, weight=self.w["kicker_calibre"]),
        ]

    @staticmethod
    def _offense_tier(rank: int) -> float:
        bands = [(5, 1.0), (10, 0.85), (16, 0.70), (22, 0.50), (28, 0.30), (32, 0.10)]
        for hi, score in bands:
            if rank <= hi:
                return score
        return 0.10

    @staticmethod
    def _rz_tier(rank: int) -> float:
        bands = [(5, 1.0), (10, 0.85), (16, 0.65), (22, 0.45), (28, 0.25), (32, 0.10)]
        for hi, score in bands:
            if rank <= hi:
                return score
        return 0.10

    @staticmethod
    def _opp_def_tier(rank: int) -> float:
        if rank <= 4:
            return 0.30
        if rank <= 12:
            return 0.85
        if rank <= 20:
            return 0.65
        if rank <= 28:
            return 0.45
        return 0.20

    @staticmethod
    def _env(total: float) -> float:
        if total < 40:
            return 1.0
        if total < 44:
            return 0.75
        if total < 48:
            return 0.50
        if total < 52:
            return 0.30
        return 0.10

    @staticmethod
    def _k_calibre(rank: int) -> float:
        if rank <= 3:
            return 1.0
        if rank <= 8:
            return 0.80
        if rank <= 16:
            return 0.55
        if rank <= 24:
            return 0.35
        return 0.15
