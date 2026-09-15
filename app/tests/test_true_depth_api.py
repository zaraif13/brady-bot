"""True Depth Chart API — simplified columns + other starter injuries."""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from fastapi.testclient import TestClient

from brady_bot import api as api_mod
from brady_bot import auth as auth_mod
from brady_bot.players_index import NFL_TEAMS


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    users_file = tmp_path / "users.json"
    users_file.write_text('{"users": []}\n')
    monkeypatch.setattr(api_mod, "users_path", users_file)
    return TestClient(api_mod.app), users_file


def _login(client, users_file):
    auth_mod.create_user("a@example.com", "secret123", users_file)
    r = client.post(
        "/api/auth/login", json={"username": "a@example.com", "password": "secret123"}
    )
    assert r.status_code == 200


def _stub_frames(monkeypatch, *, team="BUF"):
    depth = pl.DataFrame(
        [
            {
                "dt": "2026-09-13T12:00:00Z",
                "team": team,
                "pos_grp": "3WR 1TE",
                "pos_abb": "RB",
                "pos_slot": 1,
                "pos_rank": 1,
                "player_name": "Starter",
                "gsis_id": "RB1",
            },
            {
                "dt": "2026-09-13T12:00:00Z",
                "team": team,
                "pos_grp": "3WR 1TE",
                "pos_abb": "RB",
                "pos_slot": 1,
                "pos_rank": 2,
                "player_name": "Backup",
                "gsis_id": "RB2",
            },
            {
                "dt": "2026-09-13T12:00:00Z",
                "team": team,
                "pos_grp": "3WR 1TE",
                "pos_abb": "LT",
                "pos_slot": 3,
                "pos_rank": 1,
                "player_name": "Left Tackle",
                "gsis_id": "OL1",
            },
            {
                "dt": "2026-09-13T12:00:00Z",
                "team": team,
                "pos_grp": "Base 3-4 D",
                "pos_abb": "NT",
                "pos_slot": 2,
                "pos_rank": 1,
                "player_name": "Nose",
                "gsis_id": "DL1",
            },
        ]
    )
    injuries = pl.DataFrame(
        [
            {
                "week": 1,
                "team": team,
                "gsis_id": "OL1",
                "report_status": "Out",
            },
            {
                "week": 1,
                "team": team,
                "gsis_id": "DL1",
                "report_status": "Doubtful",
            },
        ]
    )
    stats = pl.DataFrame(
        [
            {
                "season_type": "REG",
                "week": 1,
                "team": team,
                "player_id": "RB1",
                "player_display_name": "Starter",
                "position": "RB",
                "targets": 0,
                "carries": 8,
                "target_share": None,
            },
            {
                "season_type": "REG",
                "week": 1,
                "team": team,
                "player_id": "RB2",
                "player_display_name": "Backup",
                "position": "RB",
                "targets": 0,
                "carries": 16,
                "target_share": None,
            },
        ]
    )
    schedules = pl.DataFrame({"season": [2026], "week": [1], "game_type": ["REG"]})

    monkeypatch.setattr(api_mod.nflverse, "load_depth_charts", lambda *a, **k: depth)
    monkeypatch.setattr(api_mod.nflverse, "load_injuries", lambda *a, **k: injuries)
    monkeypatch.setattr(api_mod.nflverse, "load_player_stats", lambda *a, **k: stats)
    monkeypatch.setattr(api_mod.nflverse, "load_schedules", lambda *a, **k: schedules)


def test_true_depth_requires_auth(client):
    c, _ = client
    assert c.get("/api/true-depth").status_code == 401
    assert c.get("/api/true-depth/BUF").status_code == 401


def test_true_depth_page_is_served(client):
    c, _ = client
    r = c.get("/true-depth")
    assert r.status_code == 200
    assert b"True Depth Chart" in r.content
    assert b"Other Starter Injuries" in r.content
    assert b"js/depth-chart/true-depth.js" in r.content


def test_true_depth_list_returns_all_32_teams(client):
    c, users = client
    _login(c, users)
    r = c.get("/api/true-depth")
    assert r.status_code == 200
    teams = r.json()["teams"]
    assert [t["code"] for t in teams] == list(NFL_TEAMS)


def test_live_payload_uses_columns_contract(client, monkeypatch):
    c, users = client
    _login(c, users)
    _stub_frames(monkeypatch)

    r = c.get("/api/true-depth/BUF")
    assert r.status_code == 200
    body = r.json()
    assert "sections" not in body
    assert "columns" in body
    assert list(body["columns"]) == ["QB", "RB", "WR", "TE"]
    assert body["week"] == 1
    assert body["other_starter_injuries"] == {"OL": 1, "DL": 1, "LBs": 0, "DBs": 0}

    rb = body["columns"]["RB"]
    assert [col["published"]["player_name"] for col in rb] == ["Starter", "Backup"]
    assert [col["true"]["player_name"] for col in rb] == ["Backup", "Starter"]
    assert [col["true"]["movement"] for col in rb] == ["up", "down"]


def test_la_alias_resolves_to_the_rams(client, monkeypatch):
    c, users = client
    _login(c, users)
    _stub_frames(monkeypatch, team="LA")

    r = c.get("/api/true-depth/LA")
    assert r.status_code == 200
    body = r.json()
    assert body["team"] == "LAR"
    assert body["columns"]["RB"]
