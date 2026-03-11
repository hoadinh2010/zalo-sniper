# tests/modules/test_telegram_bot.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from zalosniper.modules.telegram_bot import TelegramBot, is_authorized


def test_is_authorized():
    assert is_authorized(user_id=123, allowed=[123, 456]) is True
    assert is_authorized(user_id=789, allowed=[123, 456]) is False


@pytest.mark.asyncio
async def test_send_bug_notification(mocker):
    mock_app = MagicMock()
    mock_app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=999))

    bot = TelegramBot.__new__(TelegramBot)
    bot._app = mock_app
    bot._approved_user_ids = [111]

    from zalosniper.models.bug_analysis import BugAnalysis, BugStatus
    analysis = BugAnalysis(
        id=1, message_ids=[1], group_name="Group ABC",
        repo_owner="org", repo_name="backend",
        claude_summary="App crash khi login",
        root_cause="NullPointerException",
        proposed_fix="Thêm null check"
    )

    msg_id = await bot.send_bug_notification(chat_id=-100123, analysis=analysis)
    assert msg_id == 999
    mock_app.bot.send_message.assert_called_once()


def test_format_bug_message():
    from zalosniper.modules.telegram_bot import format_bug_message
    from zalosniper.models.bug_analysis import BugAnalysis
    analysis = BugAnalysis(
        id=5, message_ids=[1], group_name="Group ABC",
        repo_owner="org", repo_name="backend",
        claude_summary="Crash khi login",
        root_cause="NPE",
        proposed_fix="Add null check"
    )
    text = format_bug_message(analysis)
    assert "Group ABC" in text
    assert "backend" in text
    assert "NPE" in text
    assert "Approve" in text or "✅" in text
