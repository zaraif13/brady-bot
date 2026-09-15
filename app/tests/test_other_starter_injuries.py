"""Other Starter Injuries — O/D starter counts for OL / DL / LBs / DBs."""
from __future__ import annotations

import polars as pl

from brady_bot.derive.other_starter_injuries import count_other_starter_injuries


def _depth(rows: list[dict]) -> pl.DataFrame:
    defaults = {"dt": "2026-09-13T12:00:00Z", "team": "BUF"}
    return pl.DataFrame([{**defaults, **r} for r in rows])


def _injuries(rows: list[dict]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame([{"week": 1, "team": "BUF", **r} for r in rows])


def test_counts_only_out_and_doubtful_starters():
    counts = count_other_starter_injuries(
        _depth(
            [
                {"pos_abb": "LT", "pos_rank": 1, "gsis_id": "OL1", "player_name": "LT"},
                {"pos_abb": "LG", "pos_rank": 1, "gsis_id": "OL2", "player_name": "LG"},
                {"pos_abb": "NT", "pos_rank": 1, "gsis_id": "DL1", "player_name": "NT"},
                {"pos_abb": "LCB", "pos_rank": 1, "gsis_id": "DB1", "player_name": "CB"},
                {"pos_abb": "WLB", "pos_rank": 1, "gsis_id": "LB1", "player_name": "LB"},
            ]
        ),
        _injuries(
            [
                {"gsis_id": "OL1", "report_status": "Out"},
                {"gsis_id": "OL2", "report_status": "Questionable"},
                {"gsis_id": "DL1", "report_status": "Doubtful"},
                {"gsis_id": "DB1", "report_status": "Out"},
                {"gsis_id": "LB1", "report_status": "Probable"},
            ]
        ),
        "BUF",
        week=1,
    )
    assert counts == {"OL": 1, "DL": 1, "LBs": 0, "DBs": 1}


def test_backups_are_not_counted():
    counts = count_other_starter_injuries(
        _depth(
            [
                {"pos_abb": "LT", "pos_rank": 1, "gsis_id": "OL1", "player_name": "Starter"},
                {"pos_abb": "LT", "pos_rank": 2, "gsis_id": "OL2", "player_name": "Backup"},
            ]
        ),
        _injuries([{"gsis_id": "OL2", "report_status": "Out"}]),
        "BUF",
        week=1,
    )
    assert counts["OL"] == 0


def test_only_exact_pos_abb_sets_count():
    """EDGE / CB / T are outside the Simplified Depth Chart unit lists."""
    counts = count_other_starter_injuries(
        _depth(
            [
                {"pos_abb": "EDGE", "pos_rank": 1, "gsis_id": "X1", "player_name": "Edge"},
                {"pos_abb": "CB", "pos_rank": 1, "gsis_id": "X2", "player_name": "CB"},
                {"pos_abb": "T", "pos_rank": 1, "gsis_id": "X3", "player_name": "T"},
            ]
        ),
        _injuries(
            [
                {"gsis_id": "X1", "report_status": "Out"},
                {"gsis_id": "X2", "report_status": "Out"},
                {"gsis_id": "X3", "report_status": "Out"},
            ]
        ),
        "BUF",
        week=1,
    )
    assert counts == {"OL": 0, "DL": 0, "LBs": 0, "DBs": 0}


def test_dedupes_player_appearing_twice():
    counts = count_other_starter_injuries(
        _depth(
            [
                {"pos_abb": "LCB", "pos_rank": 1, "gsis_id": "DB1", "player_name": "Same"},
                {"pos_abb": "NB", "pos_rank": 1, "gsis_id": "DB1", "player_name": "Same"},
            ]
        ),
        _injuries([{"gsis_id": "DB1", "report_status": "Out"}]),
        "BUF",
        week=1,
    )
    assert counts["DBs"] == 1


def test_falls_back_to_latest_week_at_or_before_focus():
    counts = count_other_starter_injuries(
        _depth([{"pos_abb": "C", "pos_rank": 1, "gsis_id": "OL1", "player_name": "Center"}]),
        _injuries(
            [
                {"gsis_id": "OL1", "week": 1, "report_status": "Out"},
                {"gsis_id": "OL1", "week": 3, "report_status": None},
            ]
        ),
        "BUF",
        week=2,
    )
    assert counts["OL"] == 1


def test_wrong_team_is_zero():
    counts = count_other_starter_injuries(
        _depth([{"pos_abb": "C", "pos_rank": 1, "gsis_id": "OL1", "player_name": "Center"}]),
        _injuries([{"gsis_id": "OL1", "report_status": "Out"}]),
        "KC",
        week=1,
    )
    assert counts == {"OL": 0, "DL": 0, "LBs": 0, "DBs": 0}


def test_empty_inputs_are_zeros():
    assert count_other_starter_injuries(pl.DataFrame(), pl.DataFrame(), "BUF") == {
        "OL": 0,
        "DL": 0,
        "LBs": 0,
        "DBs": 0,
    }
