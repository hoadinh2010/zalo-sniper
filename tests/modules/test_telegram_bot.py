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
    assert "Bug ID" in text


@pytest.mark.asyncio
async def test_cmd_enable_updates_db_and_config():
    from unittest.mock import AsyncMock, MagicMock, patch
    from zalosniper.modules.telegram_bot import TelegramBot

    mock_db = MagicMock()
    mock_db.get_all_groups = AsyncMock(return_value=[
        {"id": 1, "group_name": "support-bugs", "telegram_chat_id": -100, "enabled": 0}
    ])
    mock_db.update_group = AsyncMock(return_value=True)

    mock_config = MagicMock()
    mock_config.reload_groups = AsyncMock()

    with patch("telegram.ext.Application.builder") as mock_builder:
        mock_app = MagicMock()
        mock_builder.return_value.token.return_value.build.return_value = mock_app
        mock_app.handlers = {0: []}
        bot = TelegramBot(
            bot_token="fake:token", approved_user_ids=[999],
            db=mock_db, config=mock_config
        )

    update = MagicMock()
    update.effective_user.id = 999
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["support-bugs"]

    await bot._cmd_enable(update, context)

    mock_db.update_group.assert_called_once_with(1, enabled=1)
    mock_config.reload_groups.assert_called_once()
    update.message.reply_text.assert_called_once()
    assert "support-bugs" in update.message.reply_text.call_args[0][0]

@pytest.mark.asyncio
async def test_cmd_disable_updates_db():
    from unittest.mock import AsyncMock, MagicMock, patch
    from zalosniper.modules.telegram_bot import TelegramBot

    mock_db = MagicMock()
    mock_db.get_all_groups = AsyncMock(return_value=[
        {"id": 2, "group_name": "dev-team", "telegram_chat_id": -200, "enabled": 1}
    ])
    mock_db.update_group = AsyncMock(return_value=True)

    mock_config = MagicMock()
    mock_config.reload_groups = AsyncMock()

    with patch("telegram.ext.Application.builder") as mock_builder:
        mock_app = MagicMock()
        mock_builder.return_value.token.return_value.build.return_value = mock_app
        mock_app.handlers = {0: []}
        bot = TelegramBot(
            bot_token="fake:token", approved_user_ids=[999],
            db=mock_db, config=mock_config
        )

    update = MagicMock()
    update.effective_user.id = 999
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = ["dev-team"]

    await bot._cmd_disable(update, context)

    mock_db.update_group.assert_called_once_with(2, enabled=0)
    mock_config.reload_groups.assert_called_once()

@pytest.mark.asyncio
async def test_cmd_dashboard_sends_url():
    from unittest.mock import AsyncMock, MagicMock, patch
    from zalosniper.modules.telegram_bot import TelegramBot

    mock_config = MagicMock()
    mock_config.dashboard_port = 8080
    mock_config.reload_groups = AsyncMock()

    with patch("telegram.ext.Application.builder") as mock_builder:
        mock_app = MagicMock()
        mock_builder.return_value.token.return_value.build.return_value = mock_app
        mock_app.handlers = {0: []}
        bot = TelegramBot(
            bot_token="fake:token", approved_user_ids=[999], config=mock_config
        )

    update = MagicMock()
    update.effective_user.id = 999
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await bot._cmd_dashboard(update, context)

    update.message.reply_text.assert_called_once()
    assert "8080" in update.message.reply_text.call_args[0][0]
