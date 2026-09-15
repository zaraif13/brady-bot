from __future__ import annotations

import uuid
from typing import Optional

from brady_bot.config import AppConfig
from brady_bot.explain import build_explanation, empty_slot_warning
from brady_bot.models import Lineup, Player, Position, ScoredPlayer, WeekContext
from brady_bot.pickers import (
    DefensePicker,
    FlexPicker,
    KickerPicker,
    QBPicker,
    RBPicker,
    TEPicker,
    WRPicker,
)
from brady_bot.pickers.base import rank_key
from brady_bot.scoring.shared import injury_abbrev, opponent_of, player_unavailable


def _annotate(ctx: WeekContext, scored: ScoredPlayer) -> ScoredPlayer:
    opp = opponent_of(ctx, scored.player.team)
    if scored.player.team in ctx.bye_teams:
        opp_label = "BYE"
    elif opp:
        game = ctx.games.get(scored.player.team)
        if game and scored.player.team == game.home_team:
            opp_label = opp
        else:
            opp_label = f"@{opp}" if opp else None
    else:
        opp_label = None
    scored.opponent = opp_label
    scored.headshot = scored.player.headshot
    rec = ctx.injuries.get(scored.player.player_id)
    scored.injury_status = injury_abbrev(rec)
    scored.injury_label = rec.report_status if rec else None
    scored.is_unavailable = player_unavailable(ctx, scored.player.player_id)
    return scored


def _with_explanation(
    scored: ScoredPlayer,
    *,
    slot: str | None = None,
    outcome: str = "starter",
    beat_by: str | None = None,
    position_label: str | None = None,
    prior_beat_by: str | None = None,
) -> ScoredPlayer:
    scored.explanation = build_explanation(
        scored,
        slot=slot,
        outcome=outcome,
        beat_by=beat_by,
        position_label=position_label,
        prior_beat_by=prior_beat_by,
    )
    return scored


def _attach_prior_eval(flex_scored: ScoredPlayer, positional: ScoredPlayer) -> ScoredPlayer:
    """Copy RB/WR/TE evaluation onto a FLEX leftover who lost both contests."""
    flex_scored.prior_label = positional.player.position.value
    flex_scored.prior_start_score = positional.start_score
    flex_scored.prior_weighted_sum = positional.weighted_sum
    flex_scored.prior_bonus = positional.bonus
    flex_scored.prior_flags = list(positional.flags)
    flex_scored.prior_factors = list(positional.factors)
    return flex_scored


def optimize_lineup(
    ctx: WeekContext,
    cfg: AppConfig,
    ir_ids: Optional[set[str]] = None,
) -> Lineup:
    """
    Fill order (tech spec):
      1) Positional formulas → QB, RB×2, WR×2, TE, K, D/ST
      2) Leftover eligible RB/WR/TE → FLEX formula (last)
      3) Everyone else → bench / IR

    Internal keys RB1/WR2 are opaque lineup indices, not depth-chart roles.
    """
    ir_ids = ir_ids or set()
    warnings = list(ctx.warnings)
    run_id = uuid.uuid4().hex[:8]

    by_pos: dict[Position, list[Player]] = {p: [] for p in Position}
    for p in ctx.roster:
        if p.player_id in ir_ids:
            continue
        by_pos[p.position].append(p)

    starters: dict[str, Optional[ScoredPlayer]] = {
        "QB": None,
        "RB1": None,
        "RB2": None,
        "WR1": None,
        "WR2": None,
        "TE": None,
        "FLEX": None,
        "K": None,
        "DEF": None,
    }
    flex_pool: list[ScoredPlayer] = []
    used: set[str] = set()

    # --- Positional phase (dedicated slots) ---
    qb_s, qb_b = QBPicker(cfg).select(ctx, by_pos[Position.QB])
    if qb_s:
        starters["QB"] = _with_explanation(
            _annotate(ctx, qb_s[0]), slot="QB", outcome="starter", position_label="QB"
        )
        used.add(qb_s[0].player.player_id)
    else:
        warnings.append(empty_slot_warning("QB"))

    rb_s, rb_b = RBPicker(cfg).select(ctx, by_pos[Position.RB])
    for i, slot in enumerate(("RB1", "RB2")):
        if i < len(rb_s):
            starters[slot] = _with_explanation(
                _annotate(ctx, rb_s[i]), slot=slot, outcome="starter", position_label="RB"
            )
            used.add(rb_s[i].player.player_id)
        else:
            warnings.append(empty_slot_warning(slot))
    flex_pool.extend([s for s in rb_b if s.gate_result != "eliminated"])

    wr_s, wr_b = WRPicker(cfg).select(ctx, by_pos[Position.WR])
    for i, slot in enumerate(("WR1", "WR2")):
        if i < len(wr_s):
            starters[slot] = _with_explanation(
                _annotate(ctx, wr_s[i]), slot=slot, outcome="starter", position_label="WR"
            )
            used.add(wr_s[i].player.player_id)
        else:
            warnings.append(empty_slot_warning(slot))
    flex_pool.extend([s for s in wr_b if s.gate_result != "eliminated"])

    te_s, te_b = TEPicker(cfg).select(ctx, by_pos[Position.TE])
    if te_s:
        starters["TE"] = _with_explanation(
            _annotate(ctx, te_s[0]), slot="TE", outcome="starter", position_label="TE"
        )
        used.add(te_s[0].player.player_id)
    else:
        warnings.append(empty_slot_warning("TE"))
    flex_pool.extend([s for s in te_b if s.gate_result != "eliminated"])

    k_s, k_b = KickerPicker(cfg).select(ctx, by_pos[Position.K])
    if k_s:
        starters["K"] = _with_explanation(
            _annotate(ctx, k_s[0]), slot="K", outcome="starter", position_label="K"
        )
        used.add(k_s[0].player.player_id)
    else:
        warnings.append(empty_slot_warning("K"))

    d_s, d_b = DefensePicker(cfg).select(ctx, by_pos[Position.DEF])
    if d_s:
        starters["DEF"] = _with_explanation(
            _annotate(ctx, d_s[0]), slot="DEF", outcome="starter", position_label="DEF"
        )
        used.add(d_s[0].player.player_id)
    else:
        warnings.append(empty_slot_warning("DEF"))

    # --- FLEX phase (last): leftovers only ---
    # Recompute exclusively with FlexPicker / lineup-picker-FLEX.md.
    # Do NOT rank leftovers by RB/WR/TE Start Score — those equations are not comparable.
    positional_by_id = {s.player.player_id: s for s in flex_pool}
    flex_cands = [s.player for s in flex_pool if s.player.player_id not in used]
    flex_s, flex_rest = FlexPicker(cfg).select(ctx, flex_cands)
    flex_by_id = {s.player.player_id: s for s in flex_s + flex_rest}
    flex_winner_name: str | None = None
    if flex_s:
        starters["FLEX"] = _with_explanation(
            _annotate(ctx, flex_s[0]), slot="FLEX", outcome="starter", position_label="FLEX"
        )
        used.add(flex_s[0].player.player_id)
        flex_winner_name = flex_s[0].player.name
    else:
        warnings.append(empty_slot_warning("FLEX"))

    # Position starters that "beat" bench mates (for beat_by on FLEX leftovers)
    pos_winners: dict[str, str] = {}
    if starters.get("QB"):
        pos_winners["QB"] = starters["QB"].player.name
    if starters.get("RB1"):
        pos_winners["RB"] = starters["RB1"].player.name
    if starters.get("WR1"):
        pos_winners["WR"] = starters["WR1"].player.name
    if starters.get("TE"):
        pos_winners["TE"] = starters["TE"].player.name
    if starters.get("K"):
        pos_winners["K"] = starters["K"].player.name
    if starters.get("DEF"):
        pos_winners["DEF"] = starters["DEF"].player.name

    flex_rest_ids = {s.player.player_id for s in flex_rest}

    bench: list[ScoredPlayer] = []
    for p in ctx.roster:
        if p.player_id in used or p.player_id in ir_ids:
            continue
        # Prefer Flex Score objects for anyone who contested FLEX (not positional Start Score)
        match = flex_by_id.get(p.player_id)
        from_flex = match is not None
        if match is None:
            match = next(
                (
                    s
                    for s in rb_b + wr_b + te_b + qb_b + k_b + d_b
                    if s.player.player_id == p.player_id
                ),
                None,
            )
        if match:
            annotated = _annotate(ctx, match)
        else:
            annotated = _annotate(
                ctx,
                ScoredPlayer(player=p, start_score=0.0, gate_result="passed"),
            )

        prior_beat_by = None
        if from_flex and p.player_id in flex_rest_ids:
            positional = positional_by_id.get(p.player_id)
            if positional is not None and positional.factors:
                annotated = _attach_prior_eval(annotated, positional)
            prior_beat_by = pos_winners.get(p.position.value)

        beat_by = None
        slot_for_bench = None
        pos_label = p.position.value
        if annotated.gate_result == "eliminated":
            pass
        elif p.player_id in flex_rest_ids and flex_winner_name:
            beat_by = flex_winner_name
            slot_for_bench = "FLEX"
            pos_label = "FLEX"
        elif p.position.value in pos_winners:
            # Lost a positional slot (or was leftover after RB/WR filled)
            if p.position in (Position.RB, Position.WR) and p.player_id not in flex_rest_ids:
                # still in flex_pool path means they lost RB/WR then lost flex — covered above
                beat_by = pos_winners[p.position.value]
            elif p.position not in (Position.RB, Position.WR):
                beat_by = pos_winners.get(p.position.value)

        bench.append(
            _with_explanation(
                annotated,
                slot=slot_for_bench,
                outcome="bench",
                beat_by=beat_by,
                position_label=pos_label,
                prior_beat_by=prior_beat_by,
            )
        )
    bench.sort(key=rank_key)

    ir_list = [
        _with_explanation(
            _annotate(
                ctx,
                ScoredPlayer(player=p, start_score=0.0, gate_result="passed", flags=["ir"]),
            ),
            outcome="ir",
        )
        for p in ctx.roster
        if p.player_id in ir_ids
    ]

    opponents = {}
    for p in ctx.roster:
        if p.team in ctx.bye_teams:
            opponents[p.player_id] = "BYE"
        else:
            opp = opponent_of(ctx, p.team)
            opponents[p.player_id] = opp or "—"

    injuries_by_player = {}
    for p in ctx.roster:
        rec = ctx.injuries.get(p.player_id)
        if rec and rec.report_status:
            # Full label for UI badges (matches /api/meta/week)
            injuries_by_player[p.player_id] = rec.report_status

    mode = str(cfg.weights.global_cfg.get("matchup_normalization", "percentile"))
    return Lineup(
        season=ctx.season,
        week=ctx.week,
        run_id=run_id,
        fetched_at=ctx.fetched_at,
        blended=ctx.blended,
        matchup_normalization=mode,
        starters=starters,
        bench=bench,
        ir=ir_list,
        warnings=warnings,
        opponents=opponents,
        injuries_by_player=injuries_by_player,
    )
