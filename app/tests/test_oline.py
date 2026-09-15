"""S10 O-line quality ranks — config load + RB/DEF consumers."""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from brady_bot.config import ConfigError, _load_oline_ranks, load_config
from brady_bot.models import Player, Position, TeamStats
from brady_bot.pickers.defense import DefensePicker
from brady_bot.pickers.rb import RBPicker
from brady_bot.players_index import NFL_TEAMS
from brady_bot.scoring.shared import oline_quality_tier
from test_pickers import _fixture_ctx


def test_load_config_oline_ranks_complete():
    cfg = load_config()
    assert len(cfg.oline_ranks) == 32
    assert set(cfg.oline_ranks) == set(NFL_TEAMS)
    assert sorted(cfg.oline_ranks.values()) == list(range(1, 33))
    assert cfg.oline_ranks["DEN"] == 1
    assert cfg.oline_ranks["HOU"] == 32
    assert cfg.oline_ranks["KC"] == 24
    assert cfg.oline_ranks["BUF"] == 4
    assert "WSH" not in cfg.oline_ranks
    assert cfg.oline_ranks["WAS"] == 31


def test_oline_ranks_halt_on_missing_team(tmp_path: Path):
    ranks = {t: i + 1 for i, t in enumerate(NFL_TEAMS)}
    del ranks["KC"]
    raw = {"oline_ranks": ranks}
    with pytest.raises(ConfigError, match=r"31 teams|missing"):
        _load_oline_ranks(raw, {})


def test_oline_ranks_halt_on_duplicate_rank():
    ranks = {t: i + 1 for i, t in enumerate(NFL_TEAMS)}
    ranks["KC"] = 1  # clash with DEN
    with pytest.raises(ConfigError, match=r"duplicates|contiguous"):
        _load_oline_ranks({"oline_ranks": ranks}, {})


def test_oline_ranks_halt_on_bad_code():
    ranks = {t: i + 1 for i, t in enumerate(NFL_TEAMS)}
    ranks["ZZZ"] = ranks.pop("KC")
    with pytest.raises(ConfigError, match=r"unrecognized"):
        _load_oline_ranks({"oline_ranks": ranks}, {})


def test_oline_ranks_normalizes_wsh_alias():
    ranks = {t: i + 1 for i, t in enumerate(t for t in NFL_TEAMS if t != "WAS")}
    ranks["WSH"] = 32  # ESPN code → WAS via aliases
    out = _load_oline_ranks({"oline_ranks": ranks}, {"WSH": "WAS"})
    assert out["WAS"] == 32
    assert "WSH" not in out
    assert len(out) == 32


def test_oline_quality_tier_bands():
    assert oline_quality_tier(4) == 1.0  # BUF
    assert oline_quality_tier(24) == 0.25  # KC
    assert oline_quality_tier(30) == 0.0  # CIN


def test_rb_oline_uses_s10_rank_not_team_stats():
    cfg = load_config()
    picker = RBPicker(cfg)
    rb = Player(player_id="R1", name="Back", team="BUF", position=Position.RB)
    ctx = _fixture_ctx([rb])
    ctx.oline_ranks = dict(cfg.oline_ranks)
    ctx.injury_counts["BUF"] = {
        "OL": 1,
        "SECONDARY": 0,
        "FRONT_SEVEN": 0,
        "FRONT_SEVEN_INTERIOR": 0,
        "DEFENSE_ALL": 0,
    }
    # Poison team_stats so a regression to run_block_rank would fail oddly
    ctx.team_stats["BUF"] = TeamStats(
        team="BUF",
        season=2026,
        through_week=5,
        offense_rank=16,
        total_defense_rank=16,
        scoring_efficiency_rank=16,
        defense_calibre_rank=16,
        qb_turnover_rank=16,
    )
    ol = next(f for f in picker.score_factors(ctx, rb) if f.name == "oline")
    # BUF rank 4 → 1.00 × 0.75 (one OL out) = 0.75
    assert abs(ol.score - 0.75) < 1e-9
    assert "rank=4" in (ol.raw_value or "")

    kc = Player(player_id="R2", name="KC Back", team="KC", position=Position.RB)
    ctx2 = _fixture_ctx([kc])
    ctx2.oline_ranks = dict(cfg.oline_ranks)
    ol_kc = next(f for f in picker.score_factors(ctx2, kc) if f.name == "oline")
    # KC rank 24 → 0.25 × 1.00
    assert abs(ol_kc.score - 0.25) < 1e-9


def test_def_opp_oline_uses_s10_and_13_22_band():
    cfg = load_config()
    picker = DefensePicker(cfg)
    ctx = _fixture_ctx(
        [Player(player_id="DEF-SF", name="49ers", team="SF", position=Position.DEF)]
    )
    ctx.oline_ranks = dict(cfg.oline_ranks)
    # LV = 21, CAR = 22 → average band 13–22 → 0.50
    for weak in ("LV", "CAR"):
        assert abs(picker._opp_ol(ctx, weak) - 0.50) < 1e-9

    # DEN = 1 elite → 0.10
    assert abs(picker._opp_ol(ctx, "DEN") - 0.10) < 1e-9

    # HOU = 32 weak + 2 OL out → 1.00
    ctx.injury_counts["HOU"] = {
        "OL": 2,
        "SECONDARY": 0,
        "FRONT_SEVEN": 0,
        "FRONT_SEVEN_INTERIOR": 0,
        "DEFENSE_ALL": 0,
    }
    assert abs(picker._opp_ol(ctx, "HOU") - 1.0) < 1e-9

    # JAX = 23, healthy → caught by 23–32 OR arm → 0.85
    assert abs(picker._opp_ol(ctx, "JAX") - 0.85) < 1e-9


def test_retired_oline_proxies_removed_from_source():
    from brady_bot.derive import team_ranks as mod
    from brady_bot import models

    src = inspect.getsource(mod)
    assert "run_block_rank" not in src
    assert "sack_rate_allowed_rank" not in src
    assert "_rush_ypa" not in src
    assert "_sack_rate_allowed" not in src
    fields = models.TeamStats.model_fields
    assert "run_block_rank" not in fields
    assert "sack_rate_allowed_rank" not in fields
