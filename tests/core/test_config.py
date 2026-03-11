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
    assert group.openproject.project_id == 1


def test_get_group_by_name_not_found(config_file):
    cfg = ConfigManager(config_file)
    assert cfg.get_group("Nonexistent Group") is None


def test_missing_required_key_raises(tmp_path):
    bad = {"telegram": {}}   # missing bot_token
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(ValueError):
        ConfigManager(str(path))
