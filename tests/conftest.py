# tests/conftest.py
import pytest
import asyncio
import yaml
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_claude_response():
    """Factory for mocked Gemini API text response."""
    def _make(text: str):
        response = MagicMock()
        response.text = text
        return response
    return _make


@pytest.fixture
def sample_messages():
    from datetime import datetime
    from zalosniper.models.message import Message
    return [
        Message(id=1, group_name="G", sender="Alice",
                content="App bị crash khi bấm nút login trên Android",
                timestamp=datetime(2026, 3, 11, 10, 0)),
        Message(id=2, group_name="G", sender="Bob",
                content="Mình cũng gặp vấn đề này từ sáng nay",
                timestamp=datetime(2026, 3, 11, 10, 5)),
    ]
