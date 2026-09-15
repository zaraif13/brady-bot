"""Depth chart position scoring — tech spec §5.9a / §5.10.1 / §5.10.2, §13.2 tests.

Covers the required tests in lineup-picker-DEPTH-CHART.md: Week 1 exact scores, the
Week 3 blend arithmetic, inertness from Week 5, the RB3 floor, missing depth entries,
pinning, the FLEX cross-position comparison, and depth override precedence.

The §5.10.2 per-game denominator rule survives the committee retirement and is tested
at the bottom of this file.
"""
from __future__ import annotations

import polars as pl
import pytest

from brady_bot.config import ConfigError, _load_depth_overrides, load_config
from brady_bot.derive.depth import (
    NO_DEPTH_ENTRY,
    derive_depth_chart_order,
    derive_pos_ranks,
    posrank_active,
    posrank_score,
    posrank_weights,
)
from brady_bot.derive.roles import snap_shares_by_team, target_shares_by_team
from brady_bot.models import GameContext, Player, Position, TeamStats, WeekContext
from brady_bot.pickers.flex import FlexPicker
from brady_bot.pickers.rb import RBPicker
from brady_bot.pickers.wr import WRPicker
from brady_bot.scoring.shared import snap_share_score

TEAMS = ("KC", "SEA", "DEN", "LAC")


def _ctx(
    roster: list[Player],
    *,
    week: int,
    pos_rank: dict[str, dict[str, int]] | None = None,
    snap_share: dict[str, float] | None = None,
    roles: dict[str, str] | None = None,
    roles_current: dict[str, str] | None = None,
    no_depth_entry: list[str] | None = None,
) -> WeekContext:
    teams = sorted({p.team for p in roster} | set(TEAMS))
    games = {}
    for i, t in enumerate(teams):
        games[t] = GameContext(
            game_id=f"{t}-g",
            home_team=t,
            away_team=teams[(i + 1) % len(teams)],
            game_total=44,
            home_implied_total=22,
            away_implied_total=22,
        )
    neutral = {t: 0.0 for t in teams}
    return WeekContext(
        season=2026,
        week=week,
        fetched_at="2026-09-10T00:00:00Z",
        roster=roster,
        team_stats={
            t: TeamStats(
                team=t,
                season=2026,
                through_week=max(week - 1, 1),
                offense_rank=16,
                total_defense_rank=16,
                scoring_efficiency_rank=16,
                defense_calibre_rank=16,
                qb_turnover_rank=16,
            )
            for t in teams
        },
        games=games,
        adj_fpa={"QB": neutral, "RB": neutral, "WR": neutral, "TE": neutral},
        calibre_rank={"RB": {}, "WR": {}, "TE": {}, "QB": {}},
        roles=roles or {},
        roles_current=roles_current if roles_current is not None else (roles or {}),
        player_teams={p.player_id: p.team for p in roster},
        snap_share=snap_share or {},
        pos_rank=pos_rank or {"RB": {}, "WR": {}, "TE": {}},
        no_depth_entry=no_depth_entry or [],
        injury_counts={t: {"OL": 0, "FRONT_SEVEN_INTERIOR": 0, "SECONDARY": 0} for t in teams},
        depth_chart_order={},
        qb1_by_team={},
        static_ids={"rb_tier1": set(), "rb_tier2": set(), "wr_top5": set(), "elite_tes": set()},
        oline_ranks={t: 16 for t in teams},
        blended=week <= 4,
    )


def _depth(picker, ctx: WeekContext, player: Player):
    return next(f for f in picker.score_factors(ctx, player) if f.name == "depth_chart")


def _opportunity(picker, ctx: WeekContext, player: Player):
    return next(f for f in picker.score_factors(ctx, player) if f.name == "opportunity")


# ---------------------------------------------------------------------------
# §5.9a — the lookup tables
# ---------------------------------------------------------------------------


def test_posrank_score_tables_match_the_spec():
    assert posrank_score(1, "RB") == 1.00
    assert posrank_score(2, "RB") == 0.30
    assert posrank_score(1, "WR") == 1.00
    assert posrank_score(2, "WR") == 0.60
    assert posrank_score(3, "WR") == 0.25
    assert posrank_score(1, "TE") == 1.00
    assert posrank_score(2, "TE") == 0.00


def test_rb3_scores_zero_not_an_interpolation():
    """§13.2 / D20 — RB3 is 0.00, not a midpoint between RB2's 0.30 and nothing."""
    assert posrank_score(3, "RB") == 0.00
    assert posrank_score(4, "RB") == 0.00
    # The interpolation an implementation might reach for by accident.
    assert posrank_score(3, "RB") != pytest.approx(0.15)


def test_scores_are_in_range_for_every_rank_and_position():
    """Validation: pos_rank scores must stay on [0.0, 1.0] or halt."""
    for position in ("RB", "WR", "TE"):
        for rank in list(range(1, 12)) + [None]:
            assert 0.0 <= posrank_score(rank, position) <= 1.0


def test_qb_k_and_dst_are_never_scored_on_depth():
    """§5.9a — QB keeps a binary gate; K and D/ST have no depth factor."""
    for position in ("QB", "K", "DEF"):
        assert posrank_score(1, position) == 0.00


def test_missing_rank_scores_zero():
    assert posrank_score(None, "RB") == 0.00
    assert posrank_score(None, "WR") == 0.00


def test_blend_weights_fade_to_zero_by_week_five():
    assert posrank_weights(1) == (1.0, 0.0)
    assert posrank_weights(2) == (0.75, 0.25)
    assert posrank_weights(3) == (0.50, 0.50)
    assert posrank_weights(4) == (0.25, 0.75)
    for week in (5, 9, 18):
        assert posrank_weights(week) == (0.0, 1.0)
        assert not posrank_active(week)


# ---------------------------------------------------------------------------
# §13.2 — Week 1 exact scores
# ---------------------------------------------------------------------------


def test_week1_rb1_is_exactly_one_and_rb2_exactly_point_three():
    """§13.2 — the required Week 1 exacts, with no current usage data in play."""
    cfg = load_config()
    picker = RBPicker(cfg)
    rb1 = Player(player_id="RB-1", name="Lead Back", team="KC", position=Position.RB)
    rb2 = Player(player_id="RB-2", name="Backup", team="KC", position=Position.RB)
    rb3 = Player(player_id="RB-3", name="Third String", team="KC", position=Position.RB)
    ctx = _ctx(
        [rb1, rb2, rb3],
        week=1,
        pos_rank={"RB": {"RB-1": 1, "RB-2": 2, "RB-3": 3}},
    )
    assert _depth(picker, ctx, rb1).score == pytest.approx(1.00)
    assert _depth(picker, ctx, rb2).score == pytest.approx(0.30)
    assert _depth(picker, ctx, rb3).score == pytest.approx(0.00)


def test_week1_wr2_is_exactly_point_six_and_wr3_point_two_five():
    cfg = load_config()
    picker = WRPicker(cfg)
    wr1 = Player(player_id="WR-1", name="Alpha", team="LAC", position=Position.WR)
    wr2 = Player(player_id="WR-2", name="Two", team="LAC", position=Position.WR)
    wr3 = Player(player_id="WR-3", name="Three", team="LAC", position=Position.WR)
    wr4 = Player(player_id="WR-4", name="Four", team="LAC", position=Position.WR)
    ctx = _ctx(
        [wr1, wr2, wr3, wr4],
        week=1,
        pos_rank={"WR": {"WR-1": 1, "WR-2": 2, "WR-3": 3, "WR-4": 4}},
    )
    assert _depth(picker, ctx, wr1).score == pytest.approx(1.00)
    assert _depth(picker, ctx, wr2).score == pytest.approx(0.60)
    assert _depth(picker, ctx, wr3).score == pytest.approx(0.25)
    assert _depth(picker, ctx, wr4).score == pytest.approx(0.00)


def test_week1_rb_depth_ignores_snap_share_entirely():
    """Week 1 usage weight is 0%, so any current share must leave the score alone."""
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="RB-1", name="Lead Back", team="KC", position=Position.RB)
    for share in (0.0, 0.05, 0.35, 0.72, 0.95):
        ctx = _ctx([rb], week=1, pos_rank={"RB": {"RB-1": 1}}, snap_share={"RB-1": share})
        assert _depth(picker, ctx, rb).score == pytest.approx(1.00), share


# ---------------------------------------------------------------------------
# §5.10.1 — the blend arithmetic
# ---------------------------------------------------------------------------


def test_week3_blend_arithmetic_is_the_worked_example():
    """§13.2 — RB1 with a 35% snap share: (0.50 x 1.00) + (0.50 x 0.20) = 0.60."""
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="RB-1", name="Lead Back", team="KC", position=Position.RB)
    ctx = _ctx([rb], week=3, pos_rank={"RB": {"RB-1": 1}}, snap_share={"RB-1": 0.35})

    # State the terms so a regression names which half moved.
    assert posrank_score(1, "RB") == 1.00
    assert snap_share_score(0.35) == 0.20
    assert _depth(picker, ctx, rb).score == pytest.approx(0.60)


def test_rb_depth_follows_the_whole_fade_schedule():
    """§5.10.1 — an RB1 at 35% snaps walks 1.00 → 0.20 across Weeks 1–5."""
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="RB-1", name="Lead Back", team="KC", position=Position.RB)
    expected = {1: 1.00, 2: 0.80, 3: 0.60, 4: 0.40, 5: 0.20}
    for week, want in expected.items():
        ctx = _ctx([rb], week=week, pos_rank={"RB": {"RB-1": 1}}, snap_share={"RB-1": 0.35})
        assert _depth(picker, ctx, rb).score == pytest.approx(want), f"week {week}"


def test_wr_blend_needs_no_scale_conversion():
    """Both WR sources use the identical table, so the blend of WR2/WR2 stays 0.60."""
    cfg = load_config()
    picker = WRPicker(cfg)
    wr = Player(player_id="WR-2", name="Two", team="LAC", position=Position.WR)
    for week in (1, 2, 3, 4, 5):
        ctx = _ctx(
            [wr],
            week=week,
            pos_rank={"WR": {"WR-2": 2}},
            roles={"WR-2": "WR2"},
            roles_current={"WR-2": "WR2"},
        )
        assert _depth(picker, ctx, wr).score == pytest.approx(0.60), f"week {week}"


def test_wr_week3_blends_a_depth_wr1_against_a_realized_wr3():
    """A charted WR1 whose targets say WR3: (0.50 x 1.00) + (0.50 x 0.25) = 0.625."""
    cfg = load_config()
    picker = WRPicker(cfg)
    wr = Player(player_id="WR-1", name="Alpha", team="LAC", position=Position.WR)
    ctx = _ctx(
        [wr],
        week=3,
        pos_rank={"WR": {"WR-1": 1}},
        roles={"WR-1": "WR1"},
        roles_current={"WR-1": "WR3"},
    )
    assert _depth(picker, ctx, wr).score == pytest.approx(0.625)


# ---------------------------------------------------------------------------
# §13.2 / non-negotiable #8c — inert from Week 5
# ---------------------------------------------------------------------------


def test_identical_usage_scores_identically_from_week_five_regardless_of_posrank():
    """§13.2 — the leak test. A pos_rank contribution past Week 4 would be invisible."""
    cfg = load_config()
    picker = RBPicker(cfg)
    lead = Player(player_id="RB-1", name="Charted RB1", team="KC", position=Position.RB)
    third = Player(player_id="RB-3", name="Charted RB3", team="SEA", position=Position.RB)
    shares = {"RB-1": 0.35, "RB-3": 0.35}

    for week in (5, 9, 18):
        ctx = _ctx(
            [lead, third],
            week=week,
            pos_rank={"RB": {"RB-1": 1, "RB-3": 3}},
            snap_share=shares,
        )
        assert _depth(picker, ctx, lead).score == pytest.approx(
            _depth(picker, ctx, third).score
        ), f"week {week}"
        assert _depth(picker, ctx, lead).score == pytest.approx(0.20), f"week {week}"


def test_week_five_wr_depth_ignores_posrank():
    cfg = load_config()
    picker = WRPicker(cfg)
    charted_first = Player(player_id="WR-A", name="Charted WR1", team="LAC", position=Position.WR)
    charted_third = Player(player_id="WR-B", name="Charted WR3", team="KC", position=Position.WR)
    ctx = _ctx(
        [charted_first, charted_third],
        week=5,
        pos_rank={"WR": {"WR-A": 1, "WR-B": 3}},
        roles_current={"WR-A": "WR2", "WR-B": "WR2"},
    )
    assert _depth(picker, ctx, charted_first).score == pytest.approx(0.60)
    assert _depth(picker, ctx, charted_third).score == pytest.approx(0.60)


def test_week_five_unlisted_rb_with_no_snaps_scores_zero_not_a_depth_fallback():
    """The retired fallback would have tiered him off pos_rank — that is the leak."""
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="RB-1", name="Charted RB1", team="KC", position=Position.RB)
    ctx = _ctx([rb], week=5, pos_rank={"RB": {"RB-1": 1}}, snap_share={})
    factor = _depth(picker, ctx, rb)
    assert factor.score == pytest.approx(0.00)
    assert factor.raw_value == "inactive"


# ---------------------------------------------------------------------------
# D20 — no depth entry
# ---------------------------------------------------------------------------


def test_player_absent_from_depth_chart_scores_zero_and_carries_the_flag():
    """§13.2 / D20 — absence scores 0.00; the flag separates it from a real demotion."""
    cfg = load_config()
    picker = RBPicker(cfg)
    unlisted = Player(player_id="RB-U", name="Unlisted", team="KC", position=Position.RB)
    charted = Player(player_id="RB-1", name="Charted", team="SEA", position=Position.RB)
    ctx = _ctx(
        [unlisted, charted],
        week=1,
        pos_rank={"RB": {"RB-1": 1}},
        no_depth_entry=["RB-U"],
    )

    factor = _depth(picker, ctx, unlisted)
    assert factor.score == pytest.approx(0.00)
    assert NO_DEPTH_ENTRY in (factor.raw_value or "")

    starters, bench = picker.select(ctx, [unlisted, charted])
    by_id = {s.player.player_id: s for s in starters + bench}
    assert NO_DEPTH_ENTRY in by_id["RB-U"].flags
    assert NO_DEPTH_ENTRY not in by_id["RB-1"].flags


def test_no_depth_entry_and_rank_four_score_alike_but_read_differently():
    """Both are 0.00; only the flagged one says the score came from absence."""
    cfg = load_config()
    picker = RBPicker(cfg)
    unlisted = Player(player_id="RB-U", name="Unlisted", team="KC", position=Position.RB)
    fourth = Player(player_id="RB-4", name="Fourth", team="KC", position=Position.RB)
    ctx = _ctx(
        [unlisted, fourth],
        week=1,
        pos_rank={"RB": {"RB-4": 4}},
        no_depth_entry=["RB-U"],
    )
    assert _depth(picker, ctx, unlisted).score == _depth(picker, ctx, fourth).score == 0.0
    assert NO_DEPTH_ENTRY in (_depth(picker, ctx, unlisted).raw_value or "")
    assert NO_DEPTH_ENTRY not in (_depth(picker, ctx, fourth).raw_value or "")


# ---------------------------------------------------------------------------
# Non-negotiable #8b — pinning
# ---------------------------------------------------------------------------


def _depth_frame(rows: list[tuple[str, str, str, int, str]]) -> pl.DataFrame:
    """rows of (gsis_id, team, pos_abb, pos_rank, dt)."""
    return pl.DataFrame(
        {
            "gsis_id": [r[0] for r in rows],
            "team": [r[1] for r in rows],
            "pos_abb": [r[2] for r in rows],
            "pos_rank": [r[3] for r in rows],
            "dt": [r[4] for r in rows],
        }
    )


def test_pinning_resolves_a_midseason_rank_change_to_the_latest_dt():
    """§13.2 — a player promoted mid-season must resolve to his current rank."""
    depth = _depth_frame(
        [
            ("A", "KC", "RB", 2, "2026-09-01T00:00:00Z"),
            ("B", "KC", "RB", 1, "2026-09-01T00:00:00Z"),
            ("A", "KC", "RB", 1, "2026-10-15T00:00:00Z"),
            ("B", "KC", "RB", 2, "2026-10-15T00:00:00Z"),
        ]
    )
    ranks = derive_pos_ranks(depth, 7)["RB"]
    assert ranks == {"A": 1, "B": 2}
    # The stale snapshot, which an unpinned read would have surfaced.
    assert ranks["A"] != 2


def test_pinning_is_per_team_so_a_lagging_feed_is_not_dropped():
    """Per-team max dt — a team whose feed lags the global max keeps its chart."""
    depth = _depth_frame(
        [
            ("A", "KC", "RB", 1, "2026-10-15T00:00:00Z"),
            ("B", "SEA", "RB", 1, "2026-10-08T00:00:00Z"),
        ]
    )
    ranks = derive_pos_ranks(depth, 7)["RB"]
    assert ranks == {"A": 1, "B": 1}


def test_pos_ranks_are_scoped_by_position_group():
    """A player charted at two slots must not contaminate the other's lookup."""
    depth = _depth_frame(
        [
            ("HYBRID", "KC", "RB", 1, "2026-09-01T00:00:00Z"),
            ("HYBRID", "KC", "WR", 4, "2026-09-01T00:00:00Z"),
            ("FB", "KC", "FB", 2, "2026-09-01T00:00:00Z"),
        ]
    )
    ranks = derive_pos_ranks(depth, 1)
    assert ranks["RB"]["HYBRID"] == 1
    assert ranks["WR"]["HYBRID"] == 4
    # FB shares the RB room.
    assert ranks["RB"]["FB"] == 2


def test_defensive_and_oline_slots_are_read_but_never_scored():
    """pos_rank is still read for starter identification; it just never lands in a table."""
    depth = _depth_frame(
        [
            ("QB", "KC", "QB", 1, "2026-09-01T00:00:00Z"),
            ("LT", "KC", "LT", 1, "2026-09-01T00:00:00Z"),
            ("CB", "KC", "RCB", 1, "2026-09-01T00:00:00Z"),
        ]
    )
    ranks = derive_pos_ranks(depth, 1)
    assert ranks == {"RB": {}, "WR": {}, "TE": {}}
    # Gate map includes QB; OL/DB still excluded.
    assert derive_depth_chart_order(depth, 1)["QB"] == {"QB": 1}


def test_depth_chart_order_is_position_scoped_against_kr_overwrite():
    """Flat last-row-wins let a KR3 overwrite RB1; position scoping keeps RB=1.

    Jeremiyah Love (ARI) is the live case: charted RB1 and KR3. Under the old flat
    map, emitting the KR row after the RB row set depth_chart_order[pid]=3. The QB
    gate reading that shape would treat a dual-listed QB1 the same way.
    """
    love = "00-0041027"
    depth = pl.DataFrame(
        {
            "gsis_id": [love, love],
            "team": ["ARI", "ARI"],
            "pos_abb": ["RB", "KR"],
            "pos_rank": [1, 3],
            "dt": ["2026-09-13T12:42:08Z", "2026-09-13T12:42:08Z"],
        }
    )
    # Force the failure order: RB first, KR last — what a flat map would keep as 3.
    depth = pl.concat(
        [
            depth.filter(pl.col("pos_abb") == "RB"),
            depth.filter(pl.col("pos_abb") == "KR"),
        ]
    )

    # OLD behavior — recreate the flat last-row-wins map the bug lived in.
    flat: dict[str, int] = {}
    for r in depth.to_dicts():
        flat[str(r["gsis_id"])] = int(r["pos_rank"])
    assert flat[love] == 3  # KR won

    scoped = derive_depth_chart_order(depth, 1)
    assert scoped["RB"][love] == 1  # RB room untouched
    assert love not in scoped.get("QB", {})
    assert "KR" not in scoped  # special teams never enter the gate map


def test_qb_gate_reads_qb_bucket_not_a_flat_map():
    """A KR overwrite in a flat map must not eliminate a real QB1 via depth_order."""
    from brady_bot.pickers.qb import QBPicker

    cfg = load_config()
    qb = Player(player_id="00-0023459", name="Aaron Rodgers", team="PIT", position=Position.QB)
    ctx = _ctx([qb], week=1)
    ctx.depth_chart_order = {"QB": {"00-0023459": 1}}
    ctx.roles = {}
    ctx.qb1_by_team = {}
    picker = QBPicker(cfg)
    assert picker.gate(ctx, qb) is None  # passes on QB-scoped order=1

    # Wrong QB bucket rank still fails closed — gate does not invent a starter.
    ctx.depth_chart_order = {"QB": {"00-0023459": 3}}
    gated = picker.gate(ctx, qb)
    assert gated is not None and gated.gate_reason == "not_qb1"


def test_te_fallback_sorts_by_te_bucket():
    """TE gate fallback must rank by TE depth, not a polluted flat map."""
    from brady_bot.models import InjuryRecord
    from brady_bot.pickers.te import TEPicker

    cfg = load_config()
    te1 = Player(player_id="TE-1", name="Starter", team="KC", position=Position.TE)
    te2 = Player(player_id="TE-2", name="Backup", team="KC", position=Position.TE)
    ctx = _ctx([te1, te2], week=1)
    # No TE1 role — force the depth_chart_order fallback path.
    ctx.roles = {"TE-2": "TE2"}
    ctx.depth_chart_order = {"TE": {"TE-1": 1, "TE-2": 2}}
    picker = TEPicker(cfg)
    assert picker.gate(ctx, te1) is None
    gated = picker.gate(ctx, te2)
    assert gated is not None and gated.gate_reason == "not_te1"

    ctx.injuries = {"TE-1": InjuryRecord(player_id="TE-1", report_status="Out")}
    assert picker.gate(ctx, te2) is None


# ---------------------------------------------------------------------------
# FLEX Step 2 — the highest-stakes factor
# ---------------------------------------------------------------------------


def test_flex_week1_wr2_beats_rb2_all_else_equal():
    """§13.2 — Opportunity is 40%, so 0.60 vs 0.30 decides the slot in Week 1."""
    cfg = load_config()
    picker = FlexPicker(cfg)
    rb2 = Player(player_id="RB-2", name="Backup Back", team="KC", position=Position.RB)
    wr2 = Player(player_id="WR-2", name="Second Receiver", team="KC", position=Position.WR)
    ctx = _ctx(
        [rb2, wr2],
        week=1,
        pos_rank={"RB": {"RB-2": 2}, "WR": {"WR-2": 2}},
    )
    assert _opportunity(picker, ctx, rb2).score == pytest.approx(0.30)
    assert _opportunity(picker, ctx, wr2).score == pytest.approx(0.60)

    starters, _ = picker.select(ctx, [rb2, wr2])
    assert starters[0].player.player_id == "WR-2"


def test_flex_week1_scores_every_rank_one_at_one_regardless_of_position():
    """The cross-position early table: RB1, WR1 and TE1 all score 1.00."""
    cfg = load_config()
    picker = FlexPicker(cfg)
    rb = Player(player_id="RB-1", name="Back", team="KC", position=Position.RB)
    wr = Player(player_id="WR-1", name="Receiver", team="SEA", position=Position.WR)
    te = Player(player_id="TE-1", name="Tight End", team="DEN", position=Position.TE)
    ctx = _ctx(
        [rb, wr, te],
        week=1,
        pos_rank={"RB": {"RB-1": 1}, "WR": {"WR-1": 1}, "TE": {"TE-1": 1}},
        roles={"TE-1": "TE1"},
    )
    for player in (rb, wr, te):
        assert _opportunity(picker, ctx, player).score == pytest.approx(1.00), player.name


def test_flex_te_tables_are_not_reconciled():
    """TE1 is a flat 1.00 on pos_rank but 0.70 on usage with healthy WRs — by design.

    WR health is a live in-season condition a preseason depth chart cannot express, so
    it only enters once the usage component carries weight.
    """
    cfg = load_config()
    picker = FlexPicker(cfg)
    te = Player(player_id="TE-1", name="Tight End", team="KC", position=Position.TE)
    pos_rank = {"TE": {"TE-1": 1}}

    week1 = _ctx([te], week=1, pos_rank=pos_rank, roles={"TE-1": "TE1"})
    assert _opportunity(picker, week1, te).score == pytest.approx(1.00)

    week5 = _ctx([te], week=5, pos_rank=pos_rank, roles={"TE-1": "TE1"})
    assert _opportunity(picker, week5, te).score == pytest.approx(0.70)

    # Week 3 is the midpoint of the two tables: (0.50 x 1.00) + (0.50 x 0.70).
    week3 = _ctx([te], week=3, pos_rank=pos_rank, roles={"TE-1": "TE1"})
    assert _opportunity(picker, week3, te).score == pytest.approx(0.85)


def test_flex_week5_uses_the_usage_table_only():
    cfg = load_config()
    picker = FlexPicker(cfg)
    rb2 = Player(player_id="RB-2", name="Backup Back", team="KC", position=Position.RB)
    wr2 = Player(player_id="WR-2", name="Second Receiver", team="KC", position=Position.WR)
    ctx = _ctx(
        [rb2, wr2],
        week=5,
        pos_rank={"RB": {"RB-2": 2}, "WR": {"WR-2": 2}},
        snap_share={"RB-2": 0.65},
        roles_current={"WR-2": "WR2"},
    )
    assert _opportunity(picker, ctx, rb2).score == pytest.approx(1.00)  # workhorse
    assert _opportunity(picker, ctx, wr2).score == pytest.approx(0.65)  # WR2 usage row


# ---------------------------------------------------------------------------
# The committee 0.50 substitution is gone from the scoring path
# ---------------------------------------------------------------------------


def test_no_factor_ever_lands_on_the_retired_neutral_score():
    """D16 retired — a Week 1 RB depth score is 1.00 / 0.30 / 0.00, never 0.50.

    pos_rank reads the current team's current depth chart, so it already reflects a
    player's new situation. Forcing 0.50 on top would discard good data.
    """
    cfg = load_config()
    picker = RBPicker(cfg)
    for rank, want in ((1, 1.00), (2, 0.30), (3, 0.00)):
        rb = Player(player_id="RB-X", name="Back", team="KC", position=Position.RB)
        ctx = _ctx([rb], week=1, pos_rank={"RB": {"RB-X": rank}})
        score = _depth(picker, ctx, rb).score
        assert score == pytest.approx(want)
        assert score != pytest.approx(0.50)


def test_the_committee_module_is_gone():
    """§5.9b retired — automatic committee-change detection is no longer computed."""
    with pytest.raises(ModuleNotFoundError):
        __import__("brady_bot.derive.committee")


def test_week_context_no_longer_carries_committee_state():
    fields = set(WeekContext.model_fields)
    assert "committee_changed" not in fields
    assert "committee_incomplete" not in fields
    assert "pos_rank" in fields
    assert "no_depth_entry" in fields


# ---------------------------------------------------------------------------
# Breakdown labels — a 20–40% factor must never read as a bare number
# ---------------------------------------------------------------------------


def test_blend_label_names_both_components_and_their_weights():
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="RB-1", name="Lead Back", team="KC", position=Position.RB)

    week1 = _ctx([rb], week=1, pos_rank={"RB": {"RB-1": 1}}, snap_share={"RB-1": 0.35})
    assert _depth(picker, week1, rb).raw_value == "RB1 1.00 (wk1)"

    week3 = _ctx([rb], week=3, pos_rank={"RB": {"RB-1": 1}}, snap_share={"RB-1": 0.35})
    raw = _depth(picker, week3, rb).raw_value or ""
    assert "RB1 1.00@50%" in raw
    assert "snap=35% 0.20@50%" in raw

    week5 = _ctx([rb], week=5, pos_rank={"RB": {"RB-1": 1}}, snap_share={"RB-1": 0.35})
    assert _depth(picker, week5, rb).raw_value == "snap=35%"


# ---------------------------------------------------------------------------
# S11 depth overrides
# ---------------------------------------------------------------------------


def test_depth_override_beats_the_published_depth_chart():
    """§13.2 — a manual pos_rank wins, including for a player the chart omits."""
    depth = _depth_frame(
        [
            ("STALE", "KC", "RB", 3, "2026-09-01T00:00:00Z"),
            ("INCUMBENT", "KC", "RB", 1, "2026-09-01T00:00:00Z"),
        ]
    )
    published = derive_pos_ranks(depth, 1)["RB"]
    assert published["STALE"] == 3

    overridden = derive_pos_ranks(
        depth, 1, overrides={"STALE": ("RB", 1), "SIGNED": ("RB", 2)}
    )["RB"]
    assert overridden["STALE"] == 1
    assert overridden["SIGNED"] == 2  # absent from the chart entirely
    assert overridden["INCUMBENT"] == 1


def test_depth_override_changes_a_week1_score():
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="STALE", name="Post-cuts Signing", team="KC", position=Position.RB)
    depth = _depth_frame([("STALE", "KC", "RB", 3, "2026-09-01T00:00:00Z")])

    published = _ctx([rb], week=1, pos_rank=derive_pos_ranks(depth, 1))
    assert _depth(picker, published, rb).score == pytest.approx(0.00)

    forced = _ctx(
        [rb], week=1, pos_rank=derive_pos_ranks(depth, 1, overrides={"STALE": ("RB", 1)})
    )
    assert _depth(picker, forced, rb).score == pytest.approx(1.00)


def test_depth_overrides_config_parses_the_documented_shape():
    entries = _load_depth_overrides(
        {
            "depth_overrides": [
                {
                    "name": "Example Player",
                    "team": "KC",
                    "position": "rb",
                    "pos_rank": 1,
                    "note": "Signed post-cuts; depth chart not yet updated",
                }
            ]
        }
    )
    assert entries == [
        {
            "name": "Example Player",
            "team": "KC",
            "position": "RB",
            "pos_rank": 1,
            "note": "Signed post-cuts; depth chart not yet updated",
        }
    ]


def test_shipped_config_loads_and_is_a_depth_override_file():
    cfg = load_config()
    assert not hasattr(cfg, "committee_overrides")
    for entry in cfg.depth_overrides:
        assert entry["position"] in ("RB", "WR", "TE")
        assert entry["pos_rank"] >= 1
        assert entry.get("note")


def test_legacy_committee_block_halts_rather_than_being_ignored():
    """A silently ignored legacy block would leave a stale rank driving a live factor."""
    with pytest.raises(ConfigError, match="retired"):
        _load_depth_overrides(
            {"committee_overrides": [{"name": "X", "team": "KC", "changed": True}]}
        )


def test_depth_overrides_rejects_missing_pos_rank():
    with pytest.raises(ConfigError, match="missing 'pos_rank'"):
        _load_depth_overrides(
            {"depth_overrides": [{"name": "X", "team": "KC", "position": "RB"}]}
        )


def test_depth_overrides_rejects_unscored_position():
    with pytest.raises(ConfigError, match="must be one of"):
        _load_depth_overrides(
            {"depth_overrides": [{"name": "X", "position": "QB", "pos_rank": 1}]}
        )


def test_depth_overrides_rejects_non_integer_pos_rank():
    for bad in ("1", 0, -2, True, 1.5):
        with pytest.raises(ConfigError, match="must be an integer"):
            _load_depth_overrides(
                {"depth_overrides": [{"name": "X", "position": "RB", "pos_rank": bad}]}
            )


def test_depth_overrides_rejects_nameless_entry():
    with pytest.raises(ConfigError, match="missing a name"):
        _load_depth_overrides({"depth_overrides": [{"position": "RB", "pos_rank": 1}]})


# ---------------------------------------------------------------------------
# §5.10.2 / D18 — per-game denominator. Survives the committee retirement.
# ---------------------------------------------------------------------------


def test_snap_share_denominator_excludes_missed_games():
    """§13.2 — 70% across 10 games played, 7 missed, scores 1.00 not 0.20."""
    played = 10
    missed = 7
    rows = []
    for wk in range(1, played + 1):
        rows.append(("00-A", "DEN", wk, 70.0))
    # Missed games simply have no snap-count row; they must not become zeros.
    snaps = pl.DataFrame(
        {
            "pfr_player_id": [r[0] for r in rows],
            "team": [r[1] for r in rows],
            "week": [r[2] for r in rows],
            "offense_pct": [r[3] for r in rows],
            "position": ["RB"] * len(rows),
            "season": [2025] * len(rows),
        }
    )
    players = pl.DataFrame({"gsis_id": ["G-A"], "pfr_id": ["00-A"]})
    shares = snap_shares_by_team(snaps, 2025, 1, 18, ("RB",), players=players)
    share = shares[("G-A", "DEN")]

    assert share == pytest.approx(0.70)
    assert snap_share_score(share) == 1.00

    # The bug this rule surfaced: dividing by team games instead.
    wrong = (0.70 * played) / (played + missed)
    assert wrong == pytest.approx(0.4118, abs=1e-4)
    assert snap_share_score(wrong) == 0.20


def test_target_share_denominator_excludes_missed_games():
    """A receiver who missed games keeps his real per-game share of team targets."""
    rows = []
    for wk in range(1, 18):
        # Team-mate plays every week with 6 targets.
        rows.append(("MATE", "LAC", wk, 6))
    for wk in range(1, 11):
        # Our receiver plays 10 of 17 at 14 targets → 14/20 = 70% per game.
        rows.append(("STAR", "LAC", wk, 14))
    ps = pl.DataFrame(
        {
            "player_id": [r[0] for r in rows],
            "team": [r[1] for r in rows],
            "week": [r[2] for r in rows],
            "targets": [r[3] for r in rows],
            "position": ["WR"] * len(rows),
            "season": [2025] * len(rows),
        }
    )
    shares = target_shares_by_team(ps, 2025, 1, 18, ("WR",))
    assert shares[("STAR", "LAC")] == pytest.approx(0.70)

    # Summing the window and dividing by the team's window total — the old behaviour —
    # puts the seven games he missed into his denominator.
    wrong = (14 * 10) / (14 * 10 + 6 * 17)
    assert wrong == pytest.approx(0.5785, abs=1e-4)
    assert shares[("STAR", "LAC")] > wrong


def test_zero_target_game_counts_but_missed_game_does_not():
    """Active with 0 targets is real signal; a missed game is not a zero."""
    rows = [("A", "KC", 1, 10), ("A", "KC", 2, 0), ("B", "KC", 1, 10), ("B", "KC", 2, 10)]
    ps = pl.DataFrame(
        {
            "player_id": [r[0] for r in rows],
            "team": [r[1] for r in rows],
            "week": [r[2] for r in rows],
            "targets": [r[3] for r in rows],
            "position": ["WR"] * len(rows),
            "season": [2025] * len(rows),
        }
    )
    shares = target_shares_by_team(ps, 2025, 1, 18, ("WR",))
    # A: week 1 = 10/20 = 0.50, week 2 = 0/10 = 0.00 → mean 0.25
    assert shares[("A", "KC")] == pytest.approx(0.25)

    # Drop A's zero-target week entirely (as if he were inactive) → mean over 1 game
    played_only = ps.filter(~((pl.col("player_id") == "A") & (pl.col("week") == 2)))
    shares2 = target_shares_by_team(played_only, 2025, 1, 18, ("WR",))
    assert shares2[("A", "KC")] == pytest.approx(0.50)
