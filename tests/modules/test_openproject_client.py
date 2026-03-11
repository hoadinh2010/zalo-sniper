# tests/modules/test_openproject_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from zalosniper.modules.openproject_client import OpenProjectClient


@pytest.fixture
def client():
    return OpenProjectClient(url="https://op.example.com", api_key="test_key")


@pytest.mark.asyncio
async def test_create_work_package(client):
    mock_response = AsyncMock()
    mock_response.status = 201
    mock_response.json = AsyncMock(return_value={
        "id": 99,
        "_links": {"self": {"href": "/api/v3/work_packages/99"}}
    })

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_cm)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        wp_id, wp_url = await client.create_work_package(
            project_id=1,
            title="Bug: login crash",
            description="App crash khi login trên Android",
            status="new",
        )

    assert wp_id == 99


@pytest.mark.asyncio
async def test_create_work_package_failure_does_not_raise(client):
    mock_response = AsyncMock()
    mock_response.status = 500
    mock_response.text = AsyncMock(return_value="Internal Server Error")

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_cm)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        result = await client.create_work_package(
            project_id=1, title="test", description="test", status="new"
        )

    assert result == (None, None)
