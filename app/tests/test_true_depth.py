"""True Depth Chart — flat columns payload + True reorder."""
from __future__ import annotations

import json

import polars as pl

from brady_bot.derive.depth_table import build_skill_columns
from brady_bot.derive.opportunity_share import AllView, ShareRow, WeekView
from brady_bot.derive.true_depth import build_payload


def _depth(rows: list[dict]) -> pl.DataFrame:
    defaults = {"dt": "2026-09-13T12:00:00Z", "team": "BUF", "pos_grp": "3WR 1TE"}
    return pl.DataFrame([{**defaults, **r} for r in rows])


def _injuries(rows: list[dict]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame([{"week": 1, "team": "BUF", **r} for r in rows])


def _share(
    player_id: str,
    player: str,
    position: str,
    *,
    target: float | None = None,
    targets: int | None = None,
    rush: float | None = None,
    carries: int | None = None,
    team: str = "BUF",
) -> ShareRow:
    return ShareRow(
        team=team,
        player_id=player_id,
        player=player,
        position=position,
        target_share_pct=target,
        targets=targets,
        gp_tgt=1 if target is not None else 0,
        rush_share_pct=rush,
        carries=carries,
        gp_rsh=1 if rush is not None else 0,
    )


def _payload(
    depth,
    shares,
    injuries=None,
    weeks=(1,),
    week=1,
    week_shares=None,
) -> dict:
    skill = build_skill_columns(
        depth, injuries if injuries is not None else pl.DataFrame(), "BUF", week=week
    )
    week_view = None
    if weeks:
        latest = max(weeks)
        rows = tuple(week_shares) if week_shares is not None else tuple(shares)
        week_view = WeekView(week=latest, rows=rows)
    return build_payload(
        skill,
        AllView(rows=tuple(shares), completed_weeks=weeks),
        week_view,
        week=week,
        other_starter_injuries={"OL": 0, "DL": 0, "LBs": 0, "DBs": 0},
    )


def _true_names(payload: dict, pos: str) -> list[str | None]:
    return [c["true"]["player_name"] for c in payload["columns"][pos]]


def _published_names(payload: dict, pos: str) -> list[str | None]:
    return [c["published"]["player_name"] for c in payload["columns"][pos]]


def _movements(payload: dict, pos: str) -> list[str]:
    return [c["true"]["movement"] for c in payload["columns"][pos]]


def test_rb_column_reorders_by_rush_share():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "Named Starter",
                 "gsis_id": "RB1"},
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 2, "player_name": "Real Workhorse",
                 "gsis_id": "RB2"},
            ]
        ),
        [
            _share("RB1", "Named Starter", "RB", rush=30.0, carries=9),
            _share("RB2", "Real Workhorse", "RB", rush=60.0, carries=18),
        ],
    )
    assert _published_names(payload, "RB") == ["Named Starter", "Real Workhorse"]
    assert _true_names(payload, "RB") == ["Real Workhorse", "Named Starter"]
    assert _movements(payload, "RB") == ["up", "down"]


def test_wr_flat_column_reorders_by_target_share():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 1, "player_name": "A", "gsis_id": "1"},
                {"pos_abb": "WR", "pos_slot": 2, "pos_rank": 2, "player_name": "B", "gsis_id": "2"},
                {"pos_abb": "WR", "pos_slot": 8, "pos_rank": 3, "player_name": "C", "gsis_id": "3"},
            ]
        ),
        [
            _share("1", "A", "WR", target=10.0, targets=5),
            _share("2", "B", "WR", target=25.0, targets=12),
            _share("3", "C", "WR", target=18.0, targets=9),
        ],
    )
    assert _true_names(payload, "WR") == ["B", "C", "A"]


def test_qb_has_no_true_field():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "QB", "pos_slot": 1, "pos_rank": 1, "player_name": "Passer",
                 "gsis_id": "Q1"},
                {"pos_abb": "QB", "pos_slot": 1, "pos_rank": 2, "player_name": "Backup",
                 "gsis_id": "Q2"},
            ]
        ),
        [_share("Q1", "Passer", "QB", rush=10.0, carries=3)],
    )
    for entry in payload["columns"]["QB"]:
        assert "true" not in entry
    assert _published_names(payload, "QB") == ["Passer", "Backup"]


def test_out_demotion_applies_to_true_order():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "Hurt Stud",
                 "gsis_id": "1"},
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 2, "player_name": "Healthy Backup",
                 "gsis_id": "2"},
            ]
        ),
        [
            _share("1", "Hurt Stud", "RB", rush=70.0, carries=21),
            _share("2", "Healthy Backup", "RB", rush=20.0, carries=6),
        ],
        injuries=_injuries([{"gsis_id": "1", "report_status": "Out"}]),
    )
    assert _true_names(payload, "RB") == ["Healthy Backup", "Hurt Stud"]
    assert payload["columns"]["RB"][1]["true"]["injury_mark"] == "O"


def test_usage_overflow_extends_true_column():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 1, "player_name": "Listed",
                 "gsis_id": "1"},
            ]
        ),
        [
            _share("1", "Listed", "WR", target=20.0, targets=9),
            _share("99", "Just Traded In", "WR", target=28.0, targets=13),
        ],
    )
    assert _true_names(payload, "WR") == ["Just Traded In", "Listed"]
    assert _published_names(payload, "WR") == ["Listed", None]


def test_preseason_mirrors_published():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "One",
                 "gsis_id": "1"},
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 2, "player_name": "Two",
                 "gsis_id": "2"},
            ]
        ),
        [],
        weeks=(),
    )
    assert payload["has_usage_data"] is False
    assert _true_names(payload, "RB") == ["One", "Two"]
    assert _movements(payload, "RB") == ["none", "none"]


def test_payload_shape_matches_simplified_contract():
    payload = _payload(
        _depth(
            [{"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "One", "gsis_id": "1"}]
        ),
        [_share("1", "One", "RB", rush=50.0, carries=15)],
    )
    assert set(payload) >= {
        "team",
        "week",
        "has_usage_data",
        "completed_weeks",
        "opportunity_week",
        "columns",
        "other_starter_injuries",
    }
    assert "sections" not in payload
    assert list(payload["columns"]) == ["QB", "RB", "WR", "TE"]
    assert payload["opportunity_week"] == 1
    rb = payload["columns"]["RB"][0]
    assert set(rb) == {"pos_rank", "published", "true"}
    assert set(rb["true"]) == {
        "player_name",
        "injury_mark",
        "movement",
        "opportunity_pct",
        "bellcow",
    }


def test_true_mode_opportunity_pct_comes_from_latest_week_not_all_mean():
    """Ranking uses All averages; displayed % is the latest week only."""
    payload = _payload(
        _depth(
            [
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 1, "player_name": "A", "gsis_id": "1"},
                {"pos_abb": "WR", "pos_slot": 1, "pos_rank": 2, "player_name": "B", "gsis_id": "2"},
            ]
        ),
        # All means: A=40, B=20 → A ranks first
        [
            _share("1", "A", "WR", target=40.0, targets=20),
            _share("2", "B", "WR", target=20.0, targets=10),
        ],
        weeks=(1, 2),
        # Latest week alone: B=50, A=10
        week_shares=[
            _share("1", "A", "WR", target=10.0, targets=4),
            _share("2", "B", "WR", target=50.0, targets=20),
        ],
    )
    assert payload["opportunity_week"] == 2
    assert _true_names(payload, "WR") == ["A", "B"]  # All ranking unchanged
    by_name = {c["true"]["player_name"]: c["true"] for c in payload["columns"]["WR"]}
    assert by_name["A"]["opportunity_pct"] == 10.0
    assert by_name["B"]["opportunity_pct"] == 50.0
    assert by_name["A"]["bellcow"] is False
    assert by_name["B"]["bellcow"] is False


def test_rb_bellcow_at_sixty_percent_hard_cutoff():
    payload = _payload(
        _depth(
            [
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "Bell", "gsis_id": "1"},
                {"pos_abb": "RB", "pos_slot": 1, "pos_rank": 2, "player_name": "Almost", "gsis_id": "2"},
            ]
        ),
        [
            _share("1", "Bell", "RB", rush=60.0, carries=18),
            _share("2", "Almost", "RB", rush=59.9, carries=17),
        ],
    )
    by_name = {c["true"]["player_name"]: c["true"] for c in payload["columns"]["RB"]}
    assert by_name["Bell"]["opportunity_pct"] == 60.0
    assert by_name["Bell"]["bellcow"] is True
    assert by_name["Almost"]["opportunity_pct"] == 59.9
    assert by_name["Almost"]["bellcow"] is False


def test_wr_never_gets_bellcow_even_with_high_target_share():
    payload = _payload(
        _depth(
            [{"pos_abb": "WR", "pos_slot": 1, "pos_rank": 1, "player_name": "Wide", "gsis_id": "1"}]
        ),
        [_share("1", "Wide", "WR", target=70.0, targets=14)],
    )
    true = payload["columns"]["WR"][0]["true"]
    assert true["opportunity_pct"] == 70.0
    assert true["bellcow"] is False


def test_missing_latest_week_share_omits_pct():
    payload = _payload(
        _depth(
            [{"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "Inactive", "gsis_id": "1"}]
        ),
        [_share("1", "Inactive", "RB", rush=40.0, carries=12)],
        weeks=(1, 2),
        week_shares=[],  # not in latest week population
    )
    true = payload["columns"]["RB"][0]["true"]
    assert true["opportunity_pct"] is None
    assert true["bellcow"] is False


def test_payload_is_json_serializable():
    payload = _payload(
        _depth(
            [{"pos_abb": "RB", "pos_slot": 1, "pos_rank": 1, "player_name": "One", "gsis_id": "1"}]
        ),
        [_share("1", "One", "RB", rush=50.0, carries=15)],
    )
    assert json.loads(json.dumps(payload)) == payload
