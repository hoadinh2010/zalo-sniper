import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
from zalosniper.web.app import create_app
from zalosniper.web.auth import AuthManager

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_all_settings = AsyncMock(return_value={"ai_provider": "gemini"})
    db.set_many_settings = AsyncMock()
    db.set_setting = AsyncMock()
    db.get_all_groups = AsyncMock(return_value=[])
    db.get_dashboard_stats = AsyncMock(return_value={
        "bugs_done": 0, "groups_active": 0, "pending": 0,
        "prs_created": 0, "recent_analyses": []
    })
    return db

@pytest.fixture
def app_client(mock_db):
    auth = AuthManager()
    # Pre-set a known password hash
    pw_hash = auth.hash_password("testpass")
    app = create_app(db=mock_db, auth=auth, password_hash=pw_hash, bot_state={})
    return TestClient(app, raise_server_exceptions=True)

def test_login_wrong_password(app_client):
    resp = app_client.post("/api/auth/login", json={"password": "wrongpass"})
    assert resp.status_code == 401

def test_login_correct_password(app_client):
    resp = app_client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    assert "token" in resp.json()

def test_status_requires_auth(app_client):
    resp = app_client.get("/api/status")
    assert resp.status_code == 401

def test_status_with_auth(app_client):
    login = app_client.post("/api/auth/login", json={"password": "testpass"})
    token = login.json()["token"]
    resp = app_client.get("/api/status", cookies={"session": token})
    assert resp.status_code == 200
    data = resp.json()
    assert "bot_running" in data

def test_get_settings_masked(app_client):
    login = app_client.post("/api/auth/login", json={"password": "testpass"})
    token = login.json()["token"]
    resp = app_client.get("/api/settings", cookies={"session": token})
    assert resp.status_code == 200

def test_get_groups(app_client):
    login = app_client.post("/api/auth/login", json={"password": "testpass"})
    token = login.json()["token"]
    resp = app_client.get("/api/groups", cookies={"session": token})
    assert resp.status_code == 200
    assert resp.json() == []

def test_change_password_too_short(app_client):
    login = app_client.post("/api/auth/login", json={"password": "testpass"})
    token = login.json()["token"]
    resp = app_client.post("/api/auth/change-password",
                           json={"password": "abc"},
                           cookies={"session": token})
    assert resp.status_code == 400

def test_change_password_success(app_client):
    login = app_client.post("/api/auth/login", json={"password": "testpass"})
    token = login.json()["token"]
    resp = app_client.post("/api/auth/change-password",
                           json={"password": "newpassword123"},
                           cookies={"session": token})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # Old session still valid (token-based auth)
    resp2 = app_client.get("/api/status", cookies={"session": token})
    assert resp2.status_code == 200

def test_full_integration_login_and_dashboard(app_client):
    """Full flow: login → get status → logout"""
    # Login
    resp = app_client.post("/api/auth/login", json={"password": "testpass"})
    assert resp.status_code == 200
    token = resp.json()["token"]

    # Get status
    resp = app_client.get("/api/status", cookies={"session": token})
    assert resp.status_code == 200
    data = resp.json()
    assert "bot_running" in data
    assert "bugs_done" in data

    # Logout
    resp = app_client.post("/api/auth/logout", cookies={"session": token})
    assert resp.status_code == 200

    # Session invalid after logout
    resp = app_client.get("/api/status", cookies={"session": token})
    assert resp.status_code == 401
