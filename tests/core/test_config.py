# tests/core/test_config.py
import pytest
import yaml
import tempfile
import os
from zalosniper.core.config import ConfigManager, GroupConfig, RepoConfig


SAMPLE_CONFIG = {
    "dry_run": False,
    "telegram": {
        "bot_token": "test_token",
        "approved_user_ids": [111, 222],
    },
    "zalo": {
        "session_dir": "./zalo_session",
        "poll_interval_seconds": 30,
    },
    "github": {
        "token": "ghp_test",
        "pr_enabled": True,
    },
    "groups": {
        "Group ABC": {
            "repos": [
                {"owner": "org", "name": "repo1", "branch": "main", "description": "Backend"},
            ],
            "telegram_chat_id": -100123,
            "openproject": {
                "url": "https://op.example.com",
                "api_key": "key",
                "project_id": 1,
            },
        }
    },
}


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(SAMPLE_CONFIG))
    return str(path)


def test_load_config(config_file):
    cfg = ConfigManager(config_file)
    assert cfg.telegram_bot_token == "test_token"
    assert cfg.approved_user_ids == [111, 222]
    assert cfg.dry_run is False
    assert cfg.github_pr_enabled is True


def test_group_config(config_file):
    cfg = ConfigManager(config_file)
    group = cfg.get_group("Group ABC")
    assert group is not None
    assert group.telegram_chat_id == -100123
    assert len(group.repos) == 1
    assert group.repos[0].name == "repo1"
    assert group.openproject.project_id == "1"


def test_get_group_by_name_not_found(config_file):
    cfg = ConfigManager(config_file)
    assert cfg.get_group("Nonexistent Group") is None


def test_missing_required_key_raises(tmp_path):
    bad = {"telegram": {}}   # missing bot_token
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(ValueError):
        ConfigManager(str(path))


# --- DB-backed tests ---

import json
from zalosniper.core.database import Database


@pytest.mark.asyncio
async def test_from_db_loads_settings(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.init()
    await db.set_many_settings({
        "telegram_bot_token": "bot-token-123",
        "ai_provider": "gemini",
        "ai_model": "gemini-2.0-flash",
        "dry_run": "0",
        "github_pr_enabled": "1",
        "zalo_session_dir": "./zalo_session",
        "zalo_poll_interval": "30",
        "github_token": "gh-token",
        "approved_user_ids": "[111, 222]",
    })
    config = await ConfigManager.from_db(db)
    assert config.telegram_bot_token == "bot-token-123"
    assert config.ai.provider == "gemini"
    assert config.dry_run is False
    assert config.approved_user_ids == [111, 222]
    await db.close()


@pytest.mark.asyncio
async def test_from_db_loads_groups(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.init()
    gid = await db.create_group("support-bugs", -1001234567)
    await db.add_group_repo(gid, "org", "backend", "main", "Backend API")
    await db.upsert_group_openproject(gid, "https://op.example.com", "key", "proj-1")
    config = await ConfigManager.from_db(db)
    assert "support-bugs" in config.groups
    group = config.get_group("support-bugs")
    assert group.telegram_chat_id == -1001234567
    assert len(group.repos) == 1
    assert group.repos[0].name == "backend"
    await db.close()


@pytest.mark.asyncio
async def test_from_db_disabled_group_excluded(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.init()
    gid = await db.create_group("disabled-group", -100)
    await db.update_group(gid, enabled=0)
    config = await ConfigManager.from_db(db)
    assert "disabled-group" not in config.groups
    await db.close()
