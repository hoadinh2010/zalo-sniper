# tests/modules/test_zalo_listener.py
import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from zalosniper.core.event_bus import EventBus, Event
from zalosniper.modules.zalo_listener import ZaloListener, parse_message_time, _parse_date_from_divider


def test_parse_message_time_today():
    # "10:30" format — today
    result = parse_message_time("10:30")
    assert result.hour == 10
    assert result.minute == 30
    assert result.date() == datetime.now().date()


def test_parse_message_time_yesterday():
    result = parse_message_time("Hôm qua 09:15")
    expected_date = (datetime.now() - timedelta(days=1)).date()
    assert result.date() == expected_date
    assert result.hour == 9


def test_parse_message_time_date():
    result = parse_message_time("10/03 08:00")
    assert result.month == 3
    assert result.day == 10


def test_parse_message_time_with_date_context():
    """HH:MM with a date_context should use that date, not today."""
    yesterday = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    result = parse_message_time("20:05", date_context=yesterday)
    assert result.date() == yesterday.date()
    assert result.hour == 20
    assert result.minute == 5


def test_parse_date_from_divider_hom_qua():
    result = _parse_date_from_divider("Hôm qua")
    expected = (datetime.now() - timedelta(days=1)).date()
    assert result.date() == expected


def test_parse_date_from_divider_hom_nay():
    result = _parse_date_from_divider("Hôm nay")
    assert result.date() == datetime.now().date()


def test_parse_date_from_divider_date_format():
    result = _parse_date_from_divider("Thứ hai, 10/03")
    assert result.month == 3
    assert result.day == 10


@pytest.mark.asyncio
async def test_session_expired_detection():
    listener = ZaloListener.__new__(ZaloListener)
    listener._page = MagicMock()
    listener._page.url = "https://chat.zalo.me/login"

    is_valid = await listener._is_session_valid()
    assert is_valid is False


@pytest.mark.asyncio
async def test_session_valid_detection():
    listener = ZaloListener.__new__(ZaloListener)
    listener._page = MagicMock()
    listener._page.url = "https://chat.zalo.me"
    listener._page.wait_for_selector = AsyncMock(return_value=True)

    is_valid = await listener._is_session_valid()
    assert is_valid is True


@pytest.mark.asyncio
async def test_process_extracted_messages_emits_event():
    db = MagicMock()
    db.insert_message = AsyncMock(return_value=1)

    bus = EventBus()
    emitted = []
    async def capture(e): emitted.append(e)
    bus.subscribe("NEW_MESSAGE", capture)

    listener = ZaloListener.__new__(ZaloListener)
    listener._db = db
    listener._bus = bus
    listener._last_seen = {}

    raw = [{"sender": "Alice", "content": "App crash", "time_str": "10:30", "zalo_message_id": "z1"}]
    await listener._process_extracted_messages("Group ABC", raw)
    await asyncio.sleep(0.05)

    assert len(emitted) == 1
    assert emitted[0].data["group_name"] == "Group ABC"


@pytest.mark.asyncio
async def test_process_extracted_messages_skips_already_seen():
    db = MagicMock()
    db.insert_message = AsyncMock(return_value=None)

    bus = EventBus()
    emitted = []
    async def capture(e): emitted.append(e)
    bus.subscribe("NEW_MESSAGE", capture)

    listener = ZaloListener.__new__(ZaloListener)
    listener._db = db
    listener._bus = bus
    # Set last_seen to end of today so message at "10:30" (today) is always "old"
    listener._last_seen = {"Group ABC": datetime.now().replace(hour=23, minute=59)}

    raw = [{"sender": "Alice", "content": "Old msg", "time_str": "10:30", "zalo_message_id": "z2"}]
    await listener._process_extracted_messages("Group ABC", raw)
    await asyncio.sleep(0.05)

    assert emitted == []
