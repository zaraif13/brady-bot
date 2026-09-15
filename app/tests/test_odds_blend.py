from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import polars as pl

from brady_bot.derive.blending import is_blended_week
from brady_bot.derive.context import _games_from_schedules
from brady_bot.sources.cache import CacheStore
from brady_bot.sources.odds import average_odds_to_games, fetch_odds


def test_average_odds_and_schedule_match_prefer_odds():
    events = [
        {
            "id": "ev1",
            "home_team": "Kansas City Chiefs",
            "away_team": "Buffalo Bills",
            "bookmakers": [
                {
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Kansas City Chiefs", "point": -3.5},
                                {"name": "Buffalo Bills", "point": 3.5},
                            ],
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "point": 48.5},
                                {"name": "Under", "point": 48.5},
                            ],
                        },
                    ]
                }
            ],
        }
    ]
    odds_map = average_odds_to_games(events)
    assert "Kansas City Chiefs" in odds_map
    assert odds_map["Kansas City Chiefs"]["game_total"] == 48.5

    schedules = pl.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "home_team": "KC",
                "away_team": "BUF",
                "game_id": "2026_01_BUF_KC",
                "total_line": 40.0,
                "spread_line": -1.0,
            }
        ]
    )
    games = _games_from_schedules(schedules, 2026, 1, odds_map, {}, odds_unavailable=False)
    assert games["KC"].game_total == 48.5
    assert games["KC"].spread == -3.5
    assert games["KC"].home_implied_total == 26.0  # 48.5/2 + 3.5/2
    assert games["BUF"].away_implied_total == 22.5


def test_fetch_odds_missing_key_soft_warning(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    keys = tmp_path / "api_keys.json"
    keys.write_text(
        '{"apis":[{"id":"the_odds_api","label":"The Odds API","key":"","updated_at":"x"}]}\n'
    )
    cache = CacheStore(root=tmp_path / "cache")
    events, unavailable, warn = fetch_odds(cache, keys_path=keys)
    assert events == []
    assert unavailable is True
    assert warn is not None
    assert "ODDS_API_KEY missing" in warn


def test_fetch_odds_invalid_key_soft_warning(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    keys = tmp_path / "api_keys.json"
    keys.write_text(
        '{"apis":[{"id":"the_odds_api","label":"The Odds API","key":"bad-key","updated_at":"x"}]}\n'
    )
    cache = CacheStore(root=tmp_path / "cache")

    def fake_get(url, params=None):
        req = httpx.Request("GET", url)
        return httpx.Response(
            401,
            request=req,
            json={
                "message": "API key is not valid. Get an API key at https://the-odds-api.com",
                "error_code": "INVALID_KEY",
            },
        )

    with patch("brady_bot.sources.odds.httpx.Client") as client_cls:
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.get.side_effect = fake_get
        client_cls.return_value = client
        events, unavailable, warn = fetch_odds(cache, refresh_odds=True, keys_path=keys)

    assert events == []
    assert unavailable is True
    assert warn == "Odds API key invalid; using schedule lines"


def test_blend_flag_without_user_warning_string():
    """Week 1 still blends internally; warning text must not be the noisy ranks message."""
    assert is_blended_week(1)
    # The noisy string is no longer appended in build_week_context; assert helper contract
    noisy = "Ranks blended with prior season through Week 4"
    import inspect
    from brady_bot.derive import context as ctx_mod

    src = inspect.getsource(ctx_mod.build_week_context)
    assert noisy not in src
    assert "blended=is_blended_week(week)" in src
