from __future__ import annotations

import re

from brady_bot.explain import build_explanation
from brady_bot.models import FactorScore, Player, Position, ScoredPlayer
from brady_bot.optimizer import optimize_lineup
from brady_bot.config import load_config
from test_pickers import _fixture_ctx


def _player(pid: str, name: str, team: str, pos: Position) -> Player:
    return Player(player_id=pid, name=name, team=team, position=pos)


def test_explanation_auto_start():
    p = _player("STAR", "Star RB", "DET", Position.RB)
    scored = ScoredPlayer(
        player=p, start_score=1.0, gate_result="auto_start", gate_reason="rb_tier1"
    )
    text = build_explanation(scored, slot="RB1", outcome="starter")
    assert "Locked starter" in text
    assert " at RB:" in text or " at RB " in text or text.startswith("Locked starter at RB:")
    assert "RB1" not in text.split(":")[0]  # lineup slot label has no RB1
    assert "tier-1" in text.lower() or "RB tier-1" in text
    assert not re.search(r"\b0\.\d{2,}\b", text)  # no score dumps


def test_explanation_bye_and_not_qb1():
    p = _player("Q2", "Backup", "KC", Position.QB)
    bye = ScoredPlayer(player=p, start_score=0.0, gate_result="eliminated", gate_reason="bye")
    assert "bye" in build_explanation(bye, outcome="bench").lower()

    nq = ScoredPlayer(player=p, start_score=0.0, gate_result="eliminated", gate_reason="not_qb1")
    text = build_explanation(nq, outcome="bench")
    assert "depth-chart QB1" in text
    assert "Benched" in text


def test_explanation_scored_starter_uses_factor_phrases_not_weights():
    p = _player("WALKER", "Walker", "SEA", Position.RB)
    factors = [
        FactorScore(name="depth_chart", raw_value="role=RB1", score=1.0, weight=0.3),
        FactorScore(name="matchup", raw_value="SF", score=0.8, weight=0.2),
        FactorScore(name="baseline", score=0.5, weight=0.05),
    ]
    scored = ScoredPlayer(player=p, start_score=0.55, factors=factors, gate_result="passed")
    text = build_explanation(scored, slot="RB1", outcome="starter")
    assert text.startswith("Started at RB.")
    assert "team's RB1 on the depth chart" in text or "depth chart" in text.lower()
    assert "0.30" not in text
    assert "0.55" not in text
    assert "weight" not in text.lower()
    assert "start_score" not in text.lower()


def test_lineup_slot_label_strips_fantasy_slot_numbers():
    from brady_bot.explain import display_slot, empty_slot_warning, lineup_slot_label

    assert display_slot("RB1") == "RB"
    assert display_slot("RB2") == "RB"
    assert display_slot("WR1") == "WR"
    assert display_slot("WR2") == "WR"
    assert display_slot("DEF") == "D/ST"
    assert display_slot("FLEX") == "FLEX"
    assert lineup_slot_label("RB1") == "RB"
    assert empty_slot_warning("RB1") == "RB slot EMPTY"
    assert empty_slot_warning("DEF") == "D/ST slot EMPTY"
    assert "RB1" not in empty_slot_warning("RB2")


def test_explanation_flex_mentions_leftovers():
    p = _player("R3", "Extra RB", "BUF", Position.RB)
    scored = ScoredPlayer(player=p, start_score=0.4, gate_result="passed", factors=[])
    text = build_explanation(scored, slot="FLEX", outcome="starter")
    assert "Started at FLEX" in text
    assert "leftovers" in text.lower()


def test_explanation_ir():
    p = _player("X", "Hurt", "CHI", Position.WR)
    scored = ScoredPlayer(player=p, start_score=0.0, flags=["ir"])
    assert "IR" in build_explanation(scored, outcome="ir")


def test_explanation_dual_bench_covers_positional_and_flex():
    """FLEX leftovers who also lost RB/WR get both beats in the prose."""
    p = _player("R_LOW", "Low RB", "BUF", Position.RB)
    prior = [
        FactorScore(name="depth_chart", score=0.2, weight=0.3),
        FactorScore(name="matchup", score=0.5, weight=0.2),
    ]
    flex = [
        FactorScore(name="opportunity", score=0.1, weight=0.4),
        FactorScore(name="matchup", score=0.5, weight=0.25),
    ]
    scored = ScoredPlayer(
        player=p,
        start_score=0.35,
        factors=flex,
        gate_result="passed",
        prior_label="RB",
        prior_start_score=0.40,
        prior_weighted_sum=0.40,
        prior_factors=prior,
    )
    text = build_explanation(
        scored,
        slot="FLEX",
        outcome="bench",
        beat_by="Tony Pollard",
        prior_beat_by="Best RB",
    )
    assert "higher-ranked RBs" in text
    assert "edged out for FLEX by Tony Pollard" in text
    assert "Benched:" in text
    assert not re.search(r"\b0\.\d{2,}\b", text)


def test_explanation_dual_bench_te_uses_prior_beat_by():
    p = _player("T2", "TE leftover", "CHI", Position.TE)
    scored = ScoredPlayer(
        player=p,
        start_score=0.4,
        factors=[FactorScore(name="opportunity", score=0.7, weight=0.4)],
        gate_result="passed",
        prior_label="TE",
        prior_start_score=0.5,
        prior_factors=[FactorScore(name="qb_quality", score=0.5, weight=0.15)],
    )
    text = build_explanation(
        scored,
        slot="FLEX",
        outcome="bench",
        beat_by="Flex Winner",
        prior_beat_by="Starting TE",
    )
    assert "finished behind Starting TE for the TE slot" in text
    assert "edged out for FLEX by Flex Winner" in text


def test_flex_loser_retains_prior_positional_factors():
    """Bench leftover who lost FLEX keeps RB/WR/TE equation alongside FLEX equation."""
    from brady_bot.pickers.flex import FLEX_FACTOR_NAMES

    cfg = load_config()
    roster = [
        _player("Q1", "QB", "KC", Position.QB),
        _player("R1", "RB Starter A", "SF", Position.RB),
        _player("R2", "RB Starter B", "DAL", Position.RB),
        _player("R_BENCH", "Backup RB leftover", "SEA", Position.RB),
        _player("W1", "WR Starter A", "SF", Position.WR),
        _player("W2", "WR Starter B", "DAL", Position.WR),
        _player("W_FLEX", "WR1 leftover", "BUF", Position.WR),
        _player("T1", "TE", "SF", Position.TE),
        _player("K1", "K", "SF", Position.K),
        _player("DEF-SF", "SF", "SF", Position.DEF),
    ]
    ctx = _fixture_ctx(roster)
    ctx.snap_share = {"R1": 0.70, "R2": 0.65, "R_BENCH": 0.20}
    ctx.roles = {
        "W1": "WR1",
        "W2": "WR1",
        "W_FLEX": "WR1",
        "R1": "RB1",
        "R2": "RB1",
        "R_BENCH": "RB2",
        "T1": "TE1",
    }
    ctx.calibre_rank["RB"] = {"R1": 5, "R2": 6, "R_BENCH": 1}
    ctx.calibre_rank["WR"] = {"W1": 10, "W2": 11, "W_FLEX": 40}
    lineup = optimize_lineup(ctx, cfg)

    assert lineup.starters["FLEX"].player.player_id == "W_FLEX"
    # FLEX starter must not carry a prior eval
    assert not lineup.starters["FLEX"].prior_factors

    bench_rb = next(s for s in lineup.bench if s.player.player_id == "R_BENCH")
    assert bench_rb.prior_label == "RB"
    assert bench_rb.prior_factors
    assert "depth_chart" in {f.name for f in bench_rb.prior_factors}
    assert {f.name for f in bench_rb.factors} <= FLEX_FACTOR_NAMES
    assert "depth_chart" not in {f.name for f in bench_rb.factors}
    assert bench_rb.explanation
    assert "higher-ranked RBs" in bench_rb.explanation
    assert "FLEX" in bench_rb.explanation


def test_optimize_lineup_sets_explanations():
    cfg = load_config()
    roster = [
        _player("Q1", "QB", "KC", Position.QB),
        _player("R1", "RB1", "SF", Position.RB),
        _player("R2", "RB2", "DAL", Position.RB),
        _player("W1", "WR1", "SF", Position.WR),
        _player("W2", "WR2", "DAL", Position.WR),
        _player("T1", "TE1", "SF", Position.TE),
        _player("K1", "K1", "SF", Position.K),
        _player("DEF-SF", "SF", "SF", Position.DEF),
        _player("R3", "RB3", "BUF", Position.RB),
    ]
    ctx = _fixture_ctx(roster)
    lineup = optimize_lineup(ctx, cfg)
    assert lineup.starters["QB"] is not None
    assert lineup.starters["QB"].explanation
    assert "Started" in lineup.starters["QB"].explanation or "Locked" in lineup.starters["QB"].explanation
    if lineup.bench:
        assert lineup.bench[0].explanation
        assert "Benched" in lineup.bench[0].explanation or "bye" in lineup.bench[0].explanation.lower()


def test_fill_order_positional_first_flex_from_leftovers():
    """Top 2 RBs fill RB slots; third only eligible for FLEX — FLEX never steals an RB starter."""
    cfg = load_config()
    r1 = _player("R_BEST", "Best RB", "SF", Position.RB)
    r2 = _player("R_MID", "Mid RB", "DAL", Position.RB)
    r3 = _player("R_LOW", "Low RB", "BUF", Position.RB)
    roster = [
        _player("Q1", "QB", "KC", Position.QB),
        r1,
        r2,
        r3,
        _player("W1", "WR A", "SF", Position.WR),
        _player("W2", "WR B", "DAL", Position.WR),
        # Extra WR so FLEX pool has >1 candidate (avoids only_rostered short-circuit)
        _player("W3", "WR C", "KC", Position.WR),
        _player("T1", "TE", "SF", Position.TE),
        _player("K1", "K", "SF", Position.K),
        _player("DEF-SF", "SF", "SF", Position.DEF),
    ]
    ctx = _fixture_ctx(roster)
    # Force clear depth/snap ranking so R_BEST and R_MID win RB slots
    ctx.snap_share = {"R_BEST": 0.7, "R_MID": 0.65, "R_LOW": 0.25}
    ctx.roles = {
        "R_BEST": "RB1",
        "R_MID": "RB1",
        "R_LOW": "RB3",
        "W1": "WR1",
        "W2": "WR1",
        "W3": "WR3",
    }
    ctx.calibre_rank["RB"] = {"R_BEST": 1, "R_MID": 2, "R_LOW": 30}
    ctx.calibre_rank["WR"] = {"W1": 1, "W2": 2, "W3": 25}
    lineup = optimize_lineup(ctx, cfg)
    rb_ids = {
        lineup.starters["RB1"].player.player_id,
        lineup.starters["RB2"].player.player_id,
    }
    assert rb_ids == {"R_BEST", "R_MID"}
    flex = lineup.starters.get("FLEX")
    assert flex is not None
    # FLEX must be a leftover (not one of the dedicated RB starters)
    assert flex.player.player_id not in rb_ids
    # With a weak third WR also leftover, FLEX may be R_LOW or W3 — either is fine
    assert flex.player.player_id in {"R_LOW", "W3"}
    assert flex.explanation and "leftovers" in flex.explanation.lower()
    # No numbered-slot EMPTY warnings
    assert not any("RB1 EMPTY" in w or "WR1 EMPTY" in w for w in lineup.warnings)
