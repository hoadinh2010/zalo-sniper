# tests/core/test_database.py
import pytest
import pytest_asyncio
import asyncio
from datetime import datetime
from zalosniper.core.database import Database
from zalosniper.models.message import Message
from zalosniper.models.bug_analysis import BugAnalysis, BugStatus


@pytest_asyncio.fixture
async def db(tmp_path):
    d = Database(str(tmp_path / "test.db"))
    await d.init()
    yield d
    await d.close()


@pytest.mark.asyncio
async def test_insert_and_fetch_message(db):
    msg = Message(
        id=None,
        group_name="Group ABC",
        sender="Alice",
        content="App bị crash khi login",
        timestamp=datetime.utcnow(),
    )
    msg_id = await db.insert_message(msg)
    assert msg_id > 0

    messages = await db.get_recent_messages("Group ABC", limit=20, within_hours=1)
    assert len(messages) == 1
    assert messages[0].content == "App bị crash khi login"


@pytest.mark.asyncio
async def test_message_deduplication(db):
    msg = Message(
        id=None,
        group_name="Group ABC",
        sender="Alice",
        content="Same message",
        timestamp=datetime.utcnow(),
        zalo_message_id="zalo_123",
    )
    id1 = await db.insert_message(msg)
    id2 = await db.insert_message(msg)   # duplicate — should be ignored
    assert id1 > 0
    assert id2 is None   # None = duplicate, not inserted


@pytest.mark.asyncio
async def test_insert_and_update_bug_analysis(db):
    analysis = BugAnalysis(
        id=None,
        message_ids=[1, 2],
        group_name="Group ABC",
        repo_owner="myorg",
        repo_name="backend",
    )
    analysis_id = await db.insert_bug_analysis(analysis)
    assert analysis_id > 0

    updated = await db.update_bug_analysis_status(analysis_id, BugStatus.APPROVED, approved_by=999)
    assert updated is True

    fetched = await db.get_bug_analysis(analysis_id)
    assert fetched.status == BugStatus.APPROVED
    assert fetched.approved_by == 999


@pytest.mark.asyncio
async def test_get_pending_analyses(db):
    for i in range(3):
        a = BugAnalysis(id=None, message_ids=[i], group_name="G", repo_owner="o", repo_name="r")
        await db.insert_bug_analysis(a)

    pending = await db.get_pending_analyses()
    assert len(pending) == 3
