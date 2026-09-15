from __future__ import annotations

from fastapi.testclient import TestClient

from brady_bot.api import app


client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_meta_week_requires_auth():
    r = client.get("/api/meta/week")
    assert r.status_code == 401


def test_index_html():
    r = client.get("/")
    assert r.status_code == 200
    assert b"Lineup Picker" in r.content
    assert b"data-nav-root" in r.content
    assert b"js/lineup/app.js" in r.content
