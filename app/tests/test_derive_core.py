from __future__ import annotations

import polars as pl
import pytest

from brady_bot.config import LeagueConfig
from brady_bot.derive.adj_fpa import derive_adj_fpa, matchup_score
from brady_bot.derive.blending import (
    blend_weights,
    is_blended_week,
    prior_season_week_window,
    rb_prior_snap_week_window,
)
from brady_bot.derive.calibre import derive_player_calibre
from brady_bot.derive.injuries import (
    build_injury_map,
    is_unavailable,
    normalize_practice_status,
    normalize_report_status,
)
from brady_bot.derive.roles import derive_snap_shares
from brady_bot.models import InjuryRecord


def test_blend_weights():
    assert blend_weights(1) == (1.0, 0.0)
    assert blend_weights(5) == (0.0, 1.0)
    assert is_blended_week(4)
    assert not is_blended_week(5)


def test_prior_season_week_window():
    assert prior_season_week_window(18) == (15, 18)
    assert prior_season_week_window(17) == (14, 17)
    assert prior_season_week_window(3) == (1, 3)
    assert prior_season_week_window(1) == (1, 1)


def test_rb_prior_snap_week_window():
    assert rb_prior_snap_week_window(18) == (10, 18)
    assert rb_prior_snap_week_window(12) == (10, 12)


def test_injury_availability_table():
    assert is_unavailable("Out", "Full")
    assert is_unavailable("Doubtful", None)
    assert is_unavailable("Questionable", "DNP")
    assert is_unavailable("Questionable", "Limited")
    assert is_unavailable("Questionable", None)
    assert not is_unavailable("Questionable", "Full")
    assert not is_unavailable(None, "DNP")
    rec = InjuryRecord(player_id="1", report_status="Out")
    assert rec.is_unavailable


def test_normalize_nflverse_practice_strings():
    assert normalize_practice_status("Full Participation in Practice") == "Full"
    assert normalize_practice_status("Limited Participation in Practice") == "Limited"
    assert normalize_practice_status("Did Not Participate") == "DNP"
    assert normalize_practice_status("DNP") == "DNP"
    assert normalize_practice_status(None) is None


def test_normalize_report_status_injury_status_md():
    assert normalize_report_status("O") == "Out"
    assert normalize_report_status("Out") == "Out"
    assert normalize_report_status("D") == "Doubtful"
    assert normalize_report_status("Q") == "Questionable"
    assert normalize_report_status("P") == "Probable"
    assert normalize_report_status("IR") == "IR"
    assert normalize_report_status("Injured Reserve") == "IR"
    assert normalize_report_status("PUP") == "PUP"
    assert normalize_report_status("NFI") == "NFI"
    assert not is_unavailable("Probable", None)
    assert is_unavailable("IR", None)
    assert is_unavailable("PUP", None)
    assert is_unavailable("NFI", None)


def test_build_injury_map_accepts_nflverse_practice_strings():
    df = pl.DataFrame(
        {
            "gsis_id": ["p1", "p2"],
            "week": [1, 1],
            "report_status": ["Questionable", "Out"],
            "practice_status": [
                "Full Participation in Practice",
                "Did Not Participate",
            ],
        }
    )
    m = build_injury_map(df, 1)
    assert m["p1"].practice_status == "Full"
    assert not m["p1"].is_unavailable
    assert m["p2"].report_status == "Out"
    assert m["p2"].is_unavailable


def test_matchup_score_percentile_direction():
    adj = {f"T{i}": float(i) for i in range(1, 33)}
    # lowest FPA = strongest D = rank 1 = score 0
    softest = max(adj, key=adj.get)
    hardest = min(adj, key=adj.get)
    assert matchup_score(adj, hardest, "percentile") == 0.0
    assert matchup_score(adj, softest, "percentile") == 1.0


def test_matchup_score_linear():
    assert matchup_score({"X": 0.0}, "X", "linear") == 0.5
    assert matchup_score({"X": 10.0}, "X", "linear") == 1.0


def test_adj_fpa_per_game_and_nulls():
    rows = []
    teams = [f"T{i:02d}" for i in range(1, 33)]
    for week in (1, 2):
        for i, team in enumerate(teams):
            rows.append(
                {
                    "season": 2026,
                    "season_type": "REG",
                    "week": week,
                    "position": "QB",
                    "opponent_team": team,
                    "passing_yards": 200.0 if week == 1 else None,
                    "passing_tds": 2,
                    "passing_interceptions": 0,
                    "rushing_yards": 0,
                    "rushing_tds": 0,
                    "receiving_yards": None,
                    "receiving_tds": None,
                    "receptions": None,
                    "rushing_fumbles_lost": 0,
                    "receiving_fumbles_lost": 0,
                    "passing_2pt_conversions": 0,
                    "rushing_2pt_conversions": 0,
                    "receiving_2pt_conversions": 0,
                }
            )
    # Team T01 only played week 1 — ensure per-game not sum bias handled by n_unique weeks
    df = pl.DataFrame(rows)
    # remove T01 week 2
    df = df.filter(~((pl.col("opponent_team") == "T01") & (pl.col("week") == 2)))
    cfg = LeagueConfig(raw={}, season=2026, scoring={
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
    })
    result = derive_adj_fpa(df, pl.DataFrame(), "QB", 2026, 2, cfg, week=5)
    assert len(result) == 32


def _qb_rows(season: int, weeks: list[int], teams: list[str], ppg_bias: float = 0.0) -> list[dict]:
    rows = []
    for week in weeks:
        for i, team in enumerate(teams):
            rows.append(
                {
                    "season": season,
                    "season_type": "REG",
                    "week": week,
                    "position": "QB",
                    "opponent_team": team,
                    "passing_yards": 250.0 + ppg_bias * 10 + i,
                    "passing_tds": 2,
                    "passing_interceptions": 0,
                    "rushing_yards": 0,
                    "rushing_tds": 0,
                    "receiving_yards": None,
                    "receiving_tds": None,
                    "receptions": None,
                    "rushing_fumbles_lost": 0,
                    "receiving_fumbles_lost": 0,
                    "passing_2pt_conversions": 0,
                    "rushing_2pt_conversions": 0,
                    "receiving_2pt_conversions": 0,
                }
            )
    return rows


_SCORING = {
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
}


def test_adj_fpa_week1_uses_prior_last_4_weeks_only():
    """Week 1 uses prior last-4 REG weeks; early prior weeks must not affect rates."""
    teams = [f"T{i:02d}" for i in range(1, 33)]
    cfg = LeagueConfig(raw={}, season=2026, scoring=_SCORING)
    # Early weeks: inflate T01 hugely; last-4 weeks: mild bias
    early = _qb_rows(2025, list(range(1, 15)), teams, ppg_bias=50.0)
    late = _qb_rows(2025, [15, 16, 17, 18], teams, ppg_bias=1.0)
    # Make T01 uniquely soft only in early weeks (already via ppg_bias on all — differentiate)
    for row in early:
        if row["opponent_team"] == "T01":
            row["passing_yards"] = 900.0
    for row in late:
        if row["opponent_team"] == "T01":
            row["passing_yards"] = 260.0
    current = _qb_rows(2026, [1], teams[:10], ppg_bias=0.0)
    df_full = pl.DataFrame(early + late + current)
    df_late_only = pl.DataFrame(late + current)

    full = derive_adj_fpa(
        df_full, pl.DataFrame(), "QB", 2026, 0, cfg, week=1, prior_week_lo=15, prior_week_hi=18
    )
    late_only = derive_adj_fpa(
        df_late_only, pl.DataFrame(), "QB", 2026, 0, cfg, week=1, prior_week_lo=15, prior_week_hi=18
    )
    assert len(full) == 32
    for t in teams:
        assert abs(full[t] - late_only[t]) < 1e-6


def test_snap_shares_ignore_prior_weeks_before_w10():
    rows = []
    for week, pct in [(9, 90.0), (10, 40.0), (14, 40.0), (15, 40.0), (16, 40.0), (17, 40.0), (18, 40.0)]:
        rows.append(
            {
                "season": 2025,
                "week": week,
                "gsis_id": "RB1",
                "team": "SEA",
                "offense_pct": pct,
            }
        )
    prior = pl.DataFrame(rows)
    shares = derive_snap_shares(
        pl.DataFrame(),
        2026,
        0,
        prior_snaps=prior,
        week=1,
        prior_week_lo=10,
        prior_week_hi=18,
    )
    assert abs(shares["RB1"] - 0.40) < 1e-6


def test_snap_shares_crosswalk_pfr_to_gsis():
    """Picker-facing dict must be keyed by gsis_id, not pfr_player_id."""
    from brady_bot.derive.roles import derive_snap_shares

    snaps = pl.DataFrame(
        {
            "season": [2026, 2026],
            "week": [1, 1],
            "pfr_player_id": ["BarkSa00", "Other00"],
            "team": ["PHI", "DAL"],
            "offense_pct": [72.0, 30.0],
        }
    )
    players = pl.DataFrame(
        {
            "pfr_id": ["BarkSa00", "Other00"],
            "gsis_id": ["00-0034844", "00-OTHER"],
        }
    )
    shares = derive_snap_shares(snaps, 2026, 1, week=5, players=players)
    assert "BarkSa00" not in shares
    assert "00-0034844" in shares
    assert abs(shares["00-0034844"] - 0.72) < 1e-6
    assert abs(shares["00-OTHER"] - 0.30) < 1e-6


def test_snap_crosswalk_halts_below_95_percent_hit_rate():
    """Synthetic ~90% hit rate must raise SnapCrosswalkError (live data always passes)."""
    import pytest
    from brady_bot.derive.roles import SnapCrosswalkError, derive_snap_shares

    # 10 unique PFR ids, only 9 map → 90% < 95%
    pfr_ids = [f"Pfr{i:02d}" for i in range(10)]
    snaps = pl.DataFrame(
        {
            "season": [2026] * 10,
            "week": [1] * 10,
            "pfr_player_id": pfr_ids,
            "team": ["SEA"] * 10,
            "offense_pct": [50.0] * 10,
        }
    )
    players = pl.DataFrame(
        {
            "pfr_id": pfr_ids[:9],  # miss Pfr09
            "gsis_id": [f"00-GSIS{i:02d}" for i in range(9)],
        }
    )
    with pytest.raises(SnapCrosswalkError, match=r"90\.0%|9/10|below minimum 95%"):
        derive_snap_shares(snaps, 2026, 1, week=5, players=players)


def test_snap_crosswalk_requires_players_when_pfr_present():
    import pytest
    from brady_bot.derive.roles import SnapCrosswalkError, derive_snap_shares

    snaps = pl.DataFrame(
        {
            "season": [2026],
            "week": [1],
            "pfr_player_id": ["BarkSa00"],
            "team": ["PHI"],
            "offense_pct": [70.0],
        }
    )
    with pytest.raises(SnapCrosswalkError, match="players catalog was not provided"):
        derive_snap_shares(snaps, 2026, 1, week=5, players=None)


def test_calibre_fallback_uses_full_prior_season():
    cfg = LeagueConfig(raw={}, season=2026, scoring=_SCORING)
    rows = []
    # Current season: only 1 game (< min_games=3) → fall back to prior
    rows.append(
        {
            "season": 2026,
            "season_type": "REG",
            "week": 1,
            "player_id": "P1",
            "position": "RB",
            "rushing_yards": 10,
            "rushing_tds": 0,
            "receiving_yards": 0,
            "receiving_tds": 0,
            "receptions": 0,
            "rushing_fumbles_lost": 0,
            "receiving_fumbles_lost": 0,
            "passing_yards": None,
            "passing_tds": None,
            "passing_interceptions": None,
            "passing_2pt_conversions": 0,
            "rushing_2pt_conversions": 0,
            "receiving_2pt_conversions": 0,
        }
    )
    # Prior early: huge; prior late: modest — fallback must use late only
    for week, yards in [(1, 200), (10, 200), (15, 40), (16, 40), (17, 40), (18, 40)]:
        rows.append(
            {
                "season": 2025,
                "season_type": "REG",
                "week": week,
                "player_id": "P1",
                "position": "RB",
                "rushing_yards": yards,
                "rushing_tds": 0,
                "receiving_yards": 0,
                "receiving_tds": 0,
                "receptions": 0,
                "rushing_fumbles_lost": 0,
                "receiving_fumbles_lost": 0,
                "passing_yards": None,
                "passing_tds": None,
                "passing_interceptions": None,
                "passing_2pt_conversions": 0,
                "rushing_2pt_conversions": 0,
                "receiving_2pt_conversions": 0,
            }
        )
    # Filler player with enough current games so ranks exist
    for week in (1, 2, 3):
        rows.append(
            {
                "season": 2026,
                "season_type": "REG",
                "week": week,
                "player_id": "P2",
                "position": "RB",
                "rushing_yards": 50,
                "rushing_tds": 0,
                "receiving_yards": 0,
                "receiving_tds": 0,
                "receptions": 0,
                "rushing_fumbles_lost": 0,
                "receiving_fumbles_lost": 0,
                "passing_yards": None,
                "passing_tds": None,
                "passing_interceptions": None,
                "passing_2pt_conversions": 0,
                "rushing_2pt_conversions": 0,
                "receiving_2pt_conversions": 0,
            }
        )
    df = pl.DataFrame(rows)
    ranks = derive_player_calibre(df, "RB", 2026, 1, cfg, min_games=3)
    assert "P1" in ranks
    # Full prior season includes week-1 boom → P1 outranks P2 on current-season games alone
    assert ranks["P1"] < ranks["P2"]


def test_injury_counts_pins_latest_week_no_duplicate_starters():
    """Multi-week depth must not inflate OL counts for the same starter."""
    from brady_bot.derive.injuries import derive_injury_counts

    depth = pl.DataFrame(
        {
            "week": [1, 2, 3, 3],
            "team": ["KC", "KC", "KC", "KC"],
            "gsis_id": ["OL1", "OL1", "OL1", "OL2"],
            "position": ["C", "C", "C", "LT"],
            "depth_chart_order": [1, 1, 1, 1],
        }
    )
    injuries = pl.DataFrame(
        {
            "week": [3, 3],
            "gsis_id": ["OL1", "OL2"],
            "report_status": ["Out", "Out"],
            "practice_status": [None, None],
        }
    )
    # Without pin: OL1 would appear 3×; with pin: only week-3 starters → 2
    assert derive_injury_counts(injuries, depth, "KC", "OL", 3) == 2


def test_pin_depth_uses_per_team_dt_when_no_week():
    from brady_bot.derive.injuries import pin_depth_to_latest_week

    depth = pl.DataFrame(
        {
            "dt": ["2026-09-01T00:00:00Z", "2026-09-10T00:00:00Z", "2026-09-05T00:00:00Z"],
            "team": ["KC", "KC", "BUF"],
            "gsis_id": ["A", "B", "C"],
            "pos_abb": ["QB", "QB", "QB"],
            "pos_rank": [1, 1, 1],
        }
    )
    pinned = pin_depth_to_latest_week(depth, 1)
    assert pinned.height == 2
    assert set(pinned["gsis_id"].to_list()) == {"B", "C"}


def test_te1_effective_start_promotes_when_chart_te1_out():
    from brady_bot.derive.roles import derive_roles
    from brady_bot.models import InjuryRecord

    depth = pl.DataFrame(
        {
            "dt": ["2026-09-10T00:00:00Z", "2026-09-10T00:00:00Z"],
            "team": ["LV", "LV"],
            "gsis_id": ["BOWERS", "MAYER"],
            "pos_abb": ["TE", "TE"],
            "pos_rank": [1, 2],
        }
    )
    injuries = {
        "BOWERS": InjuryRecord(player_id="BOWERS", report_status="Out", practice_status=None),
    }
    roles, _, _ = derive_roles(pl.DataFrame(), depth, injuries, 2026, 0, week=1)
    assert roles["MAYER"] == "TE1"
    assert roles["BOWERS"] == "TE1_OUT"
    assert sum(1 for r in roles.values() if r == "TE1") == 1


def test_roles_qb1_te1_from_pos_abb_pos_rank():
    """Live nflreadpy schema: pos_abb + pos_rank on pinned dt snapshot."""
    from brady_bot.derive.roles import derive_roles

    depth = pl.DataFrame(
        {
            "dt": ["2026-09-10T00:00:00Z"] * 6 + ["2026-09-01T00:00:00Z"],
            "team": ["KC", "KC", "KC", "BUF", "BUF", "BUF", "KC"],
            "gsis_id": ["MAHOMES", "KELCE", "PACHECO", "ALLEN", "KINCAID", "COOK", "OLD_QB"],
            "player_name": [
                "Patrick Mahomes",
                "Travis Kelce",
                "Isiah Pacheco",
                "Josh Allen",
                "Dalton Kincaid",
                "James Cook",
                "Stale QB",
            ],
            "pos_abb": ["QB", "TE", "RB", "QB", "TE", "RB", "QB"],
            "pos_rank": [1, 1, 1, 1, 1, 1, 1],
        }
    )
    roles, _, qb1 = derive_roles(pl.DataFrame(), depth, {}, 2026, 0, week=1)
    assert qb1["KC"] == "MAHOMES"
    assert qb1["BUF"] == "ALLEN"
    assert roles["MAHOMES"] == "QB1"
    assert roles["KELCE"] == "TE1"
    assert roles["ALLEN"] == "QB1"
    assert roles["KINCAID"] == "TE1"
    assert roles["PACHECO"] == "RB1"
    assert "OLD_QB" not in roles  # older dt dropped by pin


def test_injury_counts_differentiated_by_unit_pos_abb():
    """OL / SECONDARY / FRONT_SEVEN / INTERIOR count distinct pos_abb starters."""
    from brady_bot.derive.injuries import derive_injury_counts

    depth = pl.DataFrame(
        {
            "dt": ["2026-09-10T00:00:00Z"] * 6,
            "team": ["GB"] * 6,
            "gsis_id": ["LG1", "RT1", "FS1", "LDE1", "RILB1", "WR1"],
            "pos_abb": ["LG", "RT", "FS", "LDE", "RILB", "WR"],
            "pos_rank": [1, 1, 1, 1, 1, 1],
        }
    )
    injuries = pl.DataFrame(
        {
            "week": [1] * 5,
            "gsis_id": ["LG1", "RT1", "FS1", "LDE1", "RILB1"],
            "report_status": ["Out", "Out", "Out", "Out", "Out"],
            "practice_status": [None] * 5,
        }
    )
    assert derive_injury_counts(injuries, depth, "GB", "OL", 1) == 2
    assert derive_injury_counts(injuries, depth, "GB", "SECONDARY", 1) == 1
    assert derive_injury_counts(injuries, depth, "GB", "FRONT_SEVEN", 1) == 2
    # LDE excluded from interior; RILB included
    assert derive_injury_counts(injuries, depth, "GB", "FRONT_SEVEN_INTERIOR", 1) == 1
    assert derive_injury_counts(injuries, depth, "GB", "DEFENSE_ALL", 1) == 3


def test_wr_roles_week1_blend_prior_and_1pp_tiebreak():
    """Week 1 uses prior target share; within 1pp, lower depth_chart_order wins."""
    from brady_bot.derive.roles import derive_roles

    # Prior season: A and B nearly tied on KC; A has slightly more targets but B is DC order 1
    rows = []
    for week in (15, 16, 17, 18):
        rows.append(
            {
                "season": 2025,
                "week": week,
                "gsis_id": "WRA",
                "recent_team": "KC",
                "position": "WR",
                "targets": 100,
            }
        )
        rows.append(
            {
                "season": 2025,
                "week": week,
                "gsis_id": "WRB",
                "recent_team": "KC",
                "position": "WR",
                "targets": 99,  # within 1pp of A after normalize
            }
        )
        rows.append(
            {
                "season": 2025,
                "week": week,
                "gsis_id": "WRC",
                "recent_team": "KC",
                "position": "WR",
                "targets": 1,
            }
        )
    ps = pl.DataFrame(rows)
    depth = pl.DataFrame(
        {
            "week": [1, 1, 1],
            "team": ["KC", "KC", "KC"],
            "gsis_id": ["WRA", "WRB", "WRC"],
            "position": ["WR", "WR", "WR"],
            "depth_chart_order": [2, 1, 3],
        }
    )
    # through_week=0 (week 1) → prior-only blend
    roles, shares, _ = derive_roles(
        ps,
        depth,
        {},
        2026,
        0,
        week=1,
        prior_week_lo=15,
        prior_week_hi=18,
    )
    assert "WRA" in roles and "WRB" in roles
    # Shares within 1pp → WRB (depth 1) should be WR1 ahead of WRA
    assert roles["WRB"] == "WR1"
    assert roles["WRA"] == "WR2"
    assert shares["WRB"] > 0


def test_team_ranks_32_teams_and_opp_defense_fallback():
    """Real columns + opponent-offense yards allowed; no T01 placeholder."""
    from brady_bot.derive.team_ranks import derive_team_ranks

    teams = [f"T{i:02d}" for i in range(1, 33)]
    rows = []
    for week in (1, 2, 3, 4, 5):
        for i, team in enumerate(teams):
            opp = teams[(i + 1) % 32]
            rows.append(
                {
                    "season": 2025,
                    "week": week,
                    "season_type": "REG",
                    "team": team,
                    "opponent_team": opp,
                    "passing_yards": 200 + i,
                    "rushing_yards": 100 + (i % 5),
                    "passing_tds": 1,
                    "rushing_tds": 1,
                    "fg_made": 1,
                    "pat_made": 2,
                    "carries": 25,
                    "attempts": 30,
                    "sacks_suffered": i % 4,
                    "passing_interceptions": i % 3,
                    "fumbles_lost_total": 0,
                }
            )
    ts = pl.DataFrame(rows)
    ranks = derive_team_ranks(ts, pl.DataFrame(), 2025, 5, blend_week=5)
    assert len(ranks) == 32
    assert all(1 <= r.offense_rank <= 32 for r in ranks.values())
    assert all(1 <= r.total_defense_rank <= 32 for r in ranks.values())
    assert all(1 <= r.defense_calibre_rank <= 32 for r in ranks.values())
    # Highest yards (T32) outranks lowest (T01)
    assert ranks["T32"].offense_rank < ranks["T01"].offense_rank
    # Old synthetic fallback string must not exist in module source
    import inspect
    from brady_bot.derive import team_ranks as mod

    assert 'f"T{i:02d}"' not in inspect.getsource(mod)


def test_team_ranks_halts_below_32_no_placeholder():
    import pytest
    from brady_bot.derive.team_ranks import TeamRanksError, derive_team_ranks

    rows = []
    for team in ("LA", "NE", "SEA", "SF"):
        rows.append(
            {
                "season": 2026,
                "week": 1,
                "season_type": "REG",
                "team": team,
                "opponent_team": "LA" if team != "LA" else "NE",
                "passing_yards": 250,
                "rushing_yards": 120,
                "passing_tds": 2,
                "rushing_tds": 1,
                "fg_made": 1,
                "pat_made": 2,
                "carries": 25,
                "attempts": 35,
                "sacks_suffered": 2,
            }
        )
    ts = pl.DataFrame(rows)
    with pytest.raises(TeamRanksError, match=r"4 teams, expected 32"):
        derive_team_ranks(ts, pl.DataFrame(), 2026, 5, blend_week=5)

    import inspect
    from brady_bot.derive import team_ranks as mod

    src = inspect.getsource(mod)
    assert 'f"T{i:02d}"' not in src
    assert "T01" not in src


def test_adj_fpa_normalizes_team_alias_keys():
    teams = [f"T{i:02d}" for i in range(1, 32)] + ["LAR"]  # raw LA Rams abbr
    cfg = LeagueConfig(raw={}, season=2026, scoring=_SCORING)
    rows = _qb_rows(2026, [1, 2, 3, 4, 5], teams)
    df = pl.DataFrame(rows)
    aliases = {"LAR": "LA"}
    result = derive_adj_fpa(
        df, pl.DataFrame(), "QB", 2026, 5, cfg, week=5, team_aliases=aliases
    )
    assert "LA" in result
    assert "LAR" not in result
    # matchup_score finds normalized key from opponent_of-style abbr
    score = matchup_score(result, "LA", "percentile")
    assert 0.0 <= score <= 1.0
