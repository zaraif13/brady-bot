"""Opportunity Share "All" view — docs/depth-chart/opportunity_share.md Step 7.

The denominator rule is the thing worth guarding: a player's season-to-date share
averages only the weeks they qualified in. A missed week is absent, not a 0%.
"""
from __future__ import annotations

import polars as pl

from brady_bot.derive.opportunity_share import (
    build_all_view,
    build_week_view,
    is_bellcow,
)


def _stats(rows: list[dict]) -> pl.DataFrame:
    """Weekly player-stats frame with the columns the All view reads."""
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


def _row(view, player_id: str, team: str = "BUF"):
    return next(r for r in view.rows if r.player_id == player_id and r.team == team)


def test_missed_week_is_excluded_from_the_denominator():
    """20% then a missed week averages to 20%, not 10%."""
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.20},
                {"week": 2, "team": "BUF", "player_id": "P2", "player_display_name": "B",
                 "targets": 8, "target_share": 0.25},
            ]
        )
    )
    p1 = _row(view, "P1")
    assert p1.target_share_pct == 20.0
    assert p1.gp_tgt == 1
    assert p1.targets == 10


def test_zero_target_week_is_not_averaged_as_zero():
    """A played-but-targetless week is outside the Target Share population."""
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.30},
                {"week": 2, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 0, "target_share": 0.0},
            ]
        )
    )
    p1 = _row(view, "P1")
    assert p1.target_share_pct == 30.0
    assert p1.gp_tgt == 1


def test_target_share_is_mean_of_weekly_not_season_ratio():
    """10/100 then 30/50 means (10% + 60%) / 2 = 35%, not 40/150 = 26.7%."""
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.10},
                {"week": 2, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 30, "target_share": 0.60},
            ]
        )
    )
    p1 = _row(view, "P1")
    assert p1.target_share_pct == 35.0
    assert p1.targets == 40  # Qty is a sum, not a mean


def test_rush_share_denominator_includes_non_rb_carries():
    """A QB's scrambles are part of the team's rushing attempts."""
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "RB1", "player_display_name": "Back",
                 "position": "RB", "carries": 15},
                {"week": 1, "team": "BUF", "player_id": "QB1", "player_display_name": "Passer",
                 "position": "QB", "carries": 5},
            ]
        )
    )
    rb = _row(view, "RB1")
    assert rb.rush_share_pct == 75.0  # 15 / 20, not 15 / 15
    assert rb.carries == 15
    assert rb.gp_rsh == 1


def test_non_rb_rushers_are_not_in_the_rb_pool():
    """QBs contribute to the denominator but never get a rush share of their own."""
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "QB1", "player_display_name": "Passer",
                 "position": "QB", "carries": 5},
            ]
        )
    )
    assert all(r.rush_share_pct is None for r in view.rows)


def test_receiving_back_carries_both_metrics():
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "RB1", "player_display_name": "Back",
                 "position": "RB", "carries": 12, "targets": 4, "target_share": 0.20},
            ]
        )
    )
    rb = _row(view, "RB1")
    assert rb.rush_share_pct == 100.0
    assert rb.target_share_pct == 20.0
    assert rb.position == "RB"


def test_postseason_rows_are_dropped():
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.20},
                {"season_type": "POST", "week": 19, "team": "BUF", "player_id": "P1",
                 "player_display_name": "A", "targets": 10, "target_share": 0.80},
            ]
        )
    )
    assert _row(view, "P1").target_share_pct == 20.0
    assert view.completed_weeks == (1,)


def test_traded_player_is_tracked_per_team():
    view = build_all_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.20},
                {"week": 2, "team": "KC", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.40},
            ]
        )
    )
    assert _row(view, "P1", "BUF").target_share_pct == 20.0
    assert _row(view, "P1", "KC").target_share_pct == 40.0


def test_position_comes_from_the_players_latest_week():
    view = build_all_view(
        _stats(
            [
                {"week": 2, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "position": "TE", "targets": 5, "target_share": 0.10},
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "position": "WR", "targets": 5, "target_share": 0.10},
            ]
        )
    )
    assert _row(view, "P1").position == "TE"


def test_empty_stats_yield_an_empty_view():
    view = build_all_view(pl.DataFrame())
    assert view.is_empty()
    assert view.completed_weeks == ()


def test_target_share_is_derived_when_the_native_column_is_absent():
    df = _stats(
        [
            {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
             "targets": 10},
            {"week": 1, "team": "BUF", "player_id": "P2", "player_display_name": "B",
             "targets": 30},
        ]
    ).drop("target_share")
    view = build_all_view(df)
    assert _row(view, "P1").target_share_pct == 25.0


def test_week_view_returns_that_weeks_shares_only():
    view = build_week_view(
        _stats(
            [
                {"week": 1, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.20},
                {"week": 2, "team": "BUF", "player_id": "P1", "player_display_name": "A",
                 "targets": 10, "target_share": 0.40},
                {"week": 2, "team": "BUF", "player_id": "RB1", "player_display_name": "Back",
                 "position": "RB", "carries": 12},
                {"week": 2, "team": "BUF", "player_id": "QB1", "player_display_name": "Q",
                 "position": "QB", "carries": 4},
            ]
        ),
        week=2,
    )
    assert view.week == 2
    p1 = _row(view, "P1")
    assert p1.target_share_pct == 40.0
    assert p1.gp_tgt == 1
    rb = _row(view, "RB1")
    assert rb.rush_share_pct == 75.0  # 12 / 16
    assert rb.gp_rsh == 1


def test_bellcow_hard_cutoff():
    assert is_bellcow(60.0) is True
    assert is_bellcow(59.9) is False
    assert is_bellcow(None) is False
