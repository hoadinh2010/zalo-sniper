# tests/modules/test_github_client.py
import pytest
from unittest.mock import MagicMock, patch
from zalosniper.modules.github_client import GitHubClient


@pytest.fixture
def client():
    return GitHubClient(token="fake_token")


def test_create_pr_returns_url(client):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/org/repo/pull/42"
    mock_pr.number = 42
    mock_repo.create_pull.return_value = mock_pr

    with patch.object(client._github, "get_repo", return_value=mock_repo):
        url, number = client.create_pull_request(
            owner="org", repo_name="repo",
            branch="fix/bug-1", base="main",
            title="fix: login crash",
            body="Fixes login crash on Android"
        )

    assert url == "https://github.com/org/repo/pull/42"
    assert number == 42


def test_create_pr_disabled(client):
    url, number = client.create_pull_request(
        owner="org", repo_name="repo",
        branch="fix/bug-1", base="main",
        title="fix: test", body="test",
        enabled=False
    )
    assert url is None
    assert number is None
