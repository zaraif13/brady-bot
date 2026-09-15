from __future__ import annotations

from abc import ABC, abstractmethod

from brady_bot.derive.depth import NO_DEPTH_ENTRY
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer, WeekContext
from brady_bot.scoring.shared import player_unavailable


def rank_key(scored: ScoredPlayer) -> tuple[float, float, str]:
    """Sort key: start_score, then weighted_sum (pre-bonus), then player_id."""
    ws = scored.weighted_sum if scored.weighted_sum is not None else scored.start_score
    return (-scored.start_score, -ws, scored.player.player_id)


def apply_start_score_cap(weighted_sum: float, bonus: float = 0.0) -> tuple[float, list[str]]:
    """Single clamp point: start_score = min(1.00, weighted_sum + bonus) + score_capped flag."""
    uncapped = weighted_sum + bonus
    start = max(0.0, min(1.0, uncapped))
    flags: list[str] = []
    if uncapped > 1.0 + 1e-12:
        flags.append("score_capped")
    return start, flags


class Picker(ABC):
    position: Position
    slots: int = 1

    def select(
        self, ctx: WeekContext, candidates: list[Player]
    ) -> tuple[list[ScoredPlayer], list[ScoredPlayer]]:
        filtered: list[Player] = []
        eliminated: list[ScoredPlayer] = []
        for p in candidates:
            if p.team in ctx.bye_teams:
                eliminated.append(
                    ScoredPlayer(
                        player=p,
                        start_score=0.0,
                        gate_result="eliminated",
                        gate_reason="bye",
                    )
                )
                continue
            if player_unavailable(ctx, p.player_id):
                eliminated.append(
                    ScoredPlayer(
                        player=p,
                        start_score=0.0,
                        gate_result="eliminated",
                        gate_reason="unavailable",
                    )
                )
                continue
            filtered.append(p)

        # Roster short-circuit
        if len(filtered) <= self.slots and filtered:
            starters = [
                ScoredPlayer(
                    player=p,
                    start_score=1.0,
                    gate_result="auto_start",
                    gate_reason="only_rostered",
                    flags=self.flags_for(ctx, p),
                )
                for p in filtered
            ]
            return starters, eliminated

        scored: list[ScoredPlayer] = []
        for p in filtered:
            # Spec order: gate → auto-start → score
            gate = self.gate(ctx, p)
            if gate is not None:
                if not gate.flags:
                    gate.flags = self.flags_for(ctx, p)
                scored.append(gate)
                continue
            auto = self.auto_start(ctx, p, filtered)
            if auto:
                if not auto.flags:
                    auto.flags = self.flags_for(ctx, p)
                scored.append(auto)
                continue
            factors = self.score_factors(ctx, p)
            # Do not clamp here — finalize_score is the only place that decides
            # whether weighted_sum + bonus exceeds 1.00 and sets score_capped.
            weighted = sum(f.contribution for f in factors)
            start, bonus, extra_flags = self.finalize_score(ctx, p, weighted)
            flags = list(dict.fromkeys([*self.flags_for(ctx, p), *extra_flags]))
            scored.append(
                ScoredPlayer(
                    player=p,
                    start_score=start,
                    factors=factors,
                    gate_result="passed",
                    flags=flags,
                    weighted_sum=weighted,
                    bonus=bonus,
                )
            )

        # Separate eliminated from gate
        alive = [s for s in scored if s.gate_result != "eliminated"]
        dead = [s for s in scored if s.gate_result == "eliminated"] + eliminated

        auto = [s for s in alive if s.gate_result == "auto_start"]
        rest = [s for s in alive if s.gate_result != "auto_start"]
        rest.sort(key=rank_key)

        starters: list[ScoredPlayer] = []
        starters.extend(auto[: self.slots])
        need = self.slots - len(starters)
        starters.extend(rest[:need])
        bench = rest[need:] + auto[self.slots :]
        # Keep deterministic order on bench
        bench.sort(key=rank_key)
        return starters, bench + dead

    def auto_start(self, ctx: WeekContext, player: Player, pool: list[Player]) -> ScoredPlayer | None:
        return None

    def gate(self, ctx: WeekContext, player: Player) -> ScoredPlayer | None:
        return None

    def flags_for(self, ctx: WeekContext, player: Player) -> list[str]:
        # D20 — absence from the depth chart scores 0.00 like a rank 4+, so the flag is
        # what distinguishes a real demotion from a data gap. ctx.no_depth_entry is only
        # populated while pos_rank still carries weight (Weeks 1–4); past that the
        # absence has no scoring effect and the flag would be noise.
        if player.player_id in ctx.no_depth_entry:
            return [NO_DEPTH_ENTRY]
        return []

    def finalize_score(
        self, ctx: WeekContext, player: Player, weighted_sum: float
    ) -> tuple[float, float, list[str]]:
        """Return (start_score, bonus, extra_flags). Cap + score_capped live here only."""
        start, flags = apply_start_score_cap(weighted_sum, bonus=0.0)
        return start, 0.0, flags

    @abstractmethod
    def score_factors(self, ctx: WeekContext, player: Player) -> list[FactorScore]:
        ...
