"""S12 QB calibre ranking — static list, derived fallback, four consumers (D21).

Guards the property the change exists to create: WR Step 5, TE Step 5, FLEX Step 4 and
DEF Step 2 read *one* rank for a given quarterback, and the QB picker reads none of it.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from brady_bot.config import ConfigError, _load_qb_calibre_ranks, load_config
from brady_bot.derive.qb_calibre import (
    FALLBACK_FLAG,
    fallback_warnings,
    merge_qb_calibre,
)
from brady_bot.models import (
    GameContext,
    InjuryRecord,
    Player,
    Position,
    TeamStats,
    WeekContext,
)
from brady_bot.normalizer import (
    AmbiguousPlayerError,
    UnresolvedPlayerError,
    normalize_name,
    resolve_qb_calibre_ranks,
)
from brady_bot.pickers.defense import DefensePicker
from brady_bot.pickers.flex import FlexPicker
from brady_bot.pickers.qb import QBPicker
from brady_bot.pickers.te import TEPicker
from brady_bot.pickers.wr import WRPicker
from brady_bot.scoring.shared import (
    qb_calibre_of,
    qb_calibre_tier,
    qb_quality_label,
    qb_quality_score,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"
SPEC = Path(__file__).resolve().parents[1] / "docs" / "lineup" / "lineup-picker-qb-calibre.md"


# --------------------------------------------------------------------------------------
# The list itself
# --------------------------------------------------------------------------------------


def test_config_file_is_separate_from_static_lists():
    """S12 lives in its own flat file, same reasoning as oline_ranks.yaml."""
    assert (CONFIG / "qb_calibre_ranks.yaml").exists()
    static = yaml.safe_load((CONFIG / "static_lists.yaml").read_text()) or {}
    assert "qb_calibre_ranks" not in static


def test_ranking_is_99_contiguous_no_duplicates():
    cfg = load_config()
    entries = cfg.qb_calibre_ranks
    assert len(entries) == 99
    assert [e["rank"] for e in entries] == list(range(1, 100))
    names = [normalize_name(e["name"]) for e in entries]
    assert len(set(names)) == 99


def test_ranking_covers_all_32_teams():
    cfg = load_config()
    assert len({e["team"] for e in cfg.qb_calibre_ranks}) == 32


def test_new_orleans_survives_yaml_bool_coercion():
    """A bare NO parses as False under YAML 1.1, which would drop the Saints silently."""
    cfg = load_config()
    assert [e["name"] for e in cfg.qb_calibre_ranks if e["team"] == "NO"]


def test_config_matches_the_spec_document():
    """The doc is authoritative; the YAML is generated from it (scripts/gen_qb_calibre_ranks.py)."""
    from scripts.gen_qb_calibre_ranks import parse_spec, render

    assert (CONFIG / "qb_calibre_ranks.yaml").read_text() == render(parse_spec(SPEC.read_text()))


def test_duplicate_rank_halts():
    raw = {
        "qb_calibre_ranks": [
            {"rank": 1, "name": "Josh Allen", "team": "BUF"},
            {"rank": 1, "name": "Drake Maye", "team": "NE"},
        ]
    }
    with pytest.raises(ConfigError, match="duplicate rank 1"):
        _load_qb_calibre_ranks(raw, {})


def test_gap_in_ranks_halts_naming_the_gap():
    raw = {
        "qb_calibre_ranks": [
            {"rank": 1, "name": "Josh Allen", "team": "BUF"},
            {"rank": 3, "name": "Joe Burrow", "team": "CIN"},
        ]
    }
    with pytest.raises(ConfigError, match=r"missing=\[2\]"):
        _load_qb_calibre_ranks(raw, {})


def test_duplicate_name_halts():
    raw = {
        "qb_calibre_ranks": [
            {"rank": 1, "name": "Josh Allen", "team": "BUF"},
            {"rank": 2, "name": "Josh Allen Jr.", "team": "NE"},
        ]
    }
    with pytest.raises(ConfigError, match="duplicate name"):
        _load_qb_calibre_ranks(raw, {})


def test_unquoted_team_code_halts_rather_than_miskeying():
    raw = {"qb_calibre_ranks": [{"rank": 1, "name": "Tyler Shough", "team": False}]}
    with pytest.raises(ConfigError, match="must be a quoted string"):
        _load_qb_calibre_ranks(raw, {})


# --------------------------------------------------------------------------------------
# Name resolution
# --------------------------------------------------------------------------------------


def _players(rows: list[tuple[str, str, str, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"gsis_id": gid, "display_name": name, "latest_team": team, "position": pos}
            for gid, name, team, pos in rows
        ]
    )


def test_richardson_suffix_resolves_to_one_gsis_id():
    """'Anthony Richardson Sr.' here vs 'Anthony Richardson' in nflverse — one record."""
    assert normalize_name("Anthony Richardson Sr.") == normalize_name("Anthony Richardson")
    df = _players([("00-0039164", "Anthony Richardson", "IND", "QB")])
    out = resolve_qb_calibre_ranks(
        [{"rank": 59, "name": "Anthony Richardson Sr.", "team": "IND"}], df, {}
    )
    assert out == {"00-0039164": 59}


def test_same_team_surname_resolves_by_name_not_just_team():
    """Buffalo carries Josh Allen (1) and Kyle Allen (67); both must land distinctly."""
    df = _players(
        [
            ("00-0034857", "Josh Allen", "BUF", "QB"),
            ("00-0034577", "Kyle Allen", "BUF", "QB"),
        ]
    )
    out = resolve_qb_calibre_ranks(
        [
            {"rank": 1, "name": "Josh Allen", "team": "BUF"},
            {"rank": 67, "name": "Kyle Allen", "team": "BUF"},
        ],
        df,
        {},
    )
    assert out == {"00-0034857": 1, "00-0034577": 67}


def test_position_filter_excludes_the_same_named_non_qb():
    """'Josh Allen' is also a lineman; filtering on position keeps the QB."""
    df = _players(
        [
            ("00-0030833", "Josh Allen", "TB", "C"),
            ("00-0034857", "Josh Allen", "BUF", "QB"),
        ]
    )
    out = resolve_qb_calibre_ranks([{"rank": 1, "name": "Josh Allen", "team": "BUF"}], df, {})
    assert out == {"00-0034857": 1}


def test_unresolved_name_halts():
    df = _players([("00-0034857", "Josh Allen", "BUF", "QB")])
    with pytest.raises(UnresolvedPlayerError, match="Nonexistent Quarterback"):
        resolve_qb_calibre_ranks(
            [{"rank": 1, "name": "Nonexistent Quarterback", "team": "BUF"}], df, {}
        )


def test_two_entries_collapsing_to_one_id_halts():
    """A silent collapse would leave one QB's rank standing in for another's."""
    df = _players([("00-0034857", "Josh Allen", "BUF", "QB")])
    with pytest.raises(AmbiguousPlayerError, match="both resolved to 00-0034857"):
        resolve_qb_calibre_ranks(
            [
                {"rank": 1, "name": "Josh Allen", "team": "BUF"},
                {"rank": 2, "name": "Josh Allen Sr.", "team": "BUF"},
            ],
            df,
            {},
        )


# --------------------------------------------------------------------------------------
# Static overlay and derived fallback
# --------------------------------------------------------------------------------------


def test_static_rank_beats_derived_rank():
    """A listed QB reads his listed rank, whatever his fantasy points say."""
    merged, fallback = merge_qb_calibre({"LISTED": 1}, {"LISTED": 40})
    assert merged["LISTED"] == 1
    assert fallback == set()


def test_unlisted_qb_keeps_derived_rank_and_is_flagged():
    merged, fallback = merge_qb_calibre({"LISTED": 1}, {"LISTED": 40, "UNLISTED": 12})
    assert merged == {"LISTED": 1, "UNLISTED": 12}
    assert fallback == {"UNLISTED"}


def test_mid_season_arrival_with_no_stats_at_all_never_errors():
    """A promoted practice-squad arm is absent from both maps — unranked, not a crash."""
    merged, fallback = merge_qb_calibre({"LISTED": 1}, {})
    rank, is_fallback = qb_calibre_of(_ctx([], qb_calibre_fallback=fallback), "PROMOTED")
    assert rank is None and is_fallback is False
    assert qb_calibre_tier(None) == 0.0
    assert "PROMOTED" not in merged


def test_warning_names_only_the_starters_on_the_fallback_path():
    """A benched fallback QB scores nobody; a starting one is worth 15%–30% of a factor."""
    warns = fallback_warnings(
        {"gb": "SLOVIS", "kc": "MAHOMES"},
        {"SLOVIS", "BENCHED"},
        {"SLOVIS": "Kedon Slovis", "MAHOMES": "Patrick Mahomes"},
    )
    assert len(warns) == 1
    assert "Kedon Slovis (GB)" in warns[0]
    assert warns[0].startswith(FALLBACK_FLAG)


def test_no_warning_when_every_starter_is_on_the_list():
    assert fallback_warnings({"kc": "MAHOMES"}, {"BENCHED"}, {}) == []


def test_the_eight_unlisted_style_table_qbs_are_absent_from_s12():
    """Spec names these eight explicitly as the fallback's reason for existing."""
    cfg = load_config()
    listed = {normalize_name(e["name"]) for e in cfg.qb_calibre_ranks}
    for name in (
        "Joe Fagnano",
        "Mark Gronowski",
        "DJ Uiagalelei",
        "Joey Aguilar",
        "Kedon Slovis",
        "Jack Strand",
        "Matthew Caldwell",
        "Haynes King",
    ):
        assert normalize_name(name) not in listed, f"{name} unexpectedly on the calibre list"


# --------------------------------------------------------------------------------------
# The four consumers
# --------------------------------------------------------------------------------------

QB1 = "QB1"
WR = "WR_A"
TE = "TE_A"


def _ctx(roster: list[Player], **over) -> WeekContext:
    teams = sorted({p.team for p in roster} | {"KC", "BUF"})
    stats = {
        t: TeamStats(
            team=t,
            season=2026,
            through_week=5,
            offense_rank=16,
            total_defense_rank=16,
            scoring_efficiency_rank=16,
            defense_calibre_rank=16,
            qb_turnover_rank=20,  # keep the top-10 turnover row from short-circuiting
        )
        for t in teams
    }
    games = {
        t: GameContext(
            game_id="KC-BUF",
            home_team="KC",
            away_team="BUF",
            game_total=45,
            spread=-3,
            home_implied_total=24,
            away_implied_total=21,
        )
        for t in teams
    }
    adj = dict.fromkeys(teams, 0.0)
    base = dict(
        season=2026,
        week=5,
        fetched_at="2026-10-01T00:00:00Z",
        roster=roster,
        team_stats=stats,
        games=games,
        adj_fpa={"QB": adj, "RB": adj, "WR": adj, "TE": adj},
        calibre_rank={"QB": {}, "RB": {}, "WR": {}, "TE": {}, "K": {}},
        roles={},
        player_teams={p.player_id: p.team for p in roster},
        injury_counts={
            t: {
                "OL": 0,
                "SECONDARY": 0,
                "FRONT_SEVEN": 0,
                "FRONT_SEVEN_INTERIOR": 0,
                "DEFENSE_ALL": 0,
            }
            for t in teams
        },
        depth_chart_order={},
        pos_rank={},
        qb1_by_team={},
        static_ids={k: set() for k in ("elite_wrs", "elite_tes")},
        oline_ranks=dict.fromkeys(teams, 16),
    )
    base.update(over)
    return WeekContext(**base)


def _consumer_ctx(qb_rank: int, *, fallback: bool = False) -> WeekContext:
    """KC fields the QB; BUF's defence faces him. One rank, three tier tables."""
    roster = [
        Player(player_id=QB1, name="The Quarterback", team="KC", position=Position.QB),
        Player(player_id=WR, name="The Receiver", team="KC", position=Position.WR),
        Player(player_id=TE, name="The Tight End", team="KC", position=Position.TE),
        Player(player_id="DEF-BUF", name="BUF Defense", team="BUF", position=Position.DEF),
    ]
    ctx = _ctx(roster)
    ctx.calibre_rank["QB"] = {QB1: qb_rank}
    ctx.qb1_by_team = {"KC": QB1}
    ctx.roles = {QB1: "QB1", WR: "WR1", TE: "TE1"}
    ctx.qb_calibre_fallback = {QB1} if fallback else set()
    return ctx


def _factor(picker, ctx, player, name):
    return next(f for f in picker.score_factors(ctx, player) if f.name == name)


@pytest.mark.parametrize(
    "rank,wr_te,dst",
    [
        (1, 1.00, 0.15),  # elite: best for the receiver, worst for the defence
        (5, 1.00, 0.15),
        (6, 0.75, 0.35),
        (12, 0.75, 0.35),
        (13, 0.50, 0.50),
        (20, 0.50, 0.50),
        (21, 0.25, 0.65),
        (28, 0.25, 0.65),
        (29, 0.00, 0.65),
        (99, 0.00, 0.65),
    ],
)
def test_one_rank_three_tier_tables(rank, wr_te, dst):
    """WR/TE read the rank one direction, D/ST inverted — but it is the same rank."""
    cfg = load_config()
    ctx = _consumer_ctx(rank)
    wr_player = next(p for p in ctx.roster if p.player_id == WR)
    te_player = next(p for p in ctx.roster if p.player_id == TE)
    dst = pytest.approx(dst)

    assert _factor(WRPicker(cfg), ctx, wr_player, "qb_quality").score == pytest.approx(wr_te)
    assert _factor(TEPicker(cfg), ctx, te_player, "qb_quality").score == pytest.approx(wr_te)
    dst_player = next(p for p in ctx.roster if p.position == Position.DEF)
    assert _factor(DefensePicker(cfg), ctx, dst_player, "opp_qb").score == dst


def test_dst_reads_the_same_rank_as_wr_and_te():
    """The property the change exists for: no two pickers disagree about one QB."""
    cfg = load_config()
    ctx = _consumer_ctx(3)
    wr_player = next(p for p in ctx.roster if p.player_id == WR)
    dst_player = next(p for p in ctx.roster if p.position == Position.DEF)
    wr_raw = _factor(WRPicker(cfg), ctx, wr_player, "qb_quality").raw_value
    dst_raw = _factor(DefensePicker(cfg), ctx, dst_player, "opp_qb").raw_value
    assert "rank 3" in wr_raw and "rank 3" in dst_raw


def test_flex_situation_reads_the_static_rank_for_wr_candidates():
    cfg = load_config()
    ctx = _consumer_ctx(4)
    wr_player = next(p for p in ctx.roster if p.player_id == WR)
    situ = _factor(FlexPicker(cfg), ctx, wr_player, "situation")
    assert situ.score == pytest.approx(1.0)  # QB1 active and healthy
    assert "calibre rank 4" in situ.raw_value


def test_flex_situation_ignores_qb_quality_for_rb_candidates():
    cfg = load_config()
    ctx = _consumer_ctx(1)
    rb = Player(player_id="RB_A", name="The Back", team="KC", position=Position.RB)
    ctx.roster.append(rb)
    ctx.player_teams[rb.player_id] = "KC"
    situ = _factor(FlexPicker(cfg), ctx, rb, "situation")
    assert situ.score == pytest.approx(1.0)
    assert situ.raw_value is None  # no QB component at all for a RB


def test_backup_cap_holds_even_for_an_elite_backup():
    """QB1 out caps WR/TE at 0.50 however good the listed backup is."""
    cfg = load_config()
    ctx = _consumer_ctx(1)
    backup = Player(player_id="QB2", name="The Backup", team="KC", position=Position.QB)
    ctx.roster.append(backup)
    ctx.player_teams["QB2"] = "KC"
    ctx.roles["QB2"] = "QB2"
    ctx.calibre_rank["QB"]["QB2"] = 2  # elite by the list
    ctx.injuries = {QB1: InjuryRecord(player_id=QB1, report_status="Out")}

    assert qb_quality_score(ctx, "KC") == 0.50
    assert "capped 0.50" in qb_quality_label(ctx, "KC")
    wr_player = next(p for p in ctx.roster if p.player_id == WR)
    assert _factor(WRPicker(cfg), ctx, wr_player, "qb_quality").score == 0.50


# --------------------------------------------------------------------------------------
# Fallback visibility
# --------------------------------------------------------------------------------------


def test_fallback_flag_reaches_the_wr_te_and_dst_breakdowns():
    cfg = load_config()
    ctx = _consumer_ctx(12, fallback=True)
    wr_player = next(p for p in ctx.roster if p.player_id == WR)
    te_player = next(p for p in ctx.roster if p.player_id == TE)
    dst_player = next(p for p in ctx.roster if p.position == Position.DEF)

    assert FALLBACK_FLAG in _factor(WRPicker(cfg), ctx, wr_player, "qb_quality").raw_value
    assert FALLBACK_FLAG in _factor(TEPicker(cfg), ctx, te_player, "qb_quality").raw_value
    assert FALLBACK_FLAG in _factor(DefensePicker(cfg), ctx, dst_player, "opp_qb").raw_value
    assert FALLBACK_FLAG in _factor(FlexPicker(cfg), ctx, wr_player, "situation").raw_value


def test_listed_qb_carries_no_fallback_flag():
    cfg = load_config()
    ctx = _consumer_ctx(12, fallback=False)
    wr_player = next(p for p in ctx.roster if p.player_id == WR)
    assert FALLBACK_FLAG not in _factor(WRPicker(cfg), ctx, wr_player, "qb_quality").raw_value


def test_fallback_changes_the_flag_not_the_score():
    """The flag is warn-level provenance; the tier table treats both paths identically."""
    cfg = load_config()
    wr_player = next(p for p in _consumer_ctx(12).roster if p.player_id == WR)
    listed = _factor(WRPicker(cfg), _consumer_ctx(12), wr_player, "qb_quality").score
    derived = _factor(
        WRPicker(cfg), _consumer_ctx(12, fallback=True), wr_player, "qb_quality"
    ).score
    assert listed == derived


# --------------------------------------------------------------------------------------
# The QB picker must not see any of this
# --------------------------------------------------------------------------------------


def test_qb_picker_has_no_calibre_factor():
    """QB's equation is Style, PassCatcher, OLine, Matchup, SecondaryInjury, Baseline."""
    cfg = load_config()
    ctx = _consumer_ctx(1)
    qb = next(p for p in ctx.roster if p.position == Position.QB)
    names = {f.name for f in QBPicker(cfg).score_factors(ctx, qb)}
    assert not names & {"ranking", "player_calibre", "calibre", "qb_quality"}


def test_qb_start_score_identical_across_the_whole_calibre_range():
    """Move the QB from rank 1 to rank 99 — his own Start Score must not budge."""
    cfg = load_config()
    picker = QBPicker(cfg)
    scores = []
    for rank in (1, 20, 50, 99):
        ctx = _consumer_ctx(rank)
        qb = next(p for p in ctx.roster if p.position == Position.QB)
        scores.append([(f.name, f.score, f.weight) for f in picker.score_factors(ctx, qb)])
    assert all(s == scores[0] for s in scores)


def test_qb_start_score_identical_whether_listed_or_fallback():
    cfg = load_config()
    picker = QBPicker(cfg)
    listed = _consumer_ctx(1)
    derived = _consumer_ctx(1, fallback=True)
    qb = next(p for p in listed.roster if p.position == Position.QB)
    assert [(f.name, f.score) for f in picker.score_factors(listed, qb)] == [
        (f.name, f.score) for f in picker.score_factors(derived, qb)
    ]
