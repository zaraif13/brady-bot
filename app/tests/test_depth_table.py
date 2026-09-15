"""Skill-column depth chart — flat QB/RB/WR/TE lists + O demotion."""
from __future__ import annotations

import polars as pl

from brady_bot.derive.depth_table import (
    DepthPlayer,
    apply_out_demotion,
    build_skill_columns,
    injury_marks_by_player,
)


def _depth(rows: list[dict]) -> pl.DataFrame:
    defaults = {"dt": "2026-09-13T12:00:00Z", "team": "BUF", "pos_grp": "3WR 1TE"}
    return pl.DataFrame([{**defaults, **r} for r in rows])


def _injuries(rows: list[dict]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame([{"week": 1, "team": "BUF", **r} for r in rows])


def _names(skill, pos: str) -> list[str]:
    return [p.player_name for p in skill.columns[pos]]


def test_skill_columns_are_flat_pos_rank_lists():
    skill = build_skill_columns(
        _depth(
            [
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 1, "player_name": "A", "gsis_id": "1"},
                {"pos_abb": "WR", "pos_slot": 2, "pos_rank": 2, "player_name": "B", "gsis_id": "2"},
                {"pos_abb": "WR", "pos_slot": 8, "pos_rank": 3, "player_name": "C", "gsis_id": "3"},
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 4, "player_name": "D", "gsis_id": "4"},
                {"pos_abb": "RB", "pos_slot": 11, "pos_rank": 1, "player_name": "RB1", "gsis_id": "5"},
                {"pos_abb": "QB", "pos_slot": 9, "pos_rank": 1, "player_name": "QB1", "gsis_id": "6"},
                {"pos_abb": "TE", "pos_slot": 10, "pos_rank": 1, "player_name": "TE1", "gsis_id": "7"},
                {"pos_abb": "LT", "pos_slot": 3, "pos_rank": 1, "player_name": "OL", "gsis_id": "8"},
            ]
        ),
        pl.DataFrame(),
        "BUF",
    )
    assert _names(skill, "WR") == ["A", "B", "C", "D"]
    assert _names(skill, "RB") == ["RB1"]
    assert _names(skill, "QB") == ["QB1"]
    assert _names(skill, "TE") == ["TE1"]
    # Non-skill positions are dropped from the TDC payload path.
    assert all(pos in ("QB", "RB", "WR", "TE") for pos in skill.columns)


def test_out_demotes_within_a_flat_column():
    skill = build_skill_columns(
        _depth(
            [
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 1, "player_name": "One", "gsis_id": "1"},
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 2, "player_name": "Two", "gsis_id": "2"},
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 3, "player_name": "Three", "gsis_id": "3"},
            ]
        ),
        _injuries([{"gsis_id": "1", "report_status": "Out"}]),
        "BUF",
    )
    assert _names(skill, "WR") == ["Two", "Three", "One"]
    assert skill.columns["WR"][2].injury_mark == "O"


def test_questionable_is_marked_without_reordering():
    skill = build_skill_columns(
        _depth(
            [
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "Starter", "gsis_id": "1"},
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 2, "player_name": "Backup", "gsis_id": "2"},
            ]
        ),
        _injuries([{"gsis_id": "1", "report_status": "Questionable"}]),
        "BUF",
    )
    assert _names(skill, "RB") == ["Starter", "Backup"]
    assert skill.columns["RB"][0].injury_mark == "Q"


def test_injury_marks_prefer_focus_week():
    marks = injury_marks_by_player(
        _injuries(
            [
                {"gsis_id": "P1", "week": 1, "report_status": "Out"},
                {"gsis_id": "P1", "week": 2, "report_status": "Questionable"},
            ]
        ),
        week=1,
    )
    assert marks == {"P1": "O"}


def test_demotion_keeps_relative_order_among_out_players():
    players = [
        DepthPlayer("a", "a", "O", 1),
        DepthPlayer("b", "b", None, 2),
        DepthPlayer("c", "c", "O", 3),
        DepthPlayer("d", "d", None, 4),
    ]
    assert [p.player_name for p in apply_out_demotion(players)] == ["b", "d", "a", "c"]


def test_unknown_team_yields_empty_columns():
    skill = build_skill_columns(
        _depth([{"pos_abb": "QB", "pos_slot": 1, "pos_rank": 1, "player_name": "A", "gsis_id": "1"}]),
        pl.DataFrame(),
        "KC",
    )
    assert skill.is_empty()
