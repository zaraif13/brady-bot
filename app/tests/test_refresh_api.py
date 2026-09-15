"""Force-refresh endpoint — nav bar Refresh button hits this to bypass TTL."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from brady_bot import api as api_mod
from brady_bot import auth as auth_mod


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


def test_refresh_requires_auth(client):
    c, _ = client
    assert c.post("/api/refresh").status_code == 401


def test_refresh_calls_every_loader_with_no_cache(client, monkeypatch):
    c, users = client
    _login(c, users)

    calls: dict[str, dict] = {}

    def make_loader(name):
        def loader(cache, seasons, no_cache=False):
            calls[name] = {"seasons": seasons, "no_cache": no_cache}
            return None

        return loader

    for name in [
        "load_schedules",
        "load_player_stats",
        "load_team_stats",
        "load_snap_counts",
        "load_injuries",
        "load_depth_charts",
        "load_pbp",
    ]:
        monkeypatch.setattr(api_mod.nflverse, name, make_loader(name))

    r = c.post("/api/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["season"] == api_mod._cfg.league.season
    assert body["sources"] == {
        "schedules": "ok",
        "player_stats": "ok",
        "team_stats": "ok",
        "snap_counts": "ok",
        "injuries": "ok",
        "depth_charts": "ok",
        "pbp": "ok",
    }
    for name in calls:
        assert calls[name]["no_cache"] is True
        assert calls[name]["seasons"] == [api_mod._cfg.league.season]


def test_refresh_reports_per_source_errors_without_failing(client, monkeypatch):
    c, users = client
    _login(c, users)

    def ok_loader(cache, seasons, no_cache=False):
        return None

    def broken_loader(cache, seasons, no_cache=False):
        raise RuntimeError("nflreadpy unavailable")

    for name in [
        "load_schedules",
        "load_team_stats",
        "load_snap_counts",
        "load_injuries",
        "load_depth_charts",
        "load_pbp",
    ]:
        monkeypatch.setattr(api_mod.nflverse, name, ok_loader)
    monkeypatch.setattr(api_mod.nflverse, "load_player_stats", broken_loader)

    r = c.post("/api/refresh")
    assert r.status_code == 200
    body = r.json()
    assert "nflreadpy unavailable" in body["sources"]["player_stats"]
    assert body["sources"]["schedules"] == "ok"
