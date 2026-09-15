"""Fantasy scoring — kicking, interceptions column, null-fill."""
from __future__ import annotations

import ast
from pathlib import Path

import polars as pl
import pytest

from brady_bot.config import LeagueConfig
from brady_bot.fantasy import STAT_COLS, score_player_games
from brady_bot.sources import schema


_KICK_SCORING = {
    "passing_yards_per_point": 30,
    "passing_td": 5,
    "interception": -2,
    "rushing_yards_per_point": 10,
    "rushing_td": 6,
    "receiving_yards_per_point": 10,
    "receiving_td": 6,
    "reception": 0.5,
    "fumble_lost": -2,
    "two_point_conversion": 2,
    "fg_0_19": 1,
    "fg_20_29": 2,
    "fg_30_39": 3,
    "fg_40_49": 4,
    "fg_50_plus": 5,
    "fg_missed_0_19": -2,
    "fg_missed_20_29": -1,
    "pat_made": 1,
    "pat_missed": -1,
}


def test_kicker_fantasy_points_distance_buckets_and_pat():
    """fg_made=2 / pat_made=3 style row must score > 0 with league K table."""
    cfg = LeagueConfig(raw={}, season=2026, scoring=_KICK_SCORING)
    # 1×30–39 (3) + 1×40–49 (4) + 3 PAT = 10; one 20–29 miss (−1) → 9
    row = pl.DataFrame(
        [
            {
                "player_id": "00-kicker",
                "position": "K",
                "fg_made": 2,
                "pat_made": 3,
                "fg_made_0_19": 0,
                "fg_made_20_29": 0,
                "fg_made_30_39": 1,
                "fg_made_40_49": 1,
                "fg_made_50_59": 0,
                "fg_made_60_": 0,
                "fg_missed_0_19": 0,
                "fg_missed_20_29": 1,
                "pat_missed": 0,
            }
        ]
    )
    scored = score_player_games(row, cfg)
    assert scored["fantasy_points"][0] == pytest.approx(9.0)


def test_kicker_stat_cols_include_distance_buckets():
    assert schema.PS_FG_MADE_30_39 in STAT_COLS
    assert schema.PS_PAT_MADE in STAT_COLS
    assert schema.PS_FG_MISSED_0_19 in STAT_COLS
    assert "interceptions" not in STAT_COLS
    assert schema.PS_PASSING_INTERCEPTIONS in STAT_COLS


def test_null_stat_does_not_zero_out_other_fantasy_terms():
    """Null receiving_yards must not null-propagate and wipe passing points."""
    cfg = LeagueConfig(raw={}, season=2026, scoring=_KICK_SCORING)
    row = pl.DataFrame(
        [
            {
                "player_id": "00-qb",
                "position": "QB",
                "passing_yards": 300,
                "passing_tds": 2,
                "passing_interceptions": None,
                "receiving_yards": None,
                "receptions": None,
            }
        ]
    )
    scored = score_player_games(row, cfg)
    # 300/30 + 2*5 = 20; null INT/rec treated as 0
    assert scored["fantasy_points"][0] == pytest.approx(20.0)


def _string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def test_no_bare_interceptions_column_in_derive_or_fantasy():
    """Bare 'interceptions' as a column name would silently score 0 INTs."""
    src_root = Path(__file__).resolve().parents[1] / "src" / "brady_bot"
    targets = [
        src_root / "fantasy.py",
        *sorted((src_root / "derive").glob("*.py")),
    ]
    offenders: list[str] = []
    for path in targets:
        for lit in _string_literals(path):
            if lit == "interceptions":
                offenders.append(str(path.relative_to(src_root)))
                break
    assert offenders == [], f"bare 'interceptions' column still referenced in {offenders}"
