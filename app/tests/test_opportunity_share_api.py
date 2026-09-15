"""Opportunity Share API + page/nav wiring."""
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


def _stub_sources(monkeypatch):
    stats = pl.DataFrame(
        [
            {
                "season_type": "REG",
                "week": 1,
                "team": "BUF",
                "player_id": "W1",
                "player_display_name": "Receiver",
                "position": "WR",
                "targets": 8,
                "carries": 0,
                "target_share": 0.4,
            },
            {
                "season_type": "REG",
                "week": 1,
                "team": "BUF",
                "player_id": "R1",
                "player_display_name": "Rusher",
                "position": "RB",
                "targets": 0,
                "carries": 14,
                "target_share": None,
            },
            {
                "season_type": "REG",
                "week": 2,
                "team": "BUF",
                "player_id": "W1",
                "player_display_name": "Receiver",
                "position": "WR",
                "targets": 6,
                "carries": 0,
                "target_share": 0.3,
            },
        ]
    )
    pbp = pl.DataFrame(
        [
            {
                "week": 1,
                "season_type": "REG",
                "posteam": "BUF",
                "play_type": "pass",
                "yardline_100": 12,
                "receiver_player_id": "W1",
                "rusher_player_id": None,
            },
            {
                "week": 1,
                "season_type": "REG",
                "posteam": "BUF",
                "play_type": "run",
                "yardline_100": 8,
                "receiver_player_id": None,
                "rusher_player_id": "R1",
            },
        ]
    )
    monkeypatch.setattr(api_mod.nflverse, "load_player_stats", lambda *a, **k: stats)
    monkeypatch.setattr(api_mod.nflverse, "load_pbp", lambda *a, **k: pbp)


def test_opportunity_share_requires_auth(client):
    c, _ = client
    assert c.get("/api/opportunity-share").status_code == 401
    assert c.get("/api/opportunity-share/BUF").status_code == 401


def test_opportunity_share_page_is_served(client):
    c, _ = client
    r = c.get("/opportunity-share")
    assert r.status_code == 200
    assert b"Opportunity Share" in r.content
    assert b'data-nav-active="opportunity"' in r.content
    assert b"js/opportunity/opportunity-share.js" in r.content
    assert b"opp-all-banner" in r.content


def test_nav_registry_includes_opportunity_share():
    text = (api_mod.MODULE_ROOT / "js" / "sections.js").read_text()
    assert 'id: "opportunity"' in text
    assert "Opportunity Share" in text
    assert "opportunity-share.html" in text


def test_meta_lists_weeks_and_teams(client, monkeypatch):
    c, users = client
    _login(c, users)
    _stub_sources(monkeypatch)

    r = c.get("/api/opportunity-share")
    assert r.status_code == 200
    body = r.json()
    assert body["completed_weeks"] == [1, 2]
    assert [t["code"] for t in body["teams"]] == list(NFL_TEAMS)


def test_view_all_default_and_single_week(client, monkeypatch):
    c, users = client
    _login(c, users)
    _stub_sources(monkeypatch)

    all_r = c.get("/api/opportunity-share/BUF")
    assert all_r.status_code == 200
    all_body = all_r.json()
    assert all_body["view"] == "all"
    assert all_body["season_group_label"] == "Season to Date"
    assert all_body["rz_mix"]["rz_plays"] == 2
    assert {row["player_id"] for row in all_body["rows"]} >= {"W1", "R1"}

    week_r = c.get("/api/opportunity-share/BUF?view=1")
    assert week_r.status_code == 200
    week_body = week_r.json()
    assert week_body["view"] == 1
    assert week_body["season_group_label"] == "Season"
    rusher = next(row for row in week_body["rows"] if row["player_id"] == "R1")
    assert rusher["bellcow"] is True
    assert rusher["rush_share_pct"] == 100.0


def test_unknown_team_404(client, monkeypatch):
    c, users = client
    _login(c, users)
    _stub_sources(monkeypatch)
    r = c.get("/api/opportunity-share/ZZZ")
    assert r.status_code == 404


def test_empty_team_week_404(client, monkeypatch):
    c, users = client
    _login(c, users)
    _stub_sources(monkeypatch)
    r = c.get("/api/opportunity-share/KC?view=1")
    assert r.status_code == 404
