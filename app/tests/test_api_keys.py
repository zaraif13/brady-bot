from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from brady_bot import api as api_mod
from brady_bot import api_keys as api_keys_mod
from brady_bot import auth as auth_mod
from brady_bot.auth import ADMIN_PASSWORD, SUPERADMIN_PASSWORD, SUPERADMIN_USERNAME
from brady_bot.sources.cache import CacheStore
from brady_bot.sources.odds import ODDS_SPORT_KEY, check_odds_api_key, fetch_odds, resolve_odds_api_key


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    users_file = tmp_path / "users.json"
    users_file.write_text('{"users": []}\n')
    keys_file = tmp_path / "api_keys.json"
    monkeypatch.setattr(api_mod, "users_path", users_file)
    monkeypatch.setattr(api_mod, "api_keys_path", keys_file)
    monkeypatch.setattr(api_keys_mod, "API_KEYS_PATH", keys_file)
    api_keys_mod.ensure_seeded(keys_file)
    return TestClient(api_mod.app), users_file, keys_file


def _unlock(c: TestClient):
    assert c.post("/api/admin/unlock", json={"password": ADMIN_PASSWORD}).status_code == 200


def _login_superadmin(c: TestClient):
    r = c.post(
        "/api/auth/login",
        json={"username": SUPERADMIN_USERNAME, "password": SUPERADMIN_PASSWORD},
    )
    assert r.status_code == 200


def _login_user(c: TestClient, users_file: Path):
    auth_mod.create_user("other@example.com", "secret", users_file)
    r = c.post(
        "/api/auth/login",
        json={"username": "other@example.com", "password": "secret"},
    )
    assert r.status_code == 200


def test_me_includes_is_superadmin(client):
    c, _, _ = client
    _login_superadmin(c)
    me = c.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["is_superadmin"] is True


def test_apis_require_superadmin(client):
    c, users_file, _ = client
    _unlock(c)
    # Admin unlock alone (no login) → 403
    assert c.get("/api/admin/apis").status_code == 403

    _login_user(c, users_file)
    _unlock(c)
    assert c.get("/api/admin/apis").status_code == 403


def test_superadmin_apis_crud(client):
    c, _, keys_file = client
    _login_superadmin(c)
    _unlock(c)

    listed = c.get("/api/admin/apis")
    assert listed.status_code == 200
    apis = listed.json()["apis"]
    assert any(a["id"] == "the_odds_api" for a in apis)
    odds = next(a for a in apis if a["id"] == "the_odds_api")
    assert "key" not in odds
    assert odds["key_masked"].endswith("e604")

    full = c.get("/api/admin/apis/the_odds_api")
    assert full.status_code == 200
    assert full.json()["key"].endswith("e604")

    # Cannot delete builtin
    assert c.delete("/api/admin/apis/the_odds_api").status_code == 400

    created = c.post(
        "/api/admin/apis",
        json={"id": "future_api", "label": "Future", "key": "abc12345"},
    )
    assert created.status_code == 200
    assert created.json()["id"] == "future_api"

    updated = c.put(
        "/api/admin/apis/future_api",
        json={"label": "Future 2", "key": "newkey999"},
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Future 2"
    assert updated.json()["key"] == "newkey999"

    assert c.delete("/api/admin/apis/future_api").status_code == 200
    ids = [a["id"] for a in c.get("/api/admin/apis").json()["apis"]]
    assert "future_api" not in ids
    assert keys_file.exists()


def test_odds_test_endpoint(client):
    c, _, _ = client
    _login_superadmin(c)
    _unlock(c)

    fake_sports = [
        {"key": "soccer_epl", "title": "EPL", "active": True},
        {
            "key": ODDS_SPORT_KEY,
            "group": "American Football",
            "title": "NFL",
            "description": "US Football",
            "active": True,
        },
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = fake_sports

    with patch("brady_bot.sources.odds.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        r = c.post("/api/admin/apis/the_odds_api/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert ODDS_SPORT_KEY in body["message"]


def test_odds_check_invalid_key():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.json.return_value = {
        "message": "API key is not valid. Get an API key at https://the-odds-api.com",
        "error_code": "INVALID_KEY",
    }
    with patch("brady_bot.sources.odds.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        result = check_odds_api_key("bad")
    assert result["ok"] is False
    assert "invalid" in result["message"].lower()


def test_fetch_odds_uses_store_when_env_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    keys_file = tmp_path / "api_keys.json"
    api_keys_mod.save_apis(
        [
            {
                "id": "the_odds_api",
                "label": "The Odds API",
                "key": "store-key-xyz",
                "updated_at": "now",
            }
        ],
        keys_file,
    )
    assert resolve_odds_api_key(keys_file) == "store-key-xyz"

    cache = CacheStore(tmp_path / "cache")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {
            "id": "1",
            "sport_key": ODDS_SPORT_KEY,
            "home_team": "A",
            "away_team": "B",
            "bookmakers": [],
        }
    ]

    with patch("brady_bot.sources.odds.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
        events, unavailable, warn = fetch_odds(
            cache, refresh_odds=True, keys_path=keys_file
        )

    assert unavailable is False
    assert warn is None
    assert events[0]["sport_key"] == ODDS_SPORT_KEY
    called_url = client_cls.return_value.__enter__.return_value.get.call_args[0][0]
    assert ODDS_SPORT_KEY in called_url
    assert "super_bowl" not in called_url
