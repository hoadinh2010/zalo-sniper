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


@pytest.mark.asyncio
async def test_settings_crud(db):
    await db.set_setting("gemini_api_key", "test-key-123")
    val = await db.get_setting("gemini_api_key")
    assert val == "test-key-123"

@pytest.mark.asyncio
async def test_settings_missing_returns_none(db):
    val = await db.get_setting("nonexistent_key")
    assert val is None

@pytest.mark.asyncio
async def test_get_all_settings(db):
    await db.set_setting("a", "1")
    await db.set_setting("b", "2")
    settings = await db.get_all_settings()
    assert settings["a"] == "1"
    assert settings["b"] == "2"

@pytest.mark.asyncio
async def test_set_many_settings(db):
    await db.set_many_settings({"x": "10", "y": "20"})
    assert await db.get_setting("x") == "10"
    assert await db.get_setting("y") == "20"


@pytest.mark.asyncio
async def test_group_crud(db):
    gid = await db.create_group("support-bugs", -1001234567)
    assert gid > 0

    groups = await db.get_all_groups()
    assert len(groups) == 1
    assert groups[0]["group_name"] == "support-bugs"
    assert groups[0]["telegram_chat_id"] == -1001234567
    assert groups[0]["enabled"] == 1

@pytest.mark.asyncio
async def test_group_enable_disable(db):
    gid = await db.create_group("dev-team", -1009999999)
    ok = await db.update_group(gid, enabled=0)
    assert ok is True
    groups = await db.get_all_groups()
    assert groups[0]["enabled"] == 0

@pytest.mark.asyncio
async def test_group_delete_cascades(db):
    gid = await db.create_group("g", -100)
    await db.add_group_repo(gid, "org", "backend", "main", "Backend API")
    await db.delete_group(gid)
    repos = await db.get_group_repos(gid)
    assert repos == []

@pytest.mark.asyncio
async def test_repo_crud(db):
    gid = await db.create_group("g", -100)
    rid = await db.add_group_repo(gid, "org", "backend", "main", "Backend API")
    assert rid > 0
    repos = await db.get_group_repos(gid)
    assert len(repos) == 1
    assert repos[0]["repo_name"] == "backend"

@pytest.mark.asyncio
async def test_openproject_upsert(db):
    gid = await db.create_group("g", -100)
    await db.upsert_group_openproject(gid, "https://op.example.com", "key123", "proj-1")
    op = await db.get_group_openproject(gid)
    assert op["op_url"] == "https://op.example.com"
    # upsert again — update
    await db.upsert_group_openproject(gid, "https://op2.example.com", "key456", "proj-2")
    op2 = await db.get_group_openproject(gid)
    assert op2["op_url"] == "https://op2.example.com"
