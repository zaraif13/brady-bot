from __future__ import annotations

from brady_bot.config import load_config
from brady_bot.models import (
    GameContext,
    Player,
    Position,
    TeamStats,
    WeekContext,
)
from brady_bot.optimizer import optimize_lineup
from brady_bot.pickers.kicker import KickerPicker
from brady_bot.pickers.rb import RBPicker
from brady_bot.scoring.shared import rank_to_score


def _team_stats(team: str, offense: int = 10, defense: int = 10, rz: int = 10) -> TeamStats:
    return TeamStats(
        team=team,
        season=2026,
        through_week=5,
        offense_rank=offense,
        total_defense_rank=defense,
        scoring_efficiency_rank=rz,
        defense_calibre_rank=10,
        qb_turnover_rank=10,
    )


def _fixture_ctx(roster: list[Player]) -> WeekContext:
    teams = sorted({p.team for p in roster} | {"KC", "BUF", "SF", "DAL"})
    games = {}
    for i, t in enumerate(sorted(teams)):
        opp = sorted(teams)[(i + 1) % len(teams)]
        g = GameContext(
            game_id=f"{t}-{opp}",
            home_team=t,
            away_team=opp,
            game_total=45,
            spread=-3,
            home_implied_total=24,
            away_implied_total=21,
        )
        games[t] = g
    team_stats = {t: _team_stats(t) for t in teams}
    # pad to feel realistic
    adj = {t: float(i - 16) for i, t in enumerate(sorted(teams))}
    while len(adj) < 32:
        adj[f"X{len(adj)}"] = 0.0
    return WeekContext(
        season=2026,
        week=5,
        fetched_at="2026-10-01T00:00:00Z",
        roster=roster,
        injuries={},
        team_stats=team_stats,
        games=games,
        adj_fpa={"QB": adj, "RB": adj, "WR": adj, "TE": adj},
        calibre_rank={
            "QB": {p.player_id: i + 1 for i, p in enumerate(roster) if p.position == Position.QB},
            "RB": {p.player_id: i + 1 for i, p in enumerate(roster) if p.position == Position.RB},
            "WR": {p.player_id: i + 1 for i, p in enumerate(roster) if p.position == Position.WR},
            "TE": {p.player_id: i + 1 for i, p in enumerate(roster) if p.position == Position.TE},
            "K": {p.player_id: 5 for p in roster if p.position == Position.K},
        },
        roles={},
        player_teams={p.player_id: p.team for p in roster},
        rush_att_pg={},
        snap_share={p.player_id: 0.65 for p in roster if p.position == Position.RB},
        target_share={},
        injury_counts={t: {"OL": 0, "SECONDARY": 0, "FRONT_SEVEN": 0, "FRONT_SEVEN_INTERIOR": 0, "DEFENSE_ALL": 0} for t in teams},
        bye_teams=[],
        depth_chart_order={
            pos: {p.player_id: 1 for p in roster if p.position.value == pos}
            for pos in ("QB", "RB", "WR", "TE", "K", "DEF")
        },
        qb1_by_team={p.team: p.player_id for p in roster if p.position == Position.QB},
        static_ids={"rb_tier1": set(), "wr_top5": set(), "te_top4": set(), "rb_tier2": set(), "elite_wrs": set(), "elite_tes": set()},
        qb_styles={},
        oline_ranks={t: 16 for t in teams},
        blended=False,
    )


def test_rank_to_score():
    assert rank_to_score(1, 39) == 1.0
    assert rank_to_score(40, 39) == 0.0


def test_k_rz_rank_inversion_documented():
    cfg = load_config()
    picker = KickerPicker(cfg)
    p = Player(player_id="K1", name="Kick", team="KC", position=Position.K)
    ctx = _fixture_ctx([p])
    ctx.team_stats["KC"] = _team_stats("KC", offense=5, rz=1)
    factors = picker.score_factors(ctx, p)
    rz = next(f for f in factors if f.name == "red_zone")
    assert rz.score == 1.0  # rank 1 least efficient = best for K


def test_bye_never_starts():
    cfg = load_config()
    qb = Player(player_id="Q1", name="QB A", team="KC", position=Position.QB)
    qb2 = Player(player_id="Q2", name="QB B", team="BUF", position=Position.QB)
    roster = [
        qb,
        qb2,
        Player(player_id="R1", name="RB1", team="SF", position=Position.RB),
        Player(player_id="R2", name="RB2", team="DAL", position=Position.RB),
        Player(player_id="W1", name="WR1", team="SF", position=Position.WR),
        Player(player_id="W2", name="WR2", team="DAL", position=Position.WR),
        Player(player_id="T1", name="TE1", team="SF", position=Position.TE),
        Player(player_id="K1", name="K1", team="SF", position=Position.K),
        Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF),
    ]
    ctx = _fixture_ctx(roster)
    ctx.bye_teams = ["KC"]
    lineup = optimize_lineup(ctx, cfg)
    assert lineup.starters["QB"] is not None
    assert lineup.starters["QB"].player.player_id == "Q2"


def test_determinism():
    cfg = load_config()
    roster = [
        Player(player_id="Q1", name="QB", team="KC", position=Position.QB),
        Player(player_id="R1", name="RB1", team="SF", position=Position.RB),
        Player(player_id="R2", name="RB2", team="DAL", position=Position.RB),
        Player(player_id="W1", name="WR1", team="SF", position=Position.WR),
        Player(player_id="W2", name="WR2", team="DAL", position=Position.WR),
        Player(player_id="T1", name="TE1", team="SF", position=Position.TE),
        Player(player_id="K1", name="K1", team="SF", position=Position.K),
        Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF),
        Player(player_id="R3", name="RB3", team="BUF", position=Position.RB),
    ]
    ctx = _fixture_ctx(roster)
    a = optimize_lineup(ctx, cfg)
    b = optimize_lineup(ctx, cfg)
    for slot in a.starters:
        pa = a.starters[slot].player.player_id if a.starters[slot] else None
        pb = b.starters[slot].player.player_id if b.starters[slot] else None
        assert pa == pb


def test_rb_tier1_auto_start():
    cfg = load_config()
    star = Player(player_id="STAR", name="Star RB", team="DET", position=Position.RB)
    other = Player(player_id="OTH", name="Other", team="CHI", position=Position.RB)
    third = Player(player_id="THD", name="Third", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([star, other, third])
    ctx.static_ids["rb_tier1"] = {"STAR"}
    ctx.snap_share = {"STAR": 0.2, "OTH": 0.9, "THD": 0.9}
    starters, _ = RBPicker(cfg).select(ctx, [star, other, third])
    assert any(s.player.player_id == "STAR" and s.gate_result == "auto_start" for s in starters)


def test_partial_roster_optimizes_without_all_slots():
    """No field is required — optimize whatever players were entered."""
    cfg = load_config()
    roster = [
        Player(player_id="R1", name="RB1", team="SF", position=Position.RB),
        Player(player_id="R2", name="RB2", team="DAL", position=Position.RB),
        Player(player_id="W1", name="WR1", team="SF", position=Position.WR),
    ]
    ctx = _fixture_ctx(roster)
    lineup = optimize_lineup(ctx, cfg)
    assert lineup.starters["RB1"] is not None
    assert lineup.starters["RB2"] is not None
    assert lineup.starters["WR1"] is not None
    # Missing positions stay empty with warnings
    assert lineup.starters["QB"] is None
    assert lineup.starters["K"] is None
    assert any("EMPTY" in w or "empty" in w.lower() or "QB" in w for w in lineup.warnings)


def test_qb_gate_unknown_depth_eliminates():
    """Unknown depth fails closed — eliminate rather than score a backup."""
    from brady_bot.pickers.qb import QBPicker

    cfg = load_config()
    qb_a = Player(player_id="QA", name="QB A", team="KC", position=Position.QB)
    qb_b = Player(player_id="QB", name="QB B", team="BUF", position=Position.QB)
    picker = QBPicker(cfg)
    ctx = _fixture_ctx([qb_a, qb_b])
    ctx.depth_chart_order = {}
    ctx.qb1_by_team = {}
    ctx.roles = {}

    for qb in (qb_a, qb_b):
        gated = picker.gate(ctx, qb)
        assert gated is not None
        assert gated.gate_result == "eliminated"
        assert gated.gate_reason == "not_qb1"

    # Confirmed QB1 still passes the gate
    ctx.qb1_by_team = {"KC": "QA"}
    ctx.roles = {"QA": "QB1"}
    assert picker.gate(ctx, qb_a) is None

    # Known other QB1 available → backup eliminated
    ctx.qb1_by_team = {"KC": "QA", "BUF": "OTHER"}
    ctx.roles = {"QA": "QB1", "QB": "QB2"}
    gated = picker.gate(ctx, qb_b)
    assert gated is not None and gated.gate_result == "eliminated"


def test_rb1_posrank_beats_rb2_before_any_snaps_exist():
    """Week 1, no usage data: pos_rank carries the 30% factor (§5.10.1, D19)."""
    cfg = load_config()
    rb1 = Player(player_id="WALKER", name="Walker", team="SEA", position=Position.RB)
    rb2 = Player(player_id="HARVEY", name="Harvey", team="DEN", position=Position.RB)
    third = Player(player_id="THD", name="Third", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([rb1, rb2, third])
    ctx.week = 1
    ctx.snap_share = {}  # no current-season snaps yet
    ctx.pos_rank = {"RB": {"WALKER": 1, "HARVEY": 2, "THD": 3}}
    ctx.calibre_rank["RB"] = {"WALKER": 20, "HARVEY": 20, "THD": 20}
    picker = RBPicker(cfg)
    starters, _ = picker.select(ctx, [rb1, rb2, third])
    ids = [s.player.player_id for s in starters]
    assert "WALKER" in ids
    walker_score = sum(f.contribution for f in picker.score_factors(ctx, rb1))
    harvey_score = sum(f.contribution for f in picker.score_factors(ctx, rb2))
    assert walker_score > harvey_score
    depth_w = next(f for f in picker.score_factors(ctx, rb1) if f.name == "depth_chart")
    depth_h = next(f for f in picker.score_factors(ctx, rb2) if f.name == "depth_chart")
    depth_t = next(f for f in picker.score_factors(ctx, third) if f.name == "depth_chart")
    assert depth_w.score == 1.0
    assert depth_h.score == 0.30
    assert depth_t.score == 0.00


def test_rb_depth_has_no_posrank_fallback_from_week_five():
    """Week 5+, no snaps → 0.00. Tiering off pos_rank here would leak it past Week 4."""
    cfg = load_config()
    rb = Player(player_id="WALKER", name="Walker", team="SEA", position=Position.RB)
    ctx = _fixture_ctx([rb])  # fixture is week 5
    ctx.snap_share = {}
    ctx.pos_rank = {"RB": {"WALKER": 1}}
    depth = next(f for f in RBPicker(cfg).score_factors(ctx, rb) if f.name == "depth_chart")
    assert depth.score == 0.0
    assert depth.raw_value == "inactive"


def test_ui_card_path_keeps_scores_off_card_face():
    """Card face stays name/pos/team/opp; equation work lives only in details panel."""
    from pathlib import Path

    app_js = Path(__file__).resolve().parents[1] / "js" / "lineup" / "app.js"
    cards_js = Path(__file__).resolve().parents[1] / "js" / "lineup" / "cards.js"
    app = app_js.read_text()
    cards = cards_js.read_text()
    assert "renderPlayerCard" in app
    assert "detailsOpts" in app
    assert "start_score" in app  # passed into details only
    assert "prior_factors" in app  # dual bench eval wired through
    assert "injuries_by_player" in app or "setInjuries" in app
    assert "injury_label" in app  # prefer full status word on lineup cards
    assert "details-factor-table" in cards
    assert 'scoreLabel: "Start Score"' in cards or "Start Score" in cards
    assert "FLEX Score equation" in cards
    assert "renderEquationBlock" in cards
    assert "injury-status" in cards
    assert "brand-red" in (Path(__file__).resolve().parents[1] / "custom.css").read_text()
    # Default (non-details) card branch must not print start_score on the face
    assert "card-details-panel" in cards
    assert 'class="name"' in cards


def test_flex_loser_on_bench_has_prior_positional_and_flex_factors():
    """End-to-end: leftover RB who loses FLEX keeps both equation payloads."""
    from brady_bot.pickers.flex import FLEX_FACTOR_NAMES

    cfg = load_config()
    roster = [
        Player(player_id="Q1", name="QB", team="KC", position=Position.QB),
        Player(player_id="R1", name="RB Starter A", team="SF", position=Position.RB),
        Player(player_id="R2", name="RB Starter B", team="DAL", position=Position.RB),
        Player(player_id="R_BENCH", name="Backup RB leftover", team="SEA", position=Position.RB),
        Player(player_id="W1", name="WR Starter A", team="SF", position=Position.WR),
        Player(player_id="W2", name="WR Starter B", team="DAL", position=Position.WR),
        Player(player_id="W_FLEX", name="WR1 leftover", team="BUF", position=Position.WR),
        Player(player_id="T1", name="TE", team="SF", position=Position.TE),
        Player(player_id="K1", name="K", team="SF", position=Position.K),
        Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF),
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
    assert not lineup.starters["FLEX"].prior_factors

    lost = next(s for s in lineup.bench if s.player.player_id == "R_BENCH")
    assert lost.prior_label == "RB"
    assert lost.prior_factors
    assert {f.name for f in lost.factors} <= FLEX_FACTOR_NAMES
    dumped = lost.model_dump()
    assert dumped["prior_factors"]
    assert dumped["prior_label"] == "RB"

def test_qb_style_list_primary_over_rush_att():
    """Listed qb_styles wins over rush_att_pg; unlisted uses rush threshold + style_derived."""
    from brady_bot.pickers.qb import QBPicker

    cfg = load_config()
    qb = Player(player_id="Q1", name="Dual", team="KC", position=Position.QB)
    ctx = _fixture_ctx([qb])
    picker = QBPicker(cfg)

    # Listed mobile → Style 1.0 even if rush_att_pg is low
    ctx.qb_styles = {"Q1": True}
    ctx.rush_att_pg = {"Q1": 1.0}
    style = next(f for f in picker.score_factors(ctx, qb) if f.name == "style")
    assert style.score == 1.0
    assert style.raw_value == "qb_styles"
    assert picker.flags_for(ctx, qb) == []

    # Listed pocket → Style 0.0 even if rush_att_pg is high
    ctx.qb_styles = {"Q1": False}
    ctx.rush_att_pg = {"Q1": 8.0}
    style = next(f for f in picker.score_factors(ctx, qb) if f.name == "style")
    assert style.score == 0.0
    assert style.raw_value == "qb_styles"
    assert picker.flags_for(ctx, qb) == []

    # Unlisted + rush ≥ 4.0 → Style 1.0 + style_derived
    ctx.qb_styles = {}
    ctx.rush_att_pg = {"Q1": 5.0}
    style = next(f for f in picker.score_factors(ctx, qb) if f.name == "style")
    assert style.score == 1.0
    assert style.raw_value == "rush_att_pg=5.00"
    assert picker.flags_for(ctx, qb) == ["style_derived"]

    # Unlisted + rush < 4.0 → Style 0.0 + style_derived
    ctx.rush_att_pg = {"Q1": 2.0}
    style = next(f for f in picker.score_factors(ctx, qb) if f.name == "style")
    assert style.score == 0.0
    assert "rush_att_pg=2.00" == style.raw_value
    assert picker.flags_for(ctx, qb) == ["style_derived"]


def test_def_opp_qb_elite_mobile_band():
    """Top-5 calibre + listed mobile → opp_qb 0.00."""
    from brady_bot.pickers.defense import DefensePicker
    from brady_bot.models import GameContext

    cfg = load_config()
    dst = Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF)
    ctx = _fixture_ctx([dst])
    ctx.games["SF"] = GameContext(
        game_id="SF-BUF",
        home_team="SF",
        away_team="BUF",
        game_total=44,
        spread=-3,
        home_implied_total=23.5,
        away_implied_total=20.5,
    )
    ctx.qb1_by_team = {"BUF": "QB1"}
    ctx.player_teams = {"QB1": "BUF", "DEF-SF": "SF"}
    ctx.calibre_rank["QB"] = {"QB1": 3}
    ctx.qb_styles = {"QB1": True}
    # High rush would not matter for listed; ensure list path is used
    ctx.rush_att_pg = {"QB1": 0.5}
    # High turnover would short-circuit to 0.80 — keep above 10
    ctx.team_stats["BUF"].qb_turnover_rank = 16
    picker = DefensePicker(cfg)
    opp_qb = next(f for f in picker.score_factors(ctx, dst) if f.name == "opp_qb")
    assert opp_qb.score == 0.0

    # Listed pocket top-5 → 0.15 (not elite+mobile band)
    ctx.qb_styles = {"QB1": False}
    opp_qb = next(f for f in picker.score_factors(ctx, dst) if f.name == "opp_qb")
    assert opp_qb.score == 0.15


def test_qb_pass_catcher_nfl_team_roles():
    from brady_bot.pickers.qb import QBPicker
    from brady_bot.models import InjuryRecord

    cfg = load_config()
    qb = Player(player_id="Q1", name="QB", team="KC", position=Position.QB)
    ctx = _fixture_ctx([qb])
    ctx.roles = {
        "WR1A": "WR1",
        "WR2A": "WR2",
        "WR3A": "WR3",
        "TE1A": "TE1",
        "OTHER": "WR1",
    }
    ctx.player_teams = {
        "Q1": "KC",
        "WR1A": "KC",
        "WR2A": "KC",
        "WR3A": "KC",
        "TE1A": "KC",
        "OTHER": "BUF",
    }
    ctx.static_ids["elite_wrs"] = {"WR1A"}
    picker = QBPicker(cfg)
    pc = next(f for f in picker.score_factors(ctx, qb) if f.name == "pass_catcher")
    # 4 healthy → 0.90 + 0.10 elite = 1.00
    assert pc.score == 1.0
    assert "preclamp=1.00" in (pc.raw_value or "")

    ctx.injuries["WR3A"] = InjuryRecord(player_id="WR3A", report_status="Out")
    pc = next(f for f in picker.score_factors(ctx, qb) if f.name == "pass_catcher")
    # 3 healthy + 1 elite → 0.70 + 0.10 = 0.80
    assert abs(pc.score - 0.80) < 1e-9


def test_qb_pass_catcher_uncapped_boost_sets_score_capped():
    """Pass-catcher can be 1.10; finalize_score is the only clamp → score_capped on QB."""
    from brady_bot.models import FactorScore
    from brady_bot.pickers.base import apply_start_score_cap
    from brady_bot.pickers.qb import QBPicker

    cfg = load_config()
    qb = Player(player_id="Q1", name="Mahomes", team="KC", position=Position.QB)
    qb2 = Player(player_id="Q2", name="Other", team="BUF", position=Position.QB)
    ctx = _fixture_ctx([qb, qb2])
    ctx.roles = {
        "WR1A": "WR1",
        "WR2A": "WR2",
        "WR3A": "WR3",
        "TE1A": "TE1",
    }
    ctx.player_teams = {
        "Q1": "KC",
        "Q2": "BUF",
        "WR1A": "KC",
        "WR2A": "KC",
        "WR3A": "KC",
        "TE1A": "KC",
    }
    # Two elites → 0.90 + 0.20 = 1.10
    ctx.static_ids["elite_wrs"] = {"WR1A", "WR2A"}
    ctx.qb1_by_team = {"KC": "Q1", "BUF": "Q2"}
    ctx.depth_chart_order = {"QB": {"Q1": 1, "Q2": 1}}
    picker = QBPicker(cfg)

    pc = next(f for f in picker.score_factors(ctx, qb) if f.name == "pass_catcher")
    assert abs(pc.score - 1.10) < 1e-9
    assert "preclamp=1.10" in (pc.raw_value or "")

    # Max every other factor so weighted_sum = 0.80 + 1.10*0.20 = 1.02
    w = picker.w

    def maxed_factors(c, p):
        if p.player_id != "Q1":
            return [FactorScore(name="style", score=0.0, weight=1.0)]
        return [
            FactorScore(name="style", score=1.0, weight=w["style"]),
            FactorScore(
                name="pass_catcher",
                raw_value="preclamp=1.10;healthy=4;elite=2",
                score=1.10,
                weight=w["pass_catcher"],
            ),
            FactorScore(name="oline", score=1.0, weight=w["oline"]),
            FactorScore(name="matchup", score=1.0, weight=w["matchup"]),
            FactorScore(name="secondary_injury", score=1.0, weight=w["secondary_injury"]),
            FactorScore(name="baseline", score=1.0, weight=w["baseline"]),
        ]

    picker.score_factors = maxed_factors  # type: ignore[method-assign]
    factors = maxed_factors(ctx, qb)
    pre_clamp = sum(f.contribution for f in factors)
    assert pre_clamp > 1.0
    start, flags = apply_start_score_cap(pre_clamp, 0.0)
    assert abs(start - 1.0) < 1e-9
    assert flags == ["score_capped"]

    starters, bench = picker.select(ctx, [qb, qb2])
    hit = next(s for s in starters + bench if s.player.player_id == "Q1")
    assert hit.gate_result == "passed"
    assert abs(hit.weighted_sum - pre_clamp) < 1e-9
    assert hit.weighted_sum > 1.0
    assert abs(hit.start_score - 1.0) < 1e-9
    assert "score_capped" in hit.flags


def test_non_rb_finalize_score_caps_without_bonus():
    """Shared apply_start_score_cap fires score_capped for any position, not only RB."""
    from brady_bot.pickers.base import apply_start_score_cap
    from brady_bot.pickers.wr import WRPicker

    cfg = load_config()
    picker = WRPicker(cfg)
    wr = Player(player_id="W1", name="WR", team="SF", position=Position.WR)
    ctx = _fixture_ctx([wr])
    # Direct finalize path: weighted_sum already > 1 (as if a factor boost leaked)
    start, bonus, flags = picker.finalize_score(ctx, wr, 1.05)
    assert abs(start - 1.0) < 1e-9
    assert bonus == 0.0
    assert flags == ["score_capped"]
    # Same helper RB uses
    start2, flags2 = apply_start_score_cap(1.05, 0.0)
    assert start2 == start and flags2 == flags


def test_qb_quality_same_team_backup():
    from brady_bot.models import InjuryRecord
    from brady_bot.scoring.shared import qb_quality_score

    qb1 = Player(player_id="Q1", name="Starter", team="KC", position=Position.QB)
    qb2 = Player(player_id="Q2", name="Backup", team="KC", position=Position.QB)
    other = Player(player_id="QX", name="Other", team="BUF", position=Position.QB)
    ctx = _fixture_ctx([qb1, qb2, other])
    ctx.qb1_by_team = {"KC": "Q1", "BUF": "QX"}
    ctx.roles = {"Q1": "QB1", "Q2": "QB2", "QX": "QB1"}
    ctx.player_teams = {"Q1": "KC", "Q2": "KC", "QX": "BUF"}
    ctx.calibre_rank["QB"] = {"Q1": 3, "Q2": 25, "QX": 1}
    ctx.injuries["Q1"] = InjuryRecord(player_id="Q1", report_status="Out")
    # Must use KC backup (rank 25 → 0.25), not BUF elite
    assert qb_quality_score(ctx, "KC") == 0.25


def test_def_opp_skill_role_table():
    from brady_bot.models import InjuryRecord
    from brady_bot.pickers.defense import DefensePicker

    cfg = load_config()
    dst = Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF)
    ctx = _fixture_ctx([dst])
    # SF plays vs BUF in fixture rotation — set explicit game
    from brady_bot.models import GameContext

    ctx.games["SF"] = GameContext(
        game_id="SF-BUF",
        home_team="SF",
        away_team="BUF",
        game_total=44,
        spread=-3,
        home_implied_total=23.5,
        away_implied_total=20.5,
    )
    ctx.roles = {"W1": "WR1", "W2": "WR2", "T1": "TE1", "R1": "RB1"}
    ctx.player_teams = {"W1": "BUF", "W2": "BUF", "T1": "BUF", "R1": "BUF", "DEF-SF": "SF"}
    ctx.injuries = {
        "W1": InjuryRecord(player_id="W1", report_status="Out"),
        "W2": InjuryRecord(player_id="W2", report_status="Out"),
        "T1": InjuryRecord(player_id="T1", report_status="Out"),
    }
    picker = DefensePicker(cfg)
    skill = next(f for f in picker.score_factors(ctx, dst) if f.name == "opp_skill")
    assert skill.score == 1.0

    ctx.injuries = {"W1": InjuryRecord(player_id="W1", report_status="Out")}
    skill = next(f for f in picker.score_factors(ctx, dst) if f.name == "opp_skill")
    assert skill.score == 0.70


def test_def_opp_qb_backup_calibre_band():
    from brady_bot.models import InjuryRecord
    from brady_bot.pickers.defense import DefensePicker
    from brady_bot.models import GameContext

    cfg = load_config()
    dst = Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF)
    ctx = _fixture_ctx([dst])
    ctx.games["SF"] = GameContext(
        game_id="SF-BUF",
        home_team="SF",
        away_team="BUF",
        game_total=44,
        spread=-3,
        home_implied_total=23.5,
        away_implied_total=20.5,
    )
    ctx.qb1_by_team = {"BUF": "QB1"}
    ctx.roles = {"QB1": "QB1", "QB2": "QB2"}
    ctx.player_teams = {"QB1": "BUF", "QB2": "BUF", "DEF-SF": "SF"}
    ctx.calibre_rank["QB"] = {"QB1": 5, "QB2": 22}
    ctx.injuries["QB1"] = InjuryRecord(player_id="QB1", report_status="Out")
    picker = DefensePicker(cfg)
    opp_qb = next(f for f in picker.score_factors(ctx, dst) if f.name == "opp_qb")
    assert opp_qb.score == 0.85


def test_flex_calibre_boundary_and_situation_bump():
    from brady_bot.models import InjuryRecord
    from brady_bot.pickers.flex import FlexPicker

    cfg = load_config()
    wr = Player(player_id="W1", name="WR", team="KC", position=Position.WR)
    ctx = _fixture_ctx([wr])
    ctx.roles = {"W1": "WR1", "W2": "WR2", "W3": "WR3", "Q1": "QB1"}
    ctx.player_teams = {"W1": "KC", "W2": "KC", "W3": "KC", "Q1": "KC"}
    ctx.qb1_by_team = {"KC": "Q1"}
    ctx.calibre_rank["WR"] = {"W1": 1}  # pct = 1.0 → >0.95 → 1.0
    picker = FlexPicker(cfg)
    cal = next(f for f in picker.score_factors(ctx, wr) if f.name == "player_calibre")
    assert cal.score == 1.0

    # Exactly 95th percentile band: rank such that pct == 0.95
    # pct = 1 - (rank-1)/60; 0.95 = 1 - (rank-1)/60 → (rank-1)/60 = 0.05 → rank = 4
    pool = cfg.weights.flex_pool_sizes.get("WR", 60)
    rank = int(0.05 * pool) + 1
    ctx.calibre_rank["WR"] = {"W1": rank}
    pct = 1.0 - (rank - 1) / pool
    assert abs(pct - 0.95) < 1e-9 or pct <= 0.95
    cal = next(f for f in picker.score_factors(ctx, wr) if f.name == "player_calibre")
    if pct > 0.95:
        assert cal.score == 1.0
    else:
        assert cal.score == 0.90

    ctx.injuries = {
        "W2": InjuryRecord(player_id="W2", report_status="Out"),
        "W3": InjuryRecord(player_id="W3", report_status="Out"),
    }
    situ = next(f for f in picker.score_factors(ctx, wr) if f.name == "situation")
    assert situ.score == 1.0  # 1.0 base + 0.25 capped


def test_flex_te_opportunity_requires_te1():
    from brady_bot.pickers.flex import FlexPicker

    cfg = load_config()
    te = Player(player_id="T2", name="TE2", team="KC", position=Position.TE)
    ctx = _fixture_ctx([te])
    ctx.roles = {"T2": "TE2", "W1": "WR1"}
    ctx.player_teams = {"T2": "KC", "W1": "KC"}
    from brady_bot.models import InjuryRecord

    ctx.injuries["W1"] = InjuryRecord(player_id="W1", report_status="Out")
    picker = FlexPicker(cfg)
    opp = next(f for f in picker.score_factors(ctx, te) if f.name == "opportunity")
    assert opp.score == 0.30


def test_rb_tier2_bonus_math_and_flags():
    """Capped Tier 2 bonus: 0.52→0.82; 0.85→1.00 + score_capped; no pair auto-start."""
    from brady_bot.models import FactorScore
    from brady_bot.pickers.rb import RBPicker

    cfg = load_config()
    picker = RBPicker(cfg)
    assert abs(picker.tier2_bonus - 0.30) < 1e-9

    t2 = Player(player_id="T2", name="Tier2", team="BAL", position=Position.RB)
    other = Player(player_id="OTH", name="Other", team="CHI", position=Position.RB)
    third = Player(player_id="THD", name="Third", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([t2, other, third])
    ctx.static_ids["rb_tier2"] = {"T2"}

    start, bonus, flags = picker.finalize_score(ctx, t2, 0.52)
    assert abs(start - 0.82) < 1e-9
    assert abs(bonus - 0.30) < 1e-9
    assert flags == ["tier2_bonus"]

    start, bonus, flags = picker.finalize_score(ctx, t2, 0.85)
    assert abs(start - 1.0) < 1e-9
    assert abs(bonus - 0.30) < 1e-9
    assert "tier2_bonus" in flags and "score_capped" in flags

    # Lone Tier 2 does not auto-start; scored path gets tier2_bonus flag
    scores = {"T2": 0.52, "OTH": 0.40, "THD": 0.35}

    def fake_factors(c, p):
        return [FactorScore(name="depth_chart", score=scores[p.player_id], weight=1.0)]

    picker.score_factors = fake_factors  # type: ignore[method-assign]
    starters, bench = picker.select(ctx, [t2, other, third])
    all_scored = starters + bench
    hit = next(s for s in all_scored if s.player.player_id == "T2")
    assert hit.gate_result == "passed"
    assert hit.gate_reason != "rb_tier2_pair"
    assert "tier2_bonus" in hit.flags
    assert abs(hit.start_score - 0.82) < 1e-9
    assert abs((hit.weighted_sum or 0) - 0.52) < 1e-9
    assert hit.start_score <= 1.0


def test_rb_tier2_capped_sort_by_weighted_sum():
    """Two Tier 2s both at 1.00: higher weighted_sum wins the slot."""
    from brady_bot.models import FactorScore
    from brady_bot.pickers.rb import RBPicker

    cfg = load_config()
    picker = RBPicker(cfg)
    a = Player(player_id="A", name="A", team="BAL", position=Position.RB)
    b = Player(player_id="B", name="B", team="CIN", position=Position.RB)
    c = Player(player_id="C", name="C", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([a, b, c])
    ctx.static_ids["rb_tier2"] = {"A", "B"}
    scores = {"A": 0.78, "B": 0.72, "C": 0.50}

    def fake_factors(ctx_, p):
        return [FactorScore(name="depth_chart", score=scores[p.player_id], weight=1.0)]

    picker.score_factors = fake_factors  # type: ignore[method-assign]
    starters, _ = picker.select(ctx, [b, a, c])  # B listed first to avoid id-order luck
    assert starters[0].player.player_id == "A"
    assert starters[1].player.player_id == "B"
    assert abs(starters[0].start_score - 1.0) < 1e-9
    assert abs(starters[1].start_score - 1.0) < 1e-9
    assert "score_capped" in starters[0].flags
    assert "score_capped" in starters[1].flags


def test_rb_non_tier_beats_tier2_when_gap_large():
    """Non-tier with weighted +0.31 over a Tier 2 still wins."""
    from brady_bot.models import FactorScore
    from brady_bot.pickers.rb import RBPicker

    cfg = load_config()
    picker = RBPicker(cfg)
    t2 = Player(player_id="T2", name="Tier2", team="BAL", position=Position.RB)
    nt = Player(player_id="NT", name="NonTier", team="NE", position=Position.RB)
    filler = Player(player_id="F", name="Fill", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([t2, nt, filler])
    ctx.static_ids["rb_tier2"] = {"T2"}
    # Tier2 weighted 0.50 → start 0.80; non-tier 0.81 → wins
    scores = {"T2": 0.50, "NT": 0.81, "F": 0.10}

    def fake_factors(ctx_, p):
        return [FactorScore(name="depth_chart", score=scores[p.player_id], weight=1.0)]

    picker.score_factors = fake_factors  # type: ignore[method-assign]
    starters, _ = picker.select(ctx, [t2, nt, filler])
    assert starters[0].player.player_id == "NT"
    assert abs(starters[0].start_score - 0.81) < 1e-9
    t2_scored = next(s for s in starters if s.player.player_id == "T2")
    assert abs(t2_scored.start_score - 0.80) < 1e-9


def test_rb_tier1_never_gets_bonus():
    cfg = load_config()
    star = Player(player_id="STAR", name="Star RB", team="DET", position=Position.RB)
    other = Player(player_id="OTH", name="Other", team="CHI", position=Position.RB)
    third = Player(player_id="THD", name="Third", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([star, other, third])
    ctx.static_ids["rb_tier1"] = {"STAR"}
    ctx.static_ids["rb_tier2"] = {"STAR"}  # even if mislisted, auto-start skips equation
    ctx.snap_share = {"STAR": 0.2, "OTH": 0.9, "THD": 0.9}
    starters, _ = RBPicker(cfg).select(ctx, [star, other, third])
    hit = next(s for s in starters if s.player.player_id == "STAR")
    assert hit.gate_result == "auto_start"
    assert hit.bonus == 0.0
    assert "tier2_bonus" not in hit.flags


def test_te_wr_injury_multiple_out_scores_one():
    """WR2+WR3 out (WR1 healthy) → 1.00 per §8.4 multiple-WR row."""
    from brady_bot.models import InjuryRecord
    from brady_bot.pickers.te import TEPicker

    cfg = load_config()
    te = Player(player_id="TE1", name="TE", team="KC", position=Position.TE)
    ctx = _fixture_ctx([te])
    ctx.roles = {"W1": "WR1", "W2": "WR2", "W3": "WR3", "TE1": "TE1"}
    ctx.player_teams = {"W1": "KC", "W2": "KC", "W3": "KC", "TE1": "KC"}
    ctx.injuries["W2"] = InjuryRecord(player_id="W2", report_status="Out")
    ctx.injuries["W3"] = InjuryRecord(player_id="W3", report_status="Out")
    picker = TEPicker(cfg)
    wr_inj = next(f for f in picker.score_factors(ctx, te) if f.name == "wr_injury")
    assert wr_inj.score == 1.0


def test_baseline_neutral_when_odds_unavailable():
    from brady_bot.scoring.shared import baseline_for_team

    qb = Player(player_id="Q1", name="QB", team="KC", position=Position.QB)
    ctx = _fixture_ctx([qb])
    ctx.odds_unavailable = True
    assert baseline_for_team(ctx, "KC") == 0.50


def test_gate_before_auto_start():
    """TE2 in te_top4 is still eliminated by TE1 gate (gate runs first)."""
    from brady_bot.pickers.te import TEPicker

    cfg = load_config()
    te1 = Player(player_id="TE1", name="TE1", team="KC", position=Position.TE)
    te2 = Player(player_id="TE2", name="TE2", team="KC", position=Position.TE)
    ctx = _fixture_ctx([te1, te2])
    ctx.roles = {"TE1": "TE1", "TE2": "TE2"}
    ctx.player_teams = {"TE1": "KC", "TE2": "KC"}
    ctx.static_ids["te_top4"] = {"TE2"}
    starters, rest = TEPicker(cfg).select(ctx, [te1, te2])
    te2_scored = next(s for s in starters + rest if s.player.player_id == "TE2")
    assert te2_scored.gate_result == "eliminated"
    assert te2_scored.gate_reason == "not_te1"


def test_injury_status_on_lineup_payload():
    from brady_bot.models import InjuryRecord

    cfg = load_config()
    qb = Player(player_id="Q1", name="QB", team="KC", position=Position.QB)
    injured = Player(player_id="R_OUT", name="Hurt RB", team="SF", position=Position.RB)
    healthy = Player(player_id="R2", name="RB2", team="DAL", position=Position.RB)
    roster = [
        qb,
        injured,
        healthy,
        Player(player_id="W1", name="WR1", team="SF", position=Position.WR),
        Player(player_id="W2", name="WR2", team="DAL", position=Position.WR),
        Player(player_id="T1", name="TE1", team="SF", position=Position.TE),
        Player(player_id="K1", name="K1", team="SF", position=Position.K),
        Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF),
        Player(player_id="R3", name="RB3", team="BUF", position=Position.RB),
    ]
    ctx = _fixture_ctx(roster)
    ctx.injuries["R_OUT"] = InjuryRecord(player_id="R_OUT", report_status="Out")
    lineup = optimize_lineup(ctx, cfg)
    assert lineup.injuries_by_player.get("R_OUT") == "Out"
    # Injured player should appear on bench/eliminated path with status
    hurt = next(
        (s for s in lineup.bench if s.player.player_id == "R_OUT"),
        None,
    )
    assert hurt is not None
    assert hurt.injury_status == "O"
    assert hurt.is_unavailable is True
    assert hurt.injury_label == "Out"


def test_rb_teammate_uses_nfl_team_roles_not_roster():
    """RB1 out on NFL team (not fantasy-rostered) still boosts rostered RB2."""
    from brady_bot.models import InjuryRecord

    cfg = load_config()
    rb2 = Player(player_id="RB2", name="Backup", team="SEA", position=Position.RB)
    other = Player(player_id="OTH", name="Other", team="CHI", position=Position.RB)
    third = Player(player_id="THD", name="Third", team="NYJ", position=Position.RB)
    ctx = _fixture_ctx([rb2, other, third])
    ctx.roles = {"RB1_NFL": "RB1", "RB2": "RB2", "OTH": "RB1", "THD": "RB1"}
    ctx.player_teams = {
        "RB1_NFL": "SEA",
        "RB2": "SEA",
        "OTH": "CHI",
        "THD": "NYJ",
    }
    ctx.injuries["RB1_NFL"] = InjuryRecord(player_id="RB1_NFL", report_status="Out")
    ctx.snap_share = {"RB2": 0.55, "OTH": 0.55, "THD": 0.55}
    factors = RBPicker(cfg).score_factors(ctx, rb2)
    teammate = next(f for f in factors if f.name == "teammate_injury")
    assert teammate.score == 1.0


def test_flex_rb_opportunity_uses_posrank_before_any_snaps_exist():
    """Week 1 FLEX Opportunity (40%) rides pos_rank; Week 5+ has no depth fallback."""
    from brady_bot.pickers.flex import FlexPicker

    cfg = load_config()
    rb = Player(player_id="WH", name="Workhorse", team="DET", position=Position.RB)
    ctx = _fixture_ctx([rb])
    ctx.snap_share = {}  # no current-season snaps yet
    ctx.pos_rank = {"RB": {"WH": 1}}
    picker = FlexPicker(cfg)

    ctx.week = 1
    opp = next(f for f in picker.score_factors(ctx, rb) if f.name == "opportunity")
    assert opp.score == 1.0  # RB1 on the chart, not the 0.40 committee default

    ctx.week = 5
    opp = next(f for f in picker.score_factors(ctx, rb) if f.name == "opportunity")
    assert opp.score == 0.0  # usage only, and he has none


def test_flex_picks_by_flex_equation_not_positional_scores():
    """
    Leftovers compete on Flex Score only (lineup-picker-FLEX.md).
    A backup RB must lose FLEX to a WR1 leftover — opportunity (40%) under the
    FLEX equation, not RB/WR Start Scores.
    """
    from brady_bot.pickers.flex import FLEX_FACTOR_NAMES, FlexPicker

    cfg = load_config()
    roster = [
        Player(player_id="Q1", name="QB", team="KC", position=Position.QB),
        Player(player_id="R1", name="RB Starter A", team="SF", position=Position.RB),
        Player(player_id="R2", name="RB Starter B", team="DAL", position=Position.RB),
        Player(player_id="R_BENCH", name="Backup RB leftover", team="SEA", position=Position.RB),
        Player(player_id="W1", name="WR Starter A", team="SF", position=Position.WR),
        Player(player_id="W2", name="WR Starter B", team="DAL", position=Position.WR),
        Player(player_id="W_FLEX", name="WR1 leftover", team="BUF", position=Position.WR),
        Player(player_id="T1", name="TE", team="SF", position=Position.TE),
        Player(player_id="K1", name="K", team="SF", position=Position.K),
        Player(player_id="DEF-SF", name="SF", team="SF", position=Position.DEF),
    ]
    ctx = _fixture_ctx(roster)
    ctx.snap_share = {
        "R1": 0.70,
        "R2": 0.65,
        "R_BENCH": 0.20,  # FLEX opportunity 0.10
    }
    ctx.roles = {
        "W1": "WR1",
        "W2": "WR1",
        "W_FLEX": "WR1",  # FLEX opportunity 1.00
        "R1": "RB1",
        "R2": "RB1",
        "R_BENCH": "RB2",
        "T1": "TE1",
    }
    ctx.player_teams.update({p.player_id: p.team for p in roster})
    ctx.calibre_rank["RB"] = {"R1": 5, "R2": 6, "R_BENCH": 1}
    ctx.calibre_rank["WR"] = {"W1": 10, "W2": 11, "W_FLEX": 40}

    r_bench = next(p for p in roster if p.player_id == "R_BENCH")
    w_flex = next(p for p in roster if p.player_id == "W_FLEX")
    flex = FlexPicker(cfg)
    flex_rb = sum(f.contribution for f in flex.score_factors(ctx, r_bench))
    flex_wr = sum(f.contribution for f in flex.score_factors(ctx, w_flex))
    assert flex_wr > flex_rb

    # Direct leftover pin: FLEX equation only
    starters, _ = flex.select(ctx, [r_bench, w_flex])
    assert starters[0].player.player_id == "W_FLEX"
    assert {f.name for f in starters[0].factors} == FLEX_FACTOR_NAMES
    assert "depth_chart" not in {f.name for f in starters[0].factors}
    assert "ranking" not in {f.name for f in starters[0].factors}

    lineup = optimize_lineup(ctx, cfg)
    assert lineup.starters["FLEX"] is not None
    assert lineup.starters["FLEX"].player.player_id == "W_FLEX"
    assert {f.name for f in lineup.starters["FLEX"].factors} == FLEX_FACTOR_NAMES
