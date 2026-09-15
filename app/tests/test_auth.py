from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from brady_bot import api as api_mod
from brady_bot import auth as auth_mod
from brady_bot.auth import ADMIN_PASSWORD, SUPERADMIN_PASSWORD, SUPERADMIN_USERNAME


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    users_file = tmp_path / "users.json"
    users_file.write_text('{"users": []}\n')
    monkeypatch.setattr(api_mod, "users_path", users_file)
    # Fresh client so session cookies are isolated
    return TestClient(api_mod.app), users_file


def test_health_public(client):
    c, _ = client
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_protected_api_requires_login(client):
    c, _ = client
    assert c.get("/api/roster").status_code == 401
    assert c.get("/api/meta/week").status_code == 401
    assert c.get("/api/admin/users").status_code == 403


def test_login_and_me(client):
    c, users_file = client
    auth_mod.create_user("a@example.com", "secret123", users_file)
    bad = c.post("/api/auth/login", json={"username": "a@example.com", "password": "wrong"})
    assert bad.status_code == 401

    ok = c.post("/api/auth/login", json={"username": "a@example.com", "password": "secret123"})
    assert ok.status_code == 200
    assert ok.json()["user"]["username"] == "a@example.com"

    me = c.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "a@example.com"

    roster = c.get("/api/roster")
    assert roster.status_code == 200


def test_admin_unlock_and_user_crud(client):
    c, _ = client
    wrong = c.post("/api/admin/unlock", json={"password": "nope"})
    assert wrong.status_code == 403

    unlock = c.post("/api/admin/unlock", json={"password": ADMIN_PASSWORD})
    assert unlock.status_code == 200

    listed = c.get("/api/admin/users")
    assert listed.status_code == 200
    assert listed.json()["users"] == []

    created = c.post(
        "/api/admin/users",
        json={"username": "new@example.com", "password": "pass1"},
    )
    assert created.status_code == 200
    user_id = created.json()["id"]
    assert created.json()["username"] == "new@example.com"

    listed2 = c.get("/api/admin/users")
    assert len(listed2.json()["users"]) == 1

    updated = c.put(
        f"/api/admin/users/{user_id}",
        json={"username": "renamed@example.com", "password": "pass2"},
    )
    assert updated.status_code == 200
    assert updated.json()["username"] == "renamed@example.com"

    # Can log in with new credentials
    login = c.post(
        "/api/auth/login",
        json={"username": "renamed@example.com", "password": "pass2"},
    )
    assert login.status_code == 200

    # Re-unlock after login clears session
    c.post("/api/admin/unlock", json={"password": ADMIN_PASSWORD})
    deleted = c.delete(f"/api/admin/users/{user_id}")
    assert deleted.status_code == 200
    assert c.get("/api/admin/users").json()["users"] == []


def test_admin_crud_requires_unlock(client):
    c, users_file = client
    auth_mod.create_user("u@example.com", "x", users_file)
    c.post("/api/auth/login", json={"username": "u@example.com", "password": "x"})
    assert c.get("/api/admin/users").status_code == 403


def test_logout_clears_session(client):
    c, users_file = client
    auth_mod.create_user("u@example.com", "x", users_file)
    c.post("/api/auth/login", json={"username": "u@example.com", "password": "x"})
    assert c.get("/api/auth/me").status_code == 200
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_login_page_served(client):
    c, _ = client
    r = c.get("/login")
    assert r.status_code == 200
    assert b"Login" in r.content
    assert b"brady-bot-logo-text-white.png?v=20260915" in r.content


def test_create_user_rejects_non_email(client):
    c, _ = client
    c.post("/api/admin/unlock", json={"password": ADMIN_PASSWORD})
    r = c.post("/api/admin/users", json={"username": "not-an-email", "password": "x"})
    assert r.status_code == 400


def test_hardcoded_superadmin_login(client):
    c, _ = client
    # Works even when users.json is empty
    bad = c.post(
        "/api/auth/login",
        json={"username": SUPERADMIN_USERNAME, "password": "wrong"},
    )
    assert bad.status_code == 401
    ok = c.post(
        "/api/auth/login",
        json={"username": SUPERADMIN_USERNAME, "password": SUPERADMIN_PASSWORD},
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["username"] == SUPERADMIN_USERNAME
    assert c.get("/api/auth/me").status_code == 200
    assert c.get("/api/roster").status_code == 200
