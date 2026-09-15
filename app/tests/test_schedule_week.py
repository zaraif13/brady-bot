from __future__ import annotations

from datetime import datetime, timezone

import polars as pl

from brady_bot.schedule_week import (
    bye_teams_for_week,
    opponents_for_week,
    resolve_focus_week,
)


def _sched_rows(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows)


def test_focus_stays_on_week1_while_any_game_incomplete():
    # Mid-week: some Week 1 games done, some not — still focus week 1
    # even if "today" is after Week 1 kickoff dates and Week 2 exists
    rows = []
    for week in (1, 2):
        for i in range(16):
            home = f"H{week}{i:02d}"
            away = f"A{week}{i:02d}"
            done = week == 1 and i < 10  # 10 of 16 week-1 games complete
            rows.append(
                {
                    "season": 2026,
                    "week": week,
                    "game_type": "REG",
                    "home_team": home,
                    "away_team": away,
                    "home_score": 20 if done else None,
                    "away_score": 17 if done else None,
                    "gameday": "2026-09-07" if week == 1 else "2026-09-14",
                }
            )
    df = _sched_rows(rows)
    # "now" mid Week 1 after some games — must NOT jump to week 2
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    assert resolve_focus_week(df, 2026, now=now) == 1


def test_focus_advances_when_all_week1_complete():
    rows = []
    for week in (1, 2):
        for i in range(16):
            done = week == 1  # all week 1 complete; week 2 incomplete
            rows.append(
                {
                    "season": 2026,
                    "week": week,
                    "game_type": "REG",
                    "home_team": f"H{week}{i:02d}",
                    "away_team": f"A{week}{i:02d}",
                    "home_score": 21 if done else None,
                    "away_score": 14 if done else None,
                }
            )
    assert resolve_focus_week(_sched_rows(rows), 2026) == 2


def test_opponents_and_bye():
    # Use real NFL abbreviations so BYE map covers full league
    rows = [
        {
            "season": 2026,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "LAC",
            "home_score": None,
            "away_score": None,
        },
        {
            "season": 2026,
            "week": 1,
            "game_type": "REG",
            "home_team": "BUF",
            "away_team": "NYJ",
            "home_score": None,
            "away_score": None,
        },
    ]
    aliases = {}
    opps = opponents_for_week(_sched_rows(rows), 2026, 1, aliases)
    assert opps["KC"] == "LAC"
    assert opps["LAC"] == "KC"
    assert opps["BUF"] == "NYJ"
    assert opps["SF"] == "BYE"
    byes = bye_teams_for_week(_sched_rows(rows), 2026, 1, aliases)
    assert "SF" in byes
    assert "KC" not in byes


def test_ignores_non_reg_games():
    rows = [
        {
            "season": 2026,
            "week": 1,
            "game_type": "REG",
            "home_team": "KC",
            "away_team": "LAC",
            "home_score": None,
            "away_score": None,
        },
        {
            "season": 2026,
            "week": 1,
            "game_type": "PRE",
            "home_team": "SF",
            "away_team": "SEA",
            "home_score": None,
            "away_score": None,
        },
    ]
    assert resolve_focus_week(_sched_rows(rows), 2026) == 1
    opps = opponents_for_week(_sched_rows(rows), 2026, 1, {})
    assert opps["KC"] == "LAC"
    assert opps["SF"] == "BYE"  # preseason ignored
