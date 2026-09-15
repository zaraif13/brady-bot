from __future__ import annotations

import polars as pl

from brady_bot.players_index import PlayersIndex
from brady_bot.sources.nflverse import team_logo_map


def test_slot_filters():
    df = pl.DataFrame(
        {
            "gsis_id": ["1", "2", "3", "4"],
            "display_name": ["Alpha QB", "Beta RB", "Gamma WR", "Delta TE"],
            "short_name": ["A.QB", "B.RB", "G.WR", "D.TE"],
            "position": ["QB", "RB", "WR", "TE"],
            "latest_team": ["KC", "SF", "DAL", "DET"],
            "headshot": [None, None, None, None],
            "last_season": [2026, 2026, 2026, 2026],
            "status": ["ACT", "ACT", "ACT", "ACT"],
        }
    )
    idx = PlayersIndex(df, {})
    qb = idx.search("Alpha", "QB")
    assert qb and qb[0].position == "QB"
    flex = idx.search("Beta", "FLEX")
    assert flex and flex[0].position == "RB"
    wrong = idx.search("Alpha", "RB")
    assert wrong == []
    defs = idx.search("Jets", "DEF")
    assert any(h.position == "DEF" for h in defs)


def test_def_search_includes_team_logo():
    df = pl.DataFrame(
        {
            "gsis_id": ["1"],
            "display_name": ["Dummy QB"],
            "short_name": ["D.QB"],
            "position": ["QB"],
            "latest_team": ["KC"],
            "headshot": [None],
            "last_season": [2026],
            "status": ["ACT"],
        }
    )
    logos = {"NYJ": "https://example.com/jets.png", "SF": "https://example.com/sf.png"}
    idx = PlayersIndex(df, {}, logos=logos)
    hits = idx.search("Jets", "DEF")
    assert hits
    jet = next(h for h in hits if h.team == "NYJ")
    assert jet.headshot == "https://example.com/jets.png"
    player = idx.to_player("DEF-SF")
    assert player is not None
    assert player.headshot == "https://example.com/sf.png"


def test_team_logo_map_prefers_espn_column():
    teams = pl.DataFrame(
        {
            "team_abbr": ["KC", "SF"],
            "team_logo_espn": ["https://cdn/kc.png", "https://cdn/sf.png"],
        }
    )
    m = team_logo_map(teams, {})
    assert m["KC"] == "https://cdn/kc.png"
    assert m["SF"] == "https://cdn/sf.png"
