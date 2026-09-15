"""Opportunity Share board — docs/depth-chart/opportunity_share.md Steps 3–7."""
from __future__ import annotations

import polars as pl

from brady_bot.derive.opportunity_board import (
    build_team_board,
    completed_weeks,
    compute_all_rows,
    compute_week_rows,
)


def _stats(rows: list[dict]) -> pl.DataFrame:
    defaults = {
        "season_type": "REG",
        "targets": 0,
        "carries": 0,
        "target_share": None,
        "position": "WR",
    }
    filled = [{**defaults, **r} for r in rows]
    return pl.DataFrame(
        filled,
        schema={
            "season_type": pl.Utf8,
            "week": pl.Int64,
            "team": pl.Utf8,
            "player_id": pl.Utf8,
            "player_display_name": pl.Utf8,
            "position": pl.Utf8,
            "targets": pl.Int64,
            "carries": pl.Int64,
            "target_share": pl.Float64,
        },
    )


def _pbp(rows: list[dict]) -> pl.DataFrame:
    defaults = {
        "season_type": "REG",
        "receiver_player_id": None,
        "rusher_player_id": None,
    }
    filled = [{**defaults, **r} for r in rows]
    return pl.DataFrame(
        filled,
        schema={
            "week": pl.Int64,
            "season_type": pl.Utf8,
            "posteam": pl.Utf8,
            "play_type": pl.Utf8,
            "yardline_100": pl.Int64,
            "receiver_player_id": pl.Utf8,
            "rusher_player_id": pl.Utf8,
        },
    )


def _find(rows, player_id: str):
    return next(r for r in rows if r["player_id"] == player_id)


def test_completed_weeks_from_reg_stats():
    weeks = completed_weeks(
        _stats(
            [
                {"week": 2, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 1, "target_share": 0.1},
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 1, "target_share": 0.1},
            ]
        )
    )
    assert weeks == (1, 2)


def test_week_denominator_and_rz_fill():
    stats = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "W1", "player_display_name": "Wr",
             "position": "WR", "targets": 5, "target_share": 0.5},
            {"week": 1, "team": "BUF", "player_id": "R1", "player_display_name": "Rb",
             "position": "RB", "carries": 12},
            {"week": 1, "team": "BUF", "player_id": "R2", "player_display_name": "Backup",
             "position": "RB", "carries": 8},
        ]
    )
    # Only W1 gets an RZ target; R1 has no RZ carry → 0.0 fill for rush population.
    pbp = _pbp(
        [
            {"week": 1, "posteam": "BUF", "play_type": "pass", "yardline_100": 10,
             "receiver_player_id": "W1"},
            {"week": 1, "posteam": "BUF", "play_type": "run", "yardline_100": 8,
             "rusher_player_id": "R2"},
            {"week": 1, "posteam": "BUF", "play_type": "run", "yardline_100": 50,
             "rusher_player_id": "R1"},
        ]
    )
    rows, mix = compute_week_rows(stats, pbp, 1, "BUF")
    assert mix.rz_plays == 2
    assert mix.rz_pass_pct == 50.0
    assert mix.rz_rush_pct == 50.0

    wr = _find(rows, "W1")
    assert wr["target_share_pct"] == 50.0
    assert wr["targets"] == 5
    assert wr["rush_share_pct"] is None
    assert wr["carries"] is None
    assert wr["rz_target_share_pct"] == 100.0
    assert wr["rz_targets"] == 1
    assert wr["rz_rush_share_pct"] is None

    rb1 = _find(rows, "R1")
    assert rb1["rush_share_pct"] == 60.0
    assert rb1["rz_rush_share_pct"] == 0.0
    assert rb1["rz_carries"] == 0
    assert rb1["bellcow"] is True

    rb2 = _find(rows, "R2")
    assert rb2["rush_share_pct"] == 40.0
    assert rb2["rz_rush_share_pct"] == 100.0
    assert rb2["bellcow"] is False


def test_rz_null_when_metric_does_not_apply():
    stats = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "W1", "player_display_name": "Wr",
             "targets": 3, "target_share": 1.0},
        ]
    )
    rows, mix = compute_week_rows(stats, pl.DataFrame(), 1, "BUF")
    assert mix.rz_plays == 0
    assert mix.rz_pass_pct is None
    wr = _find(rows, "W1")
    assert wr["rz_target_share_pct"] == 0.0
    assert wr["rz_targets"] == 0
    assert wr["rz_rush_share_pct"] is None


def test_all_view_mean_qty_sum_and_cumulative_rz_mix():
    stats = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "W1", "player_display_name": "Wr",
             "targets": 10, "target_share": 0.40},
            {"week": 2, "team": "BUF", "player_id": "W1", "player_display_name": "Wr",
             "targets": 5, "target_share": 0.20},
            # Missed week 3 entirely — must not pull average toward 0.
            {"week": 3, "team": "BUF", "player_id": "OTHER", "player_display_name": "X",
             "targets": 1, "target_share": 0.1},
            {"week": 1, "team": "BUF", "player_id": "R1", "player_display_name": "Rb",
             "position": "RB", "carries": 18},
            {"week": 1, "team": "BUF", "player_id": "R2", "player_display_name": "Rb2",
             "position": "RB", "carries": 2},
            {"week": 2, "team": "BUF", "player_id": "R1", "player_display_name": "Rb",
             "position": "RB", "carries": 10},
        ]
    )
    pbp = _pbp(
        [
            {"week": 1, "posteam": "BUF", "play_type": "pass", "yardline_100": 12,
             "receiver_player_id": "W1"},
            {"week": 1, "posteam": "BUF", "play_type": "run", "yardline_100": 5,
             "rusher_player_id": "R1"},
            {"week": 2, "posteam": "BUF", "play_type": "pass", "yardline_100": 15,
             "receiver_player_id": "W1"},
            {"week": 2, "posteam": "BUF", "play_type": "pass", "yardline_100": 18,
             "receiver_player_id": "W1"},
            {"week": 2, "posteam": "BUF", "play_type": "run", "yardline_100": 9,
             "rusher_player_id": "R1"},
        ]
    )
    rows, mix, weeks = compute_all_rows(stats, pbp, "BUF")
    assert weeks == (1, 2, 3)
    # Cumulative: week1 1pass+1run, week2 2pass+1run → 3/5 pass, 2/5 rush
    assert mix.rz_plays == 5
    assert mix.rz_pass_pct == 60.0
    assert mix.rz_rush_pct == 40.0

    wr = _find(rows, "W1")
    assert wr["target_share_pct"] == 30.0  # mean of 40 and 20
    assert wr["targets"] == 15  # sum
    assert wr["gp"] == 2
    assert wr["gp_tgt"] == 2
    assert wr["rz_targets"] == 3
    assert wr["rz_target_share_pct"] == 100.0

    rb = _find(rows, "R1")
    # week1: 18/20 = 90; week2: 10/10 = 100 → 95.0
    assert rb["rush_share_pct"] == 95.0
    assert rb["carries"] == 28
    assert rb["bellcow"] is True


def test_bellcow_hard_cutoff():
    stats = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "R1", "player_display_name": "Almost",
             "position": "RB", "carries": 599},
            {"week": 1, "team": "BUF", "player_id": "R2", "player_display_name": "Other",
             "position": "RB", "carries": 401},
        ]
    )
    rows, _ = compute_week_rows(stats, pl.DataFrame(), 1, "BUF")
    almost = _find(rows, "R1")
    assert almost["rush_share_pct"] == 59.9
    assert almost["bellcow"] is False

    stats60 = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "R1", "player_display_name": "Cow",
             "position": "RB", "carries": 60},
            {"week": 1, "team": "BUF", "player_id": "R2", "player_display_name": "Other",
             "position": "RB", "carries": 40},
        ]
    )
    rows60, _ = compute_week_rows(stats60, pl.DataFrame(), 1, "BUF")
    assert _find(rows60, "R1")["bellcow"] is True


def test_build_team_board_all_and_week():
    stats = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "W1", "player_display_name": "Wr",
             "targets": 4, "target_share": 1.0},
        ]
    )
    all_board = build_team_board(stats, pl.DataFrame(), "BUF", "all", season=2026)
    assert all_board["view"] == "all"
    assert all_board["season_group_label"] == "Season to Date"
    assert all_board["rows"]

    week_board = build_team_board(stats, pl.DataFrame(), "BUF", "1", season=2026)
    assert week_board["view"] == 1
    assert week_board["season_group_label"] == "Season"
