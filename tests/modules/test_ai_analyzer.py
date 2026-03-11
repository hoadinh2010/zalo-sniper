# tests/modules/test_ai_analyzer.py
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from zalosniper.modules.ai_analyzer import AIAnalyzer
from zalosniper.core.config import RepoConfig


@pytest.fixture
def analyzer():
    return AIAnalyzer(api_key="test_key", model="claude-sonnet-4-6")


@pytest.mark.asyncio
async def test_classify_bug_report(analyzer, sample_messages, mock_claude_response):
    response_json = json.dumps({
        "type": "bug_report",
        "summary": "App crash khi login trên Android",
        "affected_feature": "authentication"
    })
    with patch.object(analyzer._client.messages, "create",
                      new=AsyncMock(return_value=mock_claude_response(response_json))):
        result = await analyzer.classify_messages(sample_messages)

    assert result["type"] == "bug_report"
    assert "summary" in result


@pytest.mark.asyncio
async def test_classify_noise(analyzer, mock_claude_response):
    from datetime import datetime
    from zalosniper.models.message import Message
    messages = [Message(id=1, group_name="G", sender="Alice",
                        content="Mọi người ơi hôm nay ăn gì",
                        timestamp=datetime(2026, 3, 11, 10, 0))]
    response_json = json.dumps({"type": "noise"})
    with patch.object(analyzer._client.messages, "create",
                      new=AsyncMock(return_value=mock_claude_response(response_json))):
        result = await analyzer.classify_messages(messages)

    assert result["type"] == "noise"


@pytest.mark.asyncio
async def test_select_repo(analyzer, sample_messages, mock_claude_response):
    repos = [
        RepoConfig(owner="org", name="backend", branch="main",
                   description="Backend API"),
        RepoConfig(owner="org", name="frontend", branch="main",
                   description="Frontend React"),
    ]
    response_json = json.dumps({
        "selected_repo": "backend",
        "reason": "matched",
        "confidence": "high"
    })
    with patch.object(analyzer._client.messages, "create",
                      new=AsyncMock(return_value=mock_claude_response(response_json))):
        owner, name, reason = await analyzer.select_repo(sample_messages, repos)

    assert name == "backend"
    assert reason == "matched"


@pytest.mark.asyncio
async def test_analyze_root_cause(analyzer, sample_messages, mock_claude_response):
    code_context = "# auth.py\ndef login(user, pwd): pass"
    response_json = json.dumps({
        "root_cause": "NullPointerException trong hàm login()",
        "affected_files": ["auth.py"],
        "proposed_fix_description": "Thêm null check cho user parameter"
    })
    with patch.object(analyzer._client.messages, "create",
                      new=AsyncMock(return_value=mock_claude_response(response_json))):
        result = await analyzer.analyze_root_cause(sample_messages, code_context)

    assert "root_cause" in result
    assert "proposed_fix_description" in result


@pytest.mark.asyncio
async def test_generate_patch(analyzer, mock_claude_response):
    code_context = "def login(user, pwd): return user.name"
    root_cause = "NullPointerException khi user=None"
    response_json = json.dumps({
        "patch": "--- a/auth.py\n+++ b/auth.py\n@@ -1 +1,3 @@\n-def login(user, pwd):\n+def login(user, pwd):\n+    if user is None: raise ValueError('user required')\n     return user.name"
    })
    with patch.object(analyzer._client.messages, "create",
                      new=AsyncMock(return_value=mock_claude_response(response_json))):
        patch_text = await analyzer.generate_patch(root_cause, code_context)

    assert "patch" in patch_text or "---" in patch_text
