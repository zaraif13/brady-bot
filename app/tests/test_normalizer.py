from __future__ import annotations

from brady_bot.config import load_config
from brady_bot.normalizer import normalize_name, normalize_team


def test_normalize_name_suffix_and_apostrophe():
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("Kenneth Walker III") == "kenneth walker"
    assert normalize_name("Ka'imi Fairbairn") == "kaimi fairbairn"


def test_normalize_name_ignores_periods_in_initials():
    """Search keys collapse dotted initials so typing without '.' still matches."""
    assert normalize_name("A.J. Brown") == "aj brown"
    assert normalize_name("AJ Brown") == "aj brown"
    assert normalize_name("A.J. Brown") == normalize_name("AJ Brown")
    assert normalize_name("C.J. Stroud") == normalize_name("CJ Stroud") == "cj stroud"
    assert normalize_name("T.J. Hockenson") == normalize_name("TJ Hockenson")


def test_search_finds_dotted_name_without_periods():
    import polars as pl
    from brady_bot.players_index import PlayersIndex

    df = pl.DataFrame(
        {
            "gsis_id": ["ajb"],
            "display_name": ["A.J. Brown"],
            "short_name": ["A.J.Brown"],
            "position": ["WR"],
            "latest_team": ["PHI"],
            "headshot": [None],
            "last_season": [2026],
            "status": ["ACT"],
        }
    )
    idx = PlayersIndex(df, {})
    hits = idx.search("AJ Brown", "WR")
    assert hits and hits[0].name == "A.J. Brown"
    assert hits[0].name == "A.J. Brown"  # display name unchanged from catalog


def test_team_aliases():
    cfg = load_config()
    assert normalize_team("JAC", cfg.team_aliases) == "JAX"
    assert normalize_team("WSH", cfg.team_aliases) == "WAS"


def test_weights_sum_to_one():
    cfg = load_config()
    for key, block in cfg.weights.positions.items():
        assert abs(sum(block.values()) - 1.0) < 1e-9, key
