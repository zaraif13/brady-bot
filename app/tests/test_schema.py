"""Step 0 schema constants — must match docs/schema_probe.txt findings."""
from __future__ import annotations

from pathlib import Path

from brady_bot.sources import schema


def test_depth_chart_schema_constants():
    assert schema.DEPTH_GSIS_ID == "gsis_id"
    assert schema.DEPTH_POS_ABB == "pos_abb"
    assert schema.DEPTH_POS_RANK == "pos_rank"
    assert schema.DEPTH_DT == "dt"
    assert schema.DEPTH_STARTER_RANK == 1
    # Confirmed absent from live nflreadpy — do not reintroduce as primary keys
    assert schema.DEPTH_POS_ABB != "position"
    assert schema.DEPTH_POS_RANK != "depth_chart_order"


def test_snap_and_players_crosswalk_constants():
    assert schema.SNAP_PFR_PLAYER_ID == "pfr_player_id"
    assert schema.PLAYERS_PFR_ID == "pfr_id"
    assert schema.PLAYERS_GSIS_ID == "gsis_id"
    assert schema.SNAP_CROSSWALK_MIN_HIT_RATE == 0.95
    assert schema.SNAP_OFFENSE_PCT == "offense_pct"


def test_player_stats_interceptions_and_kicking():
    assert schema.PS_PASSING_INTERCEPTIONS == "passing_interceptions"
    assert schema.PS_PASSING_INTERCEPTIONS != "interceptions"
    assert schema.PS_FG_MADE == "fg_made"
    assert schema.PS_PAT_MADE == "pat_made"
    assert schema.PS_PLAYER_ID == "player_id"


def test_team_stats_real_columns_not_aggregates():
    assert schema.TS_PASSING_YARDS == "passing_yards"
    assert schema.TS_CARRIES == "carries"
    assert schema.TS_ATTEMPTS == "attempts"
    assert schema.TS_DEF_SACKS == "def_sacks"
    assert schema.TS_SACKS_SUFFERED == "sacks_suffered"
    assert "offense_yards" not in schema.TS_OFFENSE_YARDS_COLS
    assert schema.TS_PASSING_YARDS in schema.TS_OFFENSE_YARDS_COLS


def test_unit_pos_abb_covers_ol_secondary_front():
    assert "LT" in schema.OL_POS_ABB and "C" in schema.OL_POS_ABB
    assert "LCB" in schema.SECONDARY_POS_ABB and "FS" in schema.SECONDARY_POS_ABB
    assert "RILB" in schema.FRONT_SEVEN_POS_ABB or "MLB" in schema.FRONT_SEVEN_POS_ABB
    assert "LDT" in schema.FRONT_SEVEN_INTERIOR_POS_ABB or "NT" in schema.FRONT_SEVEN_INTERIOR_POS_ABB
    assert set(schema.UNIT_POS_ABB) >= {
        "OL",
        "SECONDARY",
        "FRONT_SEVEN",
        "FRONT_SEVEN_INTERIOR",
        "DEFENSE_ALL",
    }


def test_schema_probe_doc_exists():
    probe = Path(__file__).resolve().parents[1] / "docs" / "schema_probe.txt"
    assert probe.is_file(), "Run scripts/probe_schemas.py to generate docs/schema_probe.txt"
    text = probe.read_text()
    assert "pos_abb" in text
    assert "pfr_player_id" in text
    assert "passing_interceptions" in text
    assert "Assumption verdicts" in text


def test_fantasy_uses_passing_interceptions_constant():
    from brady_bot import fantasy

    assert schema.PS_PASSING_INTERCEPTIONS in fantasy.STAT_COLS
    assert "interceptions" not in fantasy.STAT_COLS
