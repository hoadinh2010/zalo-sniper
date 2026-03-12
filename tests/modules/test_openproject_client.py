# tests/modules/test_openproject_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from zalosniper.modules.openproject_client import OpenProjectClient


@pytest.fixture
def client():
    return OpenProjectClient(url="https://op.example.com", api_key="test_key")


def _make_response(status, json_data=None, text_data=None):
    resp = AsyncMock()
    resp.status = status
    if json_data is not None:
        resp.json = AsyncMock(return_value=json_data)
    if text_data is not None:
        resp.text = AsyncMock(return_value=text_data)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_create_work_package(client):
    proj_resp = _make_response(200, json_data={"id": 1, "name": "Test"})
    types_resp = _make_response(200, json_data={
        "_embedded": {"elements": [
            {"_links": {"self": {"href": "/api/v3/types/1"}}}
        ]}
    })
    wp_resp = _make_response(201, json_data={
        "id": 99, "_links": {"self": {"href": "/api/v3/work_packages/99"}}
    })

    mock_session = AsyncMock()
    # get() called twice: project check, then types
    mock_session.get = MagicMock(side_effect=[proj_resp, types_resp])
    mock_session.post = MagicMock(return_value=wp_resp)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        wp_id, wp_url = await client.create_work_package(
            project_id="lfc-ticketing-system",
            title="Bug: login crash",
            description="App crash khi login trên Android",
        )

    assert wp_id == 99
    assert "work_packages/99" in wp_url


@pytest.mark.asyncio
async def test_create_work_package_project_not_found(client):
    proj_resp = _make_response(404, text_data="Not Found")

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=proj_resp)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        result = await client.create_work_package(
            project_id="nonexistent", title="test", description="test"
        )

    assert result == (None, None)


@pytest.mark.asyncio
async def test_create_work_package_failure_does_not_raise(client):
    proj_resp = _make_response(200, json_data={"id": 1})
    types_resp = _make_response(200, json_data={"_embedded": {"elements": []}})
    wp_resp = _make_response(500, text_data="Internal Server Error")

    mock_session = AsyncMock()
    mock_session.get = MagicMock(side_effect=[proj_resp, types_resp])
    mock_session.post = MagicMock(return_value=wp_resp)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        result = await client.create_work_package(
            project_id="lfc-ticketing-system", title="test", description="test"
        )

    assert result == (None, None)
