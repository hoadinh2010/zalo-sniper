# tests/modules/test_ai_analyzer.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from zalosniper.modules.ai_analyzer import AIAnalyzer
from zalosniper.core.config import AIConfig, RepoConfig


@pytest.fixture
def analyzer():
    with patch("google.genai.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client_cls.return_value = mock_client
        cfg = AIConfig(provider="gemini", model="gemini-2.0-flash", api_key="test_key")
        a = AIAnalyzer(config=cfg)
        yield a


def _set_response(analyzer, text: str):
    """Configure the mock to return `text` from generate_content."""
    resp = MagicMock()
    resp.text = text
    analyzer._gemini_client.aio.models.generate_content = AsyncMock(return_value=resp)


@pytest.mark.asyncio
async def test_classify_bug_report(analyzer, sample_messages):
    response_json = json.dumps({
        "type": "bug_report",
        "summary": "App crash khi login trên Android",
        "affected_feature": "authentication"
    })
    _set_response(analyzer, response_json)
    result = await analyzer.classify_messages(sample_messages)

    assert result["type"] == "bug_report"
    assert "summary" in result


@pytest.mark.asyncio
async def test_classify_noise(analyzer):
    from datetime import datetime
    from zalosniper.models.message import Message
    messages = [Message(id=1, group_name="G", sender="Alice",
                        content="Mọi người ơi hôm nay ăn gì",
                        timestamp=datetime(2026, 3, 11, 10, 0))]
    _set_response(analyzer, json.dumps({"type": "noise"}))
    result = await analyzer.classify_messages(messages)

    assert result["type"] == "noise"


@pytest.mark.asyncio
async def test_select_repo(analyzer, sample_messages):
    repos = [
        RepoConfig(owner="org", name="backend", branch="main",
                   description="Backend API"),
        RepoConfig(owner="org", name="frontend", branch="main",
                   description="Frontend React"),
    ]
    _set_response(analyzer, json.dumps({
        "selected_repo": "backend",
        "reason": "matched",
        "confidence": "high"
    }))
    owner, name, reason = await analyzer.select_repo(sample_messages, repos)

    assert name == "backend"
    assert reason == "matched"


@pytest.mark.asyncio
async def test_analyze_root_cause(analyzer, sample_messages):
    code_context = "# auth.py\ndef login(user, pwd): pass"
    _set_response(analyzer, json.dumps({
        "root_cause": "NullPointerException trong hàm login()",
        "affected_files": ["auth.py"],
        "proposed_fix_description": "Thêm null check cho user parameter"
    }))
    result = await analyzer.analyze_root_cause(sample_messages, code_context)

    assert "root_cause" in result
    assert "proposed_fix_description" in result


@pytest.mark.asyncio
async def test_generate_patch(analyzer):
    code_context = "def login(user, pwd): return user.name"
    root_cause = "NullPointerException khi user=None"
    _set_response(analyzer, json.dumps({
        "patch": "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1,3 @@\n-def login(user, pwd):\n+def login(user, pwd):\n+    if user is None: raise ValueError('user required')\n     return user.name"
    }))
    patch_text = await analyzer.generate_patch(root_cause, code_context)

    assert "patch" in patch_text or "---" in patch_text
