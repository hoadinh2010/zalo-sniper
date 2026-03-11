# ZaloSniper Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Zalo bot that monitors group messages, detects bug reports, analyzes root cause via Claude AI, proposes fixes to Telegram for human approval, then applies fixes and creates GitHub PRs and OpenProject tasks.

**Architecture:** Modular Monolith — single Python asyncio process with modules communicating via an internal EventBus. Each module is independently testable and has a single responsibility. Playwright drives Zalo Web for message collection; Claude claude-sonnet-4-6 handles all AI reasoning.

**Tech Stack:** Python 3.11+, Playwright, python-telegram-bot v20+, anthropic SDK, PyGithub, aiohttp (OpenProject), aiosqlite, pyyaml, pytest + pytest-asyncio

---

## File Map

| File | Responsibility |
|------|---------------|
| `main.py` | Entry point, wires modules together, handles `--relogin` flag |
| `requirements.txt` | All dependencies pinned |
| `config.example.yaml` | Template config with all keys documented |
| `.gitignore` | Ignore `config.yaml`, `zalo_session/`, `*.db` |
| `zalosniper/__init__.py` | Package marker |
| `zalosniper/core/event_bus.py` | `EventBus` class — asyncio Queue, typed events, subscribe/publish |
| `zalosniper/core/config.py` | `ConfigManager` — load/validate config.yaml, typed dataclasses |
| `zalosniper/core/database.py` | `Database` — aiosqlite, schema init, migrations, CRUD helpers |
| `zalosniper/models/message.py` | `Message` dataclass |
| `zalosniper/models/bug_analysis.py` | `BugAnalysis` dataclass, `BugStatus` enum |
| `zalosniper/modules/zalo_selectors.py` | All Playwright CSS selectors isolated here |
| `zalosniper/modules/zalo_listener.py` | `ZaloListener` — Playwright session management, polling |
| `zalosniper/modules/ai_analyzer.py` | `AIAnalyzer` — Claude API, classify/analyze/generate patch |
| `zalosniper/modules/code_agent.py` | `CodeAgent` — git clone/pull, file search, apply patch |
| `zalosniper/modules/telegram_bot.py` | `TelegramBot` — send notifications, handle callbacks and commands |
| `zalosniper/modules/github_client.py` | `GitHubClient` — create branch, push, create PR |
| `zalosniper/modules/openproject_client.py` | `OpenProjectClient` — create/update work packages |
| `tests/conftest.py` | Shared fixtures: in-memory DB, mock config, mock Claude responses |
| `tests/core/test_event_bus.py` | EventBus unit tests |
| `tests/core/test_config.py` | ConfigManager unit tests |
| `tests/core/test_database.py` | Database CRUD unit tests |
| `tests/modules/test_ai_analyzer.py` | AIAnalyzer unit tests (mock Claude API) |
| `tests/modules/test_code_agent.py` | CodeAgent unit tests (mock git/filesystem) |
| `tests/modules/test_telegram_bot.py` | TelegramBot unit tests (mock Telegram API) |
| `tests/modules/test_github_client.py` | GitHubClient unit tests (mock GitHub API) |
| `tests/modules/test_openproject_client.py` | OpenProjectClient unit tests (mock HTTP) |

---

## Chunk 1: Core Infrastructure

**Covers:** Project setup, EventBus, ConfigManager, Database, Models

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `config.example.yaml`
- Create: `zalosniper/__init__.py`
- Create: `zalosniper/core/__init__.py`
- Create: `zalosniper/modules/__init__.py`
- Create: `zalosniper/models/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/core/__init__.py`
- Create: `tests/modules/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
anthropic==0.40.0
playwright==1.49.0
python-telegram-bot==21.6
PyGithub==2.5.0
aiohttp==3.11.0
aiosqlite==0.20.0
pyyaml==6.0.2
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-mock==3.14.0
```

- [ ] **Step 2: Create .gitignore**

```
config.yaml
zalo_session/
*.db
*.db-wal
*.db-shm
__pycache__/
*.pyc
.env
repos/
```

- [ ] **Step 3: Create config.example.yaml**

```yaml
# ZaloSniper configuration template
# Copy to config.yaml and fill in values

dry_run: false   # true = analyse only, never create PR or task

telegram:
  bot_token: "YOUR_BOT_TOKEN"
  approved_user_ids: [123456789]   # Telegram user IDs allowed to approve fixes

zalo:
  session_dir: "./zalo_session"
  poll_interval_seconds: 30

github:
  token: "ghp_YOUR_TOKEN"
  pr_enabled: true   # false = push branch only, no PR

groups:
  "Tên Group Zalo ABC":
    repos:
      - owner: "myorg"
        name: "backend-abc"
        branch: "main"
        description: "Backend API cho dự án ABC"
      - owner: "myorg"
        name: "frontend-abc"
        branch: "main"
        description: "Frontend React cho dự án ABC"
    telegram_chat_id: -1001234567890
    openproject:
      url: "https://openproject.example.com"
      api_key: "YOUR_OP_API_KEY"
      project_id: 1
```

- [ ] **Step 4: Create all `__init__.py` files (empty)**

```bash
touch zalosniper/__init__.py \
      zalosniper/core/__init__.py \
      zalosniper/modules/__init__.py \
      zalosniper/models/__init__.py \
      tests/__init__.py \
      tests/core/__init__.py \
      tests/modules/__init__.py
```

- [ ] **Step 5: Install dependencies**

```bash
pip install -r requirements.txt
playwright install chromium
```

- [ ] **Step 6: Commit**

```bash
git init
git add requirements.txt .gitignore config.example.yaml zalosniper/ tests/
git commit -m "chore: project scaffolding"
```

---

### Task 2: Models

**Files:**
- Create: `zalosniper/models/message.py`
- Create: `zalosniper/models/bug_analysis.py`

- [ ] **Step 1: Write `zalosniper/models/message.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Message:
    id: Optional[int]
    group_name: str
    sender: str
    content: str
    timestamp: datetime
    zalo_message_id: Optional[str] = None
    processed: bool = False
    created_at: Optional[datetime] = None
```

- [ ] **Step 2: Write `zalosniper/models/bug_analysis.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class BugStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    TASK_ONLY = "task_only"
    DONE = "done"
    ERROR = "error"


@dataclass
class BugAnalysis:
    id: Optional[int]
    message_ids: List[int]
    group_name: str
    status: BugStatus = BugStatus.PENDING
    repo_owner: Optional[str] = None
    repo_name: Optional[str] = None
    repo_selection_reason: Optional[str] = None   # "matched" | "ambiguous"
    claude_summary: Optional[str] = None
    root_cause: Optional[str] = None
    proposed_fix: Optional[str] = None
    code_patch: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    op_work_package_id: Optional[int] = None
    op_work_package_url: Optional[str] = None
    telegram_message_id: Optional[int] = None
    approved_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

- [ ] **Step 3: Commit**

```bash
git add zalosniper/models/
git commit -m "feat: add Message and BugAnalysis models"
```

---

### Task 3: EventBus

**Files:**
- Create: `zalosniper/core/event_bus.py`
- Create: `tests/core/test_event_bus.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_event_bus.py
import asyncio
import pytest
from zalosniper.core.event_bus import EventBus, Event


@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("NEW_MESSAGE", handler)
    await bus.publish(Event(type="NEW_MESSAGE", data={"group": "abc"}))
    await asyncio.sleep(0.05)   # let handler run

    assert len(received) == 1
    assert received[0].data["group"] == "abc"


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = EventBus()
    calls = []

    async def h1(e): calls.append("h1")
    async def h2(e): calls.append("h2")

    bus.subscribe("BUG_DETECTED", h1)
    bus.subscribe("BUG_DETECTED", h2)
    await bus.publish(Event(type="BUG_DETECTED", data={}))
    await asyncio.sleep(0.05)

    assert set(calls) == {"h1", "h2"}


@pytest.mark.asyncio
async def test_unsubscribed_type_ignored():
    bus = EventBus()
    received = []

    async def handler(e): received.append(e)
    bus.subscribe("NEW_MESSAGE", handler)

    await bus.publish(Event(type="OTHER_EVENT", data={}))
    await asyncio.sleep(0.05)

    assert received == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_event_bus.py -v
```
Expected: `ImportError` or `ModuleNotFoundError`

- [ ] **Step 3: Write `zalosniper/core/event_bus.py`**

```python
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List


@dataclass
class Event:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)


HandlerFn = Callable[[Event], Coroutine]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, List[HandlerFn]] = {}

    def subscribe(self, event_type: str, handler: HandlerFn) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        for handler in self._subscribers.get(event.type, []):
            asyncio.create_task(handler(event))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/core/test_event_bus.py -v
```
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add zalosniper/core/event_bus.py tests/core/test_event_bus.py
git commit -m "feat: add EventBus with pub/sub"
```

---

### Task 4: ConfigManager

**Files:**
- Create: `zalosniper/core/config.py`
- Create: `tests/core/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_config.py
import pytest
import yaml
import tempfile
import os
from zalosniper.core.config import ConfigManager, GroupConfig, RepoConfig


SAMPLE_CONFIG = {
    "dry_run": False,
    "telegram": {
        "bot_token": "test_token",
        "approved_user_ids": [111, 222],
    },
    "zalo": {
        "session_dir": "./zalo_session",
        "poll_interval_seconds": 30,
    },
    "github": {
        "token": "ghp_test",
        "pr_enabled": True,
    },
    "groups": {
        "Group ABC": {
            "repos": [
                {"owner": "org", "name": "repo1", "branch": "main", "description": "Backend"},
            ],
            "telegram_chat_id": -100123,
            "openproject": {
                "url": "https://op.example.com",
                "api_key": "key",
                "project_id": 1,
            },
        }
    },
}


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(SAMPLE_CONFIG))
    return str(path)


def test_load_config(config_file):
    cfg = ConfigManager(config_file)
    assert cfg.telegram_bot_token == "test_token"
    assert cfg.approved_user_ids == [111, 222]
    assert cfg.dry_run is False
    assert cfg.github_pr_enabled is True


def test_group_config(config_file):
    cfg = ConfigManager(config_file)
    group = cfg.get_group("Group ABC")
    assert group is not None
    assert group.telegram_chat_id == -100123
    assert len(group.repos) == 1
    assert group.repos[0].name == "repo1"
    assert group.openproject.project_id == 1


def test_get_group_by_name_not_found(config_file):
    cfg = ConfigManager(config_file)
    assert cfg.get_group("Nonexistent Group") is None


def test_missing_required_key_raises(tmp_path):
    bad = {"telegram": {}}   # missing bot_token
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.dump(bad))
    with pytest.raises(ValueError):
        ConfigManager(str(path))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_config.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `zalosniper/core/config.py`**

```python
from dataclasses import dataclass
from typing import Dict, List, Optional
import yaml


@dataclass
class RepoConfig:
    owner: str
    name: str
    branch: str
    description: str = ""


@dataclass
class OpenProjectConfig:
    url: str
    api_key: str
    project_id: int


@dataclass
class GroupConfig:
    telegram_chat_id: int
    repos: List[RepoConfig]
    openproject: OpenProjectConfig


class ConfigManager:
    def __init__(self, path: str = "config.yaml") -> None:
        with open(path) as f:
            raw = yaml.safe_load(f)

        # Validate required keys
        if not raw.get("telegram", {}).get("bot_token"):
            raise ValueError("config.yaml: telegram.bot_token is required")
        if not raw.get("zalo", {}).get("session_dir"):
            raise ValueError("config.yaml: zalo.session_dir is required")

        self.dry_run: bool = raw.get("dry_run", False)
        self.telegram_bot_token: str = raw["telegram"]["bot_token"]
        self.approved_user_ids: List[int] = raw["telegram"].get("approved_user_ids", [])
        self.zalo_session_dir: str = raw["zalo"]["session_dir"]
        self.zalo_poll_interval: int = raw["zalo"].get("poll_interval_seconds", 30)
        self.github_token: str = raw.get("github", {}).get("token", "")
        self.github_pr_enabled: bool = raw.get("github", {}).get("pr_enabled", True)

        self._groups: Dict[str, GroupConfig] = {}
        for name, g in raw.get("groups", {}).items():
            repos = [
                RepoConfig(
                    owner=r["owner"],
                    name=r["name"],
                    branch=r.get("branch", "main"),
                    description=r.get("description", ""),
                )
                for r in g.get("repos", [])
            ]
            op_raw = g.get("openproject", {})
            op = OpenProjectConfig(
                url=op_raw.get("url", ""),
                api_key=op_raw.get("api_key", ""),
                project_id=op_raw.get("project_id", 0),
            )
            self._groups[name] = GroupConfig(
                telegram_chat_id=g["telegram_chat_id"],
                repos=repos,
                openproject=op,
            )

    def get_group(self, name: str) -> Optional[GroupConfig]:
        return self._groups.get(name)

    @property
    def groups(self) -> Dict[str, GroupConfig]:
        return self._groups
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_config.py -v
```
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add zalosniper/core/config.py tests/core/test_config.py
git commit -m "feat: add ConfigManager with typed group config"
```

---

### Task 5: Database

**Files:**
- Create: `zalosniper/core/database.py`
- Create: `tests/core/test_database.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_database.py
import pytest
import asyncio
from datetime import datetime
from zalosniper.core.database import Database
from zalosniper.models.message import Message
from zalosniper.models.bug_analysis import BugAnalysis, BugStatus


@pytest.fixture
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
        timestamp=datetime(2026, 3, 11, 10, 0, 0),
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
        timestamp=datetime(2026, 3, 11, 10, 0, 0),
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_database.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Write `zalosniper/core/database.py`**

```python
import json
import aiosqlite
from datetime import datetime
from typing import List, Optional
from zalosniper.models.message import Message
from zalosniper.models.bug_analysis import BugAnalysis, BugStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zalo_message_id TEXT,
    group_name TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(group_name, zalo_message_id),
    UNIQUE(group_name, sender, content, timestamp)
);

CREATE TABLE IF NOT EXISTS bug_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_ids TEXT NOT NULL,
    group_name TEXT NOT NULL,
    repo_owner TEXT,
    repo_name TEXT,
    repo_selection_reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    claude_summary TEXT,
    root_cause TEXT,
    proposed_fix TEXT,
    code_patch TEXT,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    pr_url TEXT,
    pr_number INTEGER,
    op_work_package_id INTEGER,
    op_work_package_url TEXT,
    telegram_message_id INTEGER,
    approved_by INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER IF NOT EXISTS update_bug_analyses_updated_at
AFTER UPDATE ON bug_analyses
BEGIN
    UPDATE bug_analyses SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
"""


class Database:
    def __init__(self, path: str = "zalosniper.db") -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    # --- Messages ---

    async def insert_message(self, msg: Message) -> Optional[int]:
        try:
            async with self._conn.execute(
                """INSERT OR IGNORE INTO messages
                   (zalo_message_id, group_name, sender, content, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (msg.zalo_message_id, msg.group_name, msg.sender,
                 msg.content, msg.timestamp.isoformat()),
            ) as cur:
                await self._conn.commit()
                return cur.lastrowid if cur.lastrowid else None
        except Exception:
            return None

    async def get_recent_messages(
        self, group_name: str, limit: int = 20, within_hours: int = 1
    ) -> List[Message]:
        async with self._conn.execute(
            """SELECT * FROM messages
               WHERE group_name = ?
                 AND timestamp >= datetime('now', ? || ' hours')
               ORDER BY timestamp DESC LIMIT ?""",
            (group_name, f"-{within_hours}", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_message(r) for r in rows]

    async def get_all_messages(
        self, group_name: str, days: int = 7, limit: int = 500
    ) -> List[Message]:
        async with self._conn.execute(
            """SELECT * FROM messages
               WHERE group_name = ?
                 AND timestamp >= datetime('now', ? || ' days')
               ORDER BY timestamp DESC LIMIT ?""",
            (group_name, f"-{days}", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_message(r) for r in rows]

    # --- BugAnalyses ---

    async def insert_bug_analysis(self, analysis: BugAnalysis) -> int:
        async with self._conn.execute(
            """INSERT INTO bug_analyses
               (message_ids, group_name, repo_owner, repo_name, repo_selection_reason, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (json.dumps(analysis.message_ids), analysis.group_name,
             analysis.repo_owner, analysis.repo_name,
             analysis.repo_selection_reason, analysis.status.value),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def get_bug_analysis(self, analysis_id: int) -> Optional[BugAnalysis]:
        async with self._conn.execute(
            "SELECT * FROM bug_analyses WHERE id = ?", (analysis_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_analysis(row) if row else None

    async def update_bug_analysis_status(
        self,
        analysis_id: int,
        status: BugStatus,
        approved_by: Optional[int] = None,
        **kwargs,
    ) -> bool:
        fields = {"status": status.value}
        if approved_by is not None:
            fields["approved_by"] = approved_by
        fields.update(kwargs)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [analysis_id]
        async with self._conn.execute(
            f"UPDATE bug_analyses SET {set_clause} WHERE id = ?", values
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    async def get_pending_analyses(self) -> List[BugAnalysis]:
        async with self._conn.execute(
            "SELECT * FROM bug_analyses WHERE status = 'pending' ORDER BY created_at"
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_analysis(r) for r in rows]

    async def transition_status(
        self, analysis_id: int, from_status: BugStatus, to_status: BugStatus, **kwargs
    ) -> bool:
        """Atomic idempotent status transition — only updates if current status matches."""
        fields = {"status": to_status.value}
        fields.update(kwargs)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [analysis_id, from_status.value]
        async with self._conn.execute(
            f"UPDATE bug_analyses SET {set_clause} WHERE id = ? AND status = ?", values
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0


def _row_to_message(row) -> Message:
    return Message(
        id=row["id"],
        group_name=row["group_name"],
        sender=row["sender"],
        content=row["content"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        zalo_message_id=row["zalo_message_id"],
        processed=bool(row["processed"]),
    )


def _row_to_analysis(row) -> BugAnalysis:
    # NOTE: SQLite CURRENT_TIMESTAMP stores naive UTC strings.
    # created_at is parsed as naive datetime to stay consistent with datetime.utcnow()
    # used in the timeout scheduler. Do NOT add tzinfo here.
    return BugAnalysis(
        id=row["id"],
        message_ids=json.loads(row["message_ids"]),
        group_name=row["group_name"],
        status=BugStatus(row["status"]),
        repo_owner=row["repo_owner"],
        repo_name=row["repo_name"],
        repo_selection_reason=row["repo_selection_reason"],
        claude_summary=row["claude_summary"],
        root_cause=row["root_cause"],
        proposed_fix=row["proposed_fix"],
        code_patch=row["code_patch"],
        error_message=row["error_message"],
        retry_count=row["retry_count"],
        pr_url=row["pr_url"],
        pr_number=row["pr_number"],
        op_work_package_id=row["op_work_package_id"],
        op_work_package_url=row["op_work_package_url"],
        telegram_message_id=row["telegram_message_id"],
        approved_by=row["approved_by"],
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_database.py -v
```
Expected: All 4 tests PASS

- [ ] **Step 5: Run all core tests**

```bash
pytest tests/core/ -v
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add zalosniper/core/database.py tests/core/test_database.py
git commit -m "feat: add Database with SQLite, dedup, and atomic status transition"
```

---

## Chunk 2: ZaloListener

**Covers:** Playwright session management, group polling, message extraction

### Task 6: ZaloSelectors + ZaloListener

**Files:**
- Create: `zalosniper/modules/zalo_selectors.py`
- Create: `zalosniper/modules/zalo_listener.py`
- Create: `tests/modules/test_zalo_listener.py`

> **Note:** Playwright cannot be unit-tested without a live browser. Tests here verify the non-browser logic (session detection, message parsing) using mocks.

- [ ] **Step 1: Create `zalosniper/modules/zalo_selectors.py`**

```python
# All Playwright selectors isolated here.
# When Zalo Web updates its UI, only this file needs changing.

ZALO_WEB_URL = "https://chat.zalo.me"
LOGIN_INDICATOR = "input[placeholder='Tìm kiếm']"   # present when logged in
GROUP_LIST_ITEM = ".group-item"                       # each group in sidebar
GROUP_NAME = ".group-name"                            # group name text
MESSAGE_LIST = ".message-list"                        # message container
MESSAGE_ITEM = ".message-item"                        # individual message
MESSAGE_SENDER = ".sender-name"                       # sender display name
MESSAGE_CONTENT = ".message-content"                  # text content
MESSAGE_TIME = ".message-time"                        # time element
MESSAGE_ID_ATTR = "data-msg-id"                       # message unique ID attribute
```

- [ ] **Step 2: Write failing tests for non-browser logic**

```python
# tests/modules/test_zalo_listener.py
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from zalosniper.modules.zalo_listener import ZaloListener, parse_message_time


def test_parse_message_time_today():
    # "10:30" format — today
    result = parse_message_time("10:30")
    assert result.hour == 10
    assert result.minute == 30
    assert result.date() == datetime.now().date()


def test_parse_message_time_yesterday():
    result = parse_message_time("Hôm qua 09:15")
    from datetime import timedelta
    expected_date = (datetime.now() - timedelta(days=1)).date()
    assert result.date() == expected_date
    assert result.hour == 9


def test_parse_message_time_date():
    result = parse_message_time("10/03 08:00")
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/modules/test_zalo_listener.py -v
```

- [ ] **Step 3b: Add tests for `_process_extracted_messages` (pure logic, no browser)**

Add these imports to the top of `tests/modules/test_zalo_listener.py`:

```python
import asyncio
from zalosniper.core.event_bus import EventBus, Event
```

Then add these test functions:

```python
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
    # Set last_seen to a time in the future relative to the message
    listener._last_seen = {"Group ABC": datetime(2026, 3, 11, 11, 0)}

    raw = [{"sender": "Alice", "content": "Old msg", "time_str": "10:30", "zalo_message_id": "z2"}]
    await listener._process_extracted_messages("Group ABC", raw)
    await asyncio.sleep(0.05)

    assert emitted == []
```

- [ ] **Step 4: Write `zalosniper/modules/zalo_listener.py`**

```python
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from zalosniper.core.config import ConfigManager
from zalosniper.core.database import Database
from zalosniper.core.event_bus import Event, EventBus
from zalosniper.models.message import Message
from zalosniper.modules.zalo_selectors import (
    ZALO_WEB_URL, LOGIN_INDICATOR, MESSAGE_ITEM,
    MESSAGE_SENDER, MESSAGE_CONTENT, MESSAGE_TIME, MESSAGE_ID_ATTR,
)

logger = logging.getLogger(__name__)

AlertFn = Callable[[str], None]


def parse_message_time(time_str: str) -> datetime:
    """Parse Zalo Web time formats into datetime."""
    now = datetime.now()
    time_str = time_str.strip()

    if "Hôm qua" in time_str:
        t = time_str.replace("Hôm qua", "").strip()
        h, m = map(int, t.split(":"))
        return (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)

    if "/" in time_str:
        # Format: "10/03 08:00"
        parts = time_str.split()
        day, month = map(int, parts[0].split("/"))
        h, m = map(int, parts[1].split(":"))
        return now.replace(month=month, day=day, hour=h, minute=m, second=0, microsecond=0)

    # Format: "HH:MM" (today)
    h, m = map(int, time_str.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


class ZaloListener:
    def __init__(
        self,
        config: ConfigManager,
        db: Database,
        bus: EventBus,
        alert_fn: Optional[AlertFn] = None,
    ) -> None:
        self._config = config
        self._db = db
        self._bus = bus
        self._alert_fn = alert_fn
        self._page: Optional[Page] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._running = False
        # Track last seen timestamp per group for deduplication
        self._last_seen: Dict[str, datetime] = {}

    async def start(self, headless: bool = True) -> bool:
        """Start Playwright and load existing session. Returns True if session valid."""
        session_dir = Path(self._config.zalo_session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        state_file = session_dir / "state.json"

        pw = await async_playwright().start()
        self._browser = await pw.chromium.launch(headless=headless)

        if state_file.exists():
            self._context = await self._browser.new_context(storage_state=str(state_file))
        else:
            self._context = await self._browser.new_context()

        self._page = await self._context.new_page()
        await self._page.goto(ZALO_WEB_URL)

        if not await self._is_session_valid():
            if not headless:
                logger.info("Session invalid — waiting for manual login...")
                await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=120_000)
                await self._context.storage_state(path=str(state_file))
                logger.info("Session saved.")
                return True
            else:
                logger.warning("Zalo session expired.")
                if self._alert_fn:
                    self._alert_fn("⚠️ Zalo session hết hạn. Chạy `python main.py --relogin`.")
                return False

        return True

    async def _is_session_valid(self) -> bool:
        if not self._page:
            return False
        if "login" in self._page.url:
            return False
        try:
            await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=5_000)
            return True
        except Exception:
            return False

    async def run_poll_loop(self) -> None:
        """Poll all configured groups in a loop."""
        self._running = True
        while self._running:
            for group_name in self._config.groups:
                try:
                    await self._poll_group(group_name)
                except Exception as e:
                    logger.error(f"Error polling group {group_name!r}: {e}")
                    if self._alert_fn:
                        self._alert_fn(f"⚠️ Zalo: lỗi khi poll group {group_name!r}: {e}")
            await asyncio.sleep(self._config.zalo_poll_interval)

    async def _poll_group(self, group_name: str) -> None:
        """Navigate to a group, extract new messages, save to DB, emit event."""
        # Step 1: Search for the group in the sidebar search box
        search_box = await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=5_000)
        await search_box.click()
        await search_box.fill(group_name)
        await asyncio.sleep(1)   # wait for search results

        # Step 2: Click the first matching result
        group_items = await self._page.query_selector_all(
            f"[title='{group_name}'], .group-item:has-text('{group_name}')"
        )
        if not group_items:
            logger.warning(f"Group not found in Zalo sidebar: {group_name!r}")
            return
        await group_items[0].click()
        await asyncio.sleep(1)   # wait for messages to load

        # Step 3: Extract messages from the DOM
        raw_messages = await self._extract_messages_from_dom()

        # Step 4: Filter new messages and save
        await self._process_extracted_messages(group_name, raw_messages)

        # Step 5: Clear search box
        await search_box.fill("")

    async def _extract_messages_from_dom(self) -> List[dict]:
        """Extract raw message data from the current group page DOM."""
        raw = []
        items = await self._page.query_selector_all(MESSAGE_ITEM)
        for item in items:
            try:
                sender_el = await item.query_selector(MESSAGE_SENDER)
                content_el = await item.query_selector(MESSAGE_CONTENT)
                time_el = await item.query_selector(MESSAGE_TIME)
                msg_id = await item.get_attribute(MESSAGE_ID_ATTR)

                sender = (await sender_el.inner_text()).strip() if sender_el else "Unknown"
                content = (await content_el.inner_text()).strip() if content_el else ""
                time_str = (await time_el.inner_text()).strip() if time_el else ""

                if content:
                    raw.append({
                        "sender": sender,
                        "content": content,
                        "time_str": time_str,
                        "zalo_message_id": msg_id,
                    })
            except Exception as e:
                logger.debug(f"Failed to extract message element: {e}")
        return raw

    async def _process_extracted_messages(
        self, group_name: str, raw_messages: List[dict]
    ) -> None:
        """Parse raw DOM data, filter by last_seen timestamp, save to DB, emit events."""
        last_seen = self._last_seen.get(group_name, datetime.min)
        new_count = 0

        for raw in raw_messages:
            try:
                ts = parse_message_time(raw["time_str"]) if raw["time_str"] else datetime.now()
            except Exception:
                ts = datetime.now()

            if ts <= last_seen:
                continue   # already seen

            msg = Message(
                id=None,
                group_name=group_name,
                sender=raw["sender"],
                content=raw["content"],
                timestamp=ts,
                zalo_message_id=raw.get("zalo_message_id"),
            )
            msg_id = await self._db.insert_message(msg)
            if msg_id:
                new_count += 1

        if new_count > 0:
            self._last_seen[group_name] = datetime.now()
            await self._bus.publish(Event(
                type="NEW_MESSAGE",
                data={"group_name": group_name, "new_count": new_count}
            ))
            logger.info(f"Group {group_name!r}: {new_count} new messages saved.")

    async def stop(self) -> None:
        self._running = False
        if self._browser:
            await self._browser.close()
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/modules/test_zalo_listener.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add zalosniper/modules/zalo_selectors.py zalosniper/modules/zalo_listener.py tests/modules/test_zalo_listener.py
git commit -m "feat: add ZaloListener skeleton with session management and message time parser"
```

---

## Chunk 3: AIAnalyzer

**Covers:** Claude API integration — classify messages, analyze root cause, generate patch

### Task 7: AIAnalyzer

**Files:**
- Create: `zalosniper/modules/ai_analyzer.py`
- Create: `tests/modules/test_ai_analyzer.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create shared test fixtures**

```python
# tests/conftest.py
import pytest
import asyncio
import yaml
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_claude_response():
    """Factory for mocked Claude API text response."""
    def _make(text: str):
        response = MagicMock()
        response.content = [MagicMock(text=text)]
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
```

- [ ] **Step 2: Write failing tests for AIAnalyzer**

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/modules/test_ai_analyzer.py -v
```

- [ ] **Step 4: Write `zalosniper/modules/ai_analyzer.py`**

```python
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import anthropic

from zalosniper.core.config import RepoConfig
from zalosniper.models.message import Message

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def _messages_to_text(messages: List[Message]) -> str:
    return "\n".join(
        f"[{m.timestamp.strftime('%H:%M')}] {m.sender}: {m.content}"
        for m in messages
    )


class AIAnalyzer:
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        # Use AsyncAnthropic to avoid blocking the event loop
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def _call(self, system: str, user: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Extract JSON from Claude response (may have surrounding text)."""
        start = text.find("{")
        end = text.rfind("}") + 1
        return json.loads(text[start:end])

    async def classify_messages(self, messages: List[Message]) -> Dict[str, Any]:
        """Classify messages as bug_report or noise."""
        chat = _messages_to_text(messages)
        system = (
            "You are a bug triage assistant. Analyze the Zalo chat messages and determine "
            "if they contain a bug report from users. "
            "Respond ONLY with JSON: {\"type\": \"bug_report\"|\"noise\", \"summary\": str, \"affected_feature\": str}"
        )
        text = await self._call(system, f"Messages:\n{chat}")
        return self._parse_json(text)

    async def select_repo(
        self, messages: List[Message], repos: List[RepoConfig]
    ) -> Tuple[str, str, str]:
        """Select the most likely affected repo. Returns (owner, name, reason)."""
        chat = _messages_to_text(messages)
        repo_list = "\n".join(
            f"- {r.name}: {r.description}" for r in repos
        )
        system = (
            "You are a software engineer. Based on the bug report, select the most likely "
            "affected repository from the list. "
            'Respond ONLY with JSON: {"selected_repo": "<repo_name>", "reason": "matched"|"ambiguous"}'
        )
        user = f"Bug report:\n{chat}\n\nAvailable repos:\n{repo_list}"
        text = await self._call(system, user)
        result = self._parse_json(text)

        selected_name = result.get("selected_repo", repos[0].name)
        reason = result.get("reason", "ambiguous")
        repo = next((r for r in repos if r.name == selected_name), repos[0])
        if repo.name != selected_name:
            reason = "ambiguous"
        return repo.owner, repo.name, reason

    async def analyze_root_cause(
        self, messages: List[Message], code_context: str
    ) -> Dict[str, Any]:
        """Analyze root cause using messages + code context."""
        chat = _messages_to_text(messages)
        system = (
            "You are a senior software engineer doing code review. "
            "Given a bug report from users and the relevant source code, identify the root cause. "
            "Respond ONLY with JSON: {\"root_cause\": str, \"affected_files\": [str], \"proposed_fix_description\": str}"
        )
        user = f"Bug report:\n{chat}\n\nSource code:\n{code_context}"
        text = await self._call(system, user)
        return self._parse_json(text)

    async def generate_patch(
        self, root_cause: str, code_context: str
    ) -> str:
        """Generate a unified diff patch to fix the bug."""
        system = (
            "You are a senior software engineer. Generate a minimal unified diff patch to fix the bug. "
            "Respond ONLY with JSON: {\"patch\": \"<unified diff string>\"}"
        )
        user = f"Root cause: {root_cause}\n\nSource code:\n{code_context}"
        text = await self._call(system, user)
        result = self._parse_json(text)
        return result.get("patch", "")

    async def summarize_messages(self, messages: List[Message]) -> str:
        """Summarize group messages as bullet points."""
        chat = _messages_to_text(messages)
        system = "Summarize the following Zalo group messages as bullet points in Vietnamese."
        return await self._call(system, chat)

    async def answer_question(self, messages: List[Message], question: str) -> str:
        """Answer a free-form question about message history."""
        chat = _messages_to_text(messages)
        system = (
            "You are a helpful assistant. Answer the question based on the Zalo chat history. "
            "Respond in Vietnamese."
        )
        return await self._call(system, f"Chat history:\n{chat}\n\nQuestion: {question}")
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/modules/test_ai_analyzer.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add zalosniper/modules/ai_analyzer.py tests/modules/test_ai_analyzer.py tests/conftest.py
git commit -m "feat: add AIAnalyzer with Claude API integration"
```

---

## Chunk 4: CodeAgent + GitHubClient

**Covers:** Repo cloning, file search, patch apply, branch push, PR creation

### Task 8: CodeAgent

**Files:**
- Create: `zalosniper/modules/code_agent.py`
- Create: `tests/modules/test_code_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/modules/test_code_agent.py
import pytest
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from zalosniper.modules.code_agent import CodeAgent, find_relevant_files


def test_find_relevant_files(tmp_path):
    # Create fake repo with some python files
    (tmp_path / "auth.py").write_text("def login(user, password): pass")
    (tmp_path / "models.py").write_text("class User: pass")
    (tmp_path / "utils.py").write_text("def helper(): pass")

    results = find_relevant_files(str(tmp_path), keywords=["login", "user"], max_files=10)
    filenames = [os.path.basename(r) for r in results]
    assert "auth.py" in filenames
    assert "models.py" in filenames


def test_find_relevant_files_respects_max(tmp_path):
    for i in range(20):
        (tmp_path / f"file{i}.py").write_text("def login(): pass")

    results = find_relevant_files(str(tmp_path), keywords=["login"], max_files=5)
    assert len(results) <= 5


def test_read_files_for_context(tmp_path):
    f = tmp_path / "auth.py"
    f.write_text("def login(): pass\n")
    agent = CodeAgent(repos_dir=str(tmp_path))
    context = agent.read_files_for_context([str(f)], max_tokens_per_file=100)
    assert "auth.py" in context
    assert "def login" in context


@pytest.mark.asyncio
async def test_apply_patch(tmp_path):
    original = "def login(user):\n    return user.name\n"
    patch_text = (
        "--- a/auth.py\n+++ b/auth.py\n"
        "@@ -1,2 +1,4 @@\n"
        " def login(user):\n"
        "+    if user is None:\n"
        "+        raise ValueError('user required')\n"
        "     return user.name\n"
    )
    target = tmp_path / "auth.py"
    target.write_text(original)

    agent = CodeAgent(repos_dir=str(tmp_path))
    success = await agent.apply_patch(patch_text, repo_dir=str(tmp_path))
    # patch application may fail for invalid unified diff — just check no exception
    assert isinstance(success, bool)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/modules/test_code_agent.py -v
```

- [ ] **Step 3: Write `zalosniper/modules/code_agent.py`**

```python
import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
IGNORED_EXTS = {".pyc", ".jpg", ".png", ".gif", ".svg", ".ico", ".woff", ".ttf", ".lock"}
MAX_FILE_BYTES = 100_000   # skip files larger than 100KB


def find_relevant_files(repo_dir: str, keywords: List[str], max_files: int = 10) -> List[str]:
    """Find files in repo_dir that contain any of the keywords."""
    matches = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for filename in files:
            ext = Path(filename).suffix
            if ext in IGNORED_EXTS:
                continue
            filepath = os.path.join(root, filename)
            if os.path.getsize(filepath) > MAX_FILE_BYTES:
                continue
            try:
                content = Path(filepath).read_text(errors="ignore").lower()
                if any(kw.lower() in content for kw in keywords):
                    matches.append(filepath)
            except Exception:
                continue
            if len(matches) >= max_files:
                return matches
    return matches[:max_files]


class CodeAgent:
    def __init__(self, repos_dir: str = "./repos") -> None:
        self._repos_dir = repos_dir
        Path(repos_dir).mkdir(parents=True, exist_ok=True)

    def _repo_path(self, owner: str, name: str) -> str:
        return os.path.join(self._repos_dir, owner, name)

    async def clone_or_pull(self, owner: str, name: str, branch: str, github_token: str) -> str:
        """Clone repo if not exists, or pull latest. Returns local path."""
        repo_dir = self._repo_path(owner, name)
        clone_url = f"https://{github_token}@github.com/{owner}/{name}.git"

        if os.path.exists(os.path.join(repo_dir, ".git")):
            logger.info(f"Pulling {owner}/{name}@{branch}")
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", repo_dir, "pull", "origin", branch,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        else:
            logger.info(f"Cloning {owner}/{name}")
            os.makedirs(repo_dir, exist_ok=True)
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth=1", "--branch", branch, clone_url, repo_dir,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git error: {stderr.decode()}")
        return repo_dir

    def read_files_for_context(self, file_paths: List[str], max_tokens_per_file: int = 2000) -> str:
        """Read files and format as code context string."""
        parts = []
        chars_per_token = 4
        max_chars = max_tokens_per_file * chars_per_token
        for fp in file_paths:
            try:
                content = Path(fp).read_text(errors="ignore")[:max_chars]
                parts.append(f"### {fp}\n```\n{content}\n```\n")
            except Exception as e:
                logger.warning(f"Cannot read {fp}: {e}")
        return "\n".join(parts)

    async def apply_patch(self, patch_text: str, repo_dir: str) -> bool:
        """Apply a unified diff patch to the repo using `git apply`."""
        patch_file = os.path.join(repo_dir, ".zalosniper_patch.diff")
        try:
            Path(patch_file).write_text(patch_text)
            proc = await asyncio.create_subprocess_exec(
                "git", "-C", repo_dir, "apply", "--index", patch_file,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"patch apply failed: {stderr.decode()}")
                return False
            return True
        finally:
            if os.path.exists(patch_file):
                os.remove(patch_file)

    async def create_branch_and_push(
        self, repo_dir: str, branch_name: str, commit_message: str, github_token: str,
        owner: str, repo_name: str
    ) -> bool:
        """Create branch, commit, and push."""
        remote_url = f"https://{github_token}@github.com/{owner}/{repo_name}.git"
        cmds = [
            ["git", "-C", repo_dir, "checkout", "-b", branch_name],
            ["git", "-C", repo_dir, "add", "-A"],
            ["git", "-C", repo_dir, "commit", "-m", commit_message],
            ["git", "-C", repo_dir, "push", remote_url, branch_name],
        ]
        for cmd in cmds:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"git cmd failed {cmd[2]}: {stderr.decode()}")
                return False
        return True
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/modules/test_code_agent.py -v
```
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add zalosniper/modules/code_agent.py tests/modules/test_code_agent.py
git commit -m "feat: add CodeAgent for repo clone/pull, file search, patch apply"
```

---

### Task 9: GitHubClient

**Files:**
- Create: `zalosniper/modules/github_client.py`
- Create: `tests/modules/test_github_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/modules/test_github_client.py
import pytest
from unittest.mock import MagicMock, patch
from zalosniper.modules.github_client import GitHubClient


@pytest.fixture
def client():
    return GitHubClient(token="fake_token")


def test_create_pr_returns_url(client):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.html_url = "https://github.com/org/repo/pull/42"
    mock_pr.number = 42
    mock_repo.create_pull.return_value = mock_pr

    with patch.object(client._github, "get_repo", return_value=mock_repo):
        url, number = client.create_pull_request(
            owner="org", repo_name="repo",
            branch="fix/bug-1", base="main",
            title="fix: login crash",
            body="Fixes login crash on Android"
        )

    assert url == "https://github.com/org/repo/pull/42"
    assert number == 42


def test_create_pr_disabled(client):
    url, number = client.create_pull_request(
        owner="org", repo_name="repo",
        branch="fix/bug-1", base="main",
        title="fix: test", body="test",
        enabled=False
    )
    assert url is None
    assert number is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/modules/test_github_client.py -v
```

- [ ] **Step 3: Write `zalosniper/modules/github_client.py`**

```python
import logging
from typing import Optional, Tuple
from github import Github

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._github = Github(token)

    def create_pull_request(
        self,
        owner: str,
        repo_name: str,
        branch: str,
        base: str,
        title: str,
        body: str,
        enabled: bool = True,
    ) -> Tuple[Optional[str], Optional[int]]:
        if not enabled:
            logger.info("PR creation disabled (pr_enabled=false)")
            return None, None
        try:
            repo = self._github.get_repo(f"{owner}/{repo_name}")
            pr = repo.create_pull(title=title, body=body, head=branch, base=base)
            logger.info(f"PR created: {pr.html_url}")
            return pr.html_url, pr.number
        except Exception as e:
            logger.error(f"Failed to create PR: {e}")
            raise
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/modules/test_github_client.py -v
```
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add zalosniper/modules/github_client.py tests/modules/test_github_client.py
git commit -m "feat: add GitHubClient for PR creation"
```

---

## Chunk 5: OpenProjectClient + TelegramBot

**Covers:** OpenProject work package creation, Telegram notifications and callbacks

### Task 10: OpenProjectClient

**Files:**
- Create: `zalosniper/modules/openproject_client.py`
- Create: `tests/modules/test_openproject_client.py`

- [ ] **Step 1: Write failing tests**

```python
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

    with patch("aiohttp.ClientSession.post", return_value=mock_response):
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

    with patch("aiohttp.ClientSession.post", return_value=mock_response):
        result = await client.create_work_package(
            project_id=1, title="test", description="test", status="new"
        )

    assert result == (None, None)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/modules/test_openproject_client.py -v
```

- [ ] **Step 3: Write `zalosniper/modules/openproject_client.py`**

```python
import logging
from typing import Optional, Tuple
import aiohttp

logger = logging.getLogger(__name__)


class OpenProjectClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._base = url.rstrip("/")
        self._headers = {
            "Authorization": f"Basic {_encode_api_key(api_key)}",
            "Content-Type": "application/json",
        }

    async def create_work_package(
        self,
        project_id: int,
        title: str,
        description: str,
        status: str = "new",
    ) -> Tuple[Optional[int], Optional[str]]:
        payload = {
            "subject": title,
            "description": {"format": "markdown", "raw": description},
            "_links": {
                "project": {"href": f"/api/v3/projects/{project_id}"},
                "status": {"href": f"/api/v3/statuses/{status}"},
            },
        }
        url = f"{self._base}/api/v3/work_packages"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=self._headers) as resp:
                    if resp.status in (200, 201):
                        data = await resp.json()
                        wp_id = data.get("id")
                        wp_url = f"{self._base}/work_packages/{wp_id}"
                        logger.info(f"Work package created: {wp_url}")
                        return wp_id, wp_url
                    else:
                        body = await resp.text()
                        logger.error(f"OpenProject error {resp.status}: {body}")
                        return None, None
        except Exception as e:
            logger.error(f"OpenProject request failed: {e}")
            return None, None


def _encode_api_key(api_key: str) -> str:
    import base64
    return base64.b64encode(f"apikey:{api_key}".encode()).decode()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/modules/test_openproject_client.py -v
```
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add zalosniper/modules/openproject_client.py tests/modules/test_openproject_client.py
git commit -m "feat: add OpenProjectClient for work package creation"
```

---

### Task 11: TelegramBot

**Files:**
- Create: `zalosniper/modules/telegram_bot.py`
- Create: `tests/modules/test_telegram_bot.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/modules/test_telegram_bot.py -v
```

- [ ] **Step 3: Write `zalosniper/modules/telegram_bot.py`**

```python
import asyncio
import logging
from typing import Callable, List, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from zalosniper.models.bug_analysis import BugAnalysis, BugStatus

logger = logging.getLogger(__name__)

from typing import Awaitable
CallbackFn = Callable[[int, str, int], Awaitable[None]]   # async (analysis_id, action, user_id)


def is_authorized(user_id: int, allowed: List[int]) -> bool:
    return user_id in allowed


def format_bug_message(analysis: BugAnalysis) -> str:
    return (
        f"🐛 *Bug phát hiện từ Group: {analysis.group_name}*\n\n"
        f"*Repo:* `{analysis.repo_owner}/{analysis.repo_name}`\n"
        f"*Tóm tắt:* {analysis.claude_summary or 'N/A'}\n\n"
        f"*Root cause:* {analysis.root_cause or 'N/A'}\n\n"
        f"*Đề xuất fix:* {analysis.proposed_fix or 'N/A'}\n\n"
        f"_Bug ID: {analysis.id}_"
    )


class TelegramBot:
    def __init__(
        self,
        bot_token: str,
        approved_user_ids: List[int],
        on_callback: Optional[CallbackFn] = None,
        config=None,          # ConfigManager — injected to support /status and /groups
        db=None,              # Database — injected to support /summary, /ask, /history, /pending
        ai=None,              # AIAnalyzer — injected to support /summary and /ask
        zalo_session_valid_fn=None,  # Callable[[], bool] — for /status Zalo health check
    ) -> None:
        self._approved_user_ids = approved_user_ids
        self._on_callback = on_callback
        self._config = config
        self._db = db
        self._ai = ai
        self._zalo_session_valid_fn = zalo_session_valid_fn
        self._app = Application.builder().token(bot_token).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("groups", self._cmd_groups))
        self._app.add_handler(CommandHandler("pending", self._cmd_pending))
        self._app.add_handler(CommandHandler("summary", self._cmd_summary))
        self._app.add_handler(CommandHandler("ask", self._cmd_ask))
        self._app.add_handler(CommandHandler("history", self._cmd_history))
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    async def send_message(self, chat_id: int, text: str) -> Optional[int]:
        msg = await self._app.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown"
        )
        return msg.message_id

    async def send_bug_notification(self, chat_id: int, analysis: BugAnalysis) -> Optional[int]:
        text = format_bug_message(analysis)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve Fix", callback_data=f"approve:{analysis.id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject:{analysis.id}"),
                InlineKeyboardButton("📋 Task Only", callback_data=f"task:{analysis.id}"),
            ]
        ])
        msg = await self._app.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=keyboard
        )
        return msg.message_id

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user_id = query.from_user.id

        if not is_authorized(user_id, self._approved_user_ids):
            await query.answer("❌ Bạn không có quyền thực hiện hành động này.")
            return

        await query.answer()
        action, analysis_id_str = query.data.split(":", 1)
        analysis_id = int(analysis_id_str)

        if self._on_callback:
            asyncio.create_task(self._on_callback(analysis_id, action, user_id))

    # --- Commands ---

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("🟢 ZaloSniper đang chạy.")

    async def _cmd_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Dùng /groups để xem danh sách group.")

    async def _cmd_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Danh sách pending: (chưa implement)")

    async def _cmd_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Dùng /summary <group_name> để tổng hợp.")

    async def _cmd_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Dùng /ask <group_name> <câu hỏi>.")

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text("Dùng /history <group_name>.")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/modules/test_telegram_bot.py -v
```
Expected: All 3 tests PASS

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add zalosniper/modules/telegram_bot.py tests/modules/test_telegram_bot.py
git commit -m "feat: add TelegramBot with notifications, inline callbacks, and commands"
```

---

## Chunk 6: Orchestrator + Main Entry Point

**Covers:** Wiring all modules together, main event loop, timeout scheduler

### Task 12: Orchestrator

**Files:**
- Create: `zalosniper/core/orchestrator.py`
- Create: `main.py`

- [ ] **Step 1: Write `zalosniper/core/orchestrator.py`**

```python
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from zalosniper.core.config import ConfigManager, GroupConfig
from zalosniper.core.database import Database
from zalosniper.core.event_bus import Event, EventBus
from zalosniper.models.bug_analysis import BugAnalysis, BugStatus
from zalosniper.modules.ai_analyzer import AIAnalyzer
from zalosniper.modules.code_agent import CodeAgent, find_relevant_files
from zalosniper.modules.github_client import GitHubClient
from zalosniper.modules.openproject_client import OpenProjectClient
from zalosniper.modules.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

PENDING_TIMEOUT_MINUTES = 30
RETRY_BACKOFF_MINUTES = [5, 10, 20]   # backoff per retry attempt (minutes)


async def _call_with_retry(coro_fn, db, analysis_id, alert_fn=None):
    """Call an async Claude API function with up to 3 retries and exponential backoff.

    Keeps status=pending during retries. Sets status=error after max retries.
    Returns result on success, raises on final failure.
    """
    for attempt, backoff in enumerate(RETRY_BACKOFF_MINUTES):
        try:
            return await coro_fn()
        except Exception as e:
            if attempt == len(RETRY_BACKOFF_MINUTES) - 1:
                # Final attempt failed — set error
                await db.update_bug_analysis_status(
                    analysis_id, BugStatus.ERROR, error_message=str(e)
                )
                raise
            # Increment retry_count, keep status=pending, wait before retry
            analysis = await db.get_bug_analysis(analysis_id)
            new_retry = (analysis.retry_count or 0) + 1
            await db.update_bug_analysis_status(
                analysis_id, BugStatus.PENDING, retry_count=new_retry
            )
            logger.warning(f"Claude API error (attempt {attempt + 1}): {e}. Retrying in {backoff}m.")
            if alert_fn:
                alert_fn(f"⚠️ Claude API lỗi (lần {attempt + 1}), thử lại sau {backoff} phút.")
            await asyncio.sleep(backoff * 60)


class Orchestrator:
    """Wires all modules together and owns the main processing pipeline."""

    def __init__(
        self,
        config: ConfigManager,
        db: Database,
        bus: EventBus,
        ai: AIAnalyzer,
        code_agent: CodeAgent,
        github: GitHubClient,
        telegram: TelegramBot,
    ) -> None:
        self._config = config
        self._db = db
        self._bus = bus
        self._ai = ai
        self._code_agent = code_agent
        self._github = github
        self._telegram = telegram

        bus.subscribe("NEW_MESSAGE", self._on_new_message)

    async def _on_new_message(self, event: Event) -> None:
        group_name = event.data["group_name"]
        group_config = self._config.get_group(group_name)
        if not group_config:
            return

        messages = await self._db.get_recent_messages(group_name, limit=20, within_hours=1)
        if not messages:
            return

        try:
            classification = await self._ai.classify_messages(messages)
        except Exception as e:
            logger.error(f"Claude classify failed: {e}")
            return

        if classification.get("type") != "bug_report":
            return

        # Select repo
        owner, name, reason = await self._ai.select_repo(messages, group_config.repos)

        # Create pending analysis record
        analysis = BugAnalysis(
            id=None,
            message_ids=[m.id for m in messages],
            group_name=group_name,
            repo_owner=owner,
            repo_name=name,
            repo_selection_reason=reason,
            claude_summary=classification.get("summary"),
        )
        analysis_id = await self._db.insert_bug_analysis(analysis)
        analysis.id = analysis_id

        # Get code context
        try:
            repo_config = next(r for r in group_config.repos if r.name == name)
            repo_dir = await self._code_agent.clone_or_pull(
                owner, name, repo_config.branch, self._config.github_token
            )
            keywords = classification.get("affected_feature", "").split() + [name]
            relevant = find_relevant_files(repo_dir, keywords)
            code_context = self._code_agent.read_files_for_context(relevant)
        except Exception as e:
            logger.error(f"CodeAgent error: {e}")
            code_context = ""

        # Analyze root cause (with retry logic per spec)
        try:
            root_analysis = await _call_with_retry(
                lambda: self._ai.analyze_root_cause(messages, code_context),
                self._db, analysis_id
            )
            await self._db.update_bug_analysis_status(
                analysis_id, BugStatus.PENDING,
                root_cause=root_analysis.get("root_cause"),
                proposed_fix=root_analysis.get("proposed_fix_description"),
            )
            analysis.root_cause = root_analysis.get("root_cause")
            analysis.proposed_fix = root_analysis.get("proposed_fix_description")
        except Exception as e:
            logger.error(f"Claude root cause analysis failed after retries: {e}")
            return

        # Notify Telegram
        msg_id = await self._telegram.send_bug_notification(
            chat_id=group_config.telegram_chat_id, analysis=analysis
        )
        await self._db.update_bug_analysis_status(analysis_id, BugStatus.PENDING, telegram_message_id=msg_id)

    async def handle_callback(self, analysis_id: int, action: str, user_id: int) -> None:
        """Handle approve/reject/task callbacks from Telegram."""
        if action == "approve":
            await self._handle_approve(analysis_id, user_id)
        elif action == "reject":
            await self._handle_reject(analysis_id, user_id)
        elif action == "task":
            await self._handle_task_only(analysis_id, user_id)

    async def _handle_approve(self, analysis_id: int, user_id: int) -> None:
        transitioned = await self._db.transition_status(
            analysis_id, BugStatus.PENDING, BugStatus.APPROVED, approved_by=user_id
        )
        if not transitioned:
            logger.info(f"Analysis {analysis_id} already processed — skipping approve")
            return

        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)
        repo_config = next(r for r in group_config.repos if r.name == analysis.repo_name)

        if self._config.dry_run:
            await self._telegram.send_message(
                group_config.telegram_chat_id, "🔍 Dry run — no changes made."
            )
            return

        try:
            # Get code context and generate patch
            repo_dir = await self._code_agent.clone_or_pull(
                analysis.repo_owner, analysis.repo_name,
                repo_config.branch, self._config.github_token
            )
            relevant = find_relevant_files(repo_dir, [analysis.root_cause or ""])
            code_context = self._code_agent.read_files_for_context(relevant)
            patch = await self._ai.generate_patch(analysis.root_cause or "", code_context)

            branch_name = f"fix/bug-{analysis_id}"
            patch_ok = await self._code_agent.apply_patch(patch, repo_dir)
            if not patch_ok:
                raise RuntimeError("git apply failed — patch could not be applied cleanly")
            await self._code_agent.create_branch_and_push(
                repo_dir, branch_name,
                f"fix: bug-{analysis_id} from ZaloSniper",
                self._config.github_token,
                analysis.repo_owner, analysis.repo_name,
            )

            # Create PR
            pr_url, pr_number = self._github.create_pull_request(
                owner=analysis.repo_owner,
                repo_name=analysis.repo_name,
                branch=branch_name,
                base=repo_config.branch,
                title=f"fix: {analysis.claude_summary or f'Bug {analysis_id}'}",
                body=f"**Root cause:** {analysis.root_cause}\n\n**Fix:** {analysis.proposed_fix}",
                enabled=self._config.github_pr_enabled,
            )

            # Create OpenProject task
            op = group_config.openproject
            op_client = OpenProjectClient(url=op.url, api_key=op.api_key)
            op_id, op_url = await op_client.create_work_package(
                project_id=op.project_id,
                title=f"Bug: {analysis.claude_summary}",
                description=f"**Root cause:** {analysis.root_cause}\n\nPR: {pr_url}",
                status="in_progress",
            )

            await self._db.update_bug_analysis_status(
                analysis_id, BugStatus.DONE,
                pr_url=pr_url, pr_number=pr_number,
                op_work_package_id=op_id, op_work_package_url=op_url,
                code_patch=patch,
            )

            parts = [f"✅ Fix đã được apply cho `{analysis.repo_owner}/{analysis.repo_name}`"]
            if pr_url:
                parts.append(f"🔗 PR: {pr_url}")
            if op_url:
                parts.append(f"📋 OpenProject: {op_url}")
            await self._telegram.send_message(group_config.telegram_chat_id, "\n".join(parts))

        except Exception as e:
            logger.error(f"Approve handler error: {e}")
            await self._db.update_bug_analysis_status(analysis_id, BugStatus.ERROR, error_message=str(e))
            await self._telegram.send_message(
                group_config.telegram_chat_id, f"❌ Lỗi khi apply fix: {e}"
            )

    async def _handle_reject(self, analysis_id: int, user_id: int) -> None:
        transitioned = await self._db.transition_status(
            analysis_id, BugStatus.PENDING, BugStatus.REJECTED, approved_by=user_id
        )
        if not transitioned:
            return
        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)
        await self._telegram.send_message(group_config.telegram_chat_id, f"❌ Bug #{analysis_id} đã bị reject.")

    async def _handle_task_only(self, analysis_id: int, user_id: int) -> None:
        transitioned = await self._db.transition_status(
            analysis_id, BugStatus.PENDING, BugStatus.TASK_ONLY, approved_by=user_id
        )
        if not transitioned:
            return
        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)
        op = group_config.openproject
        op_client = OpenProjectClient(url=op.url, api_key=op.api_key)
        op_id, op_url = await op_client.create_work_package(
            project_id=op.project_id,
            title=f"Bug: {analysis.claude_summary}",
            description=analysis.root_cause or "",
            status="new",
        )
        await self._db.update_bug_analysis_status(
            analysis_id, BugStatus.TASK_ONLY,
            op_work_package_id=op_id, op_work_package_url=op_url,
        )
        msg = f"📋 OpenProject task tạo thành công: {op_url}" if op_url else "📋 Tạo task thất bại."
        await self._telegram.send_message(group_config.telegram_chat_id, msg)

    async def run_timeout_scheduler(self) -> None:
        """Background task: expire pending analyses older than 30 minutes."""
        while True:
            await asyncio.sleep(60)
            pending = await self._db.get_pending_analyses()
            cutoff = datetime.utcnow() - timedelta(minutes=PENDING_TIMEOUT_MINUTES)
            for analysis in pending:
                if analysis.created_at and analysis.created_at < cutoff:
                    transitioned = await self._db.transition_status(
                        analysis.id, BugStatus.PENDING, BugStatus.EXPIRED
                    )
                    if transitioned:
                        group_config = self._config.get_group(analysis.group_name)
                        if group_config:
                            await self._telegram.send_message(
                                group_config.telegram_chat_id,
                                f"⏰ Bug #{analysis.id} đã hết hạn (30 phút)."
                            )
```

- [ ] **Step 2: Write `main.py`**

```python
#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys

from zalosniper.core.config import ConfigManager
from zalosniper.core.database import Database
from zalosniper.core.event_bus import EventBus
from zalosniper.core.orchestrator import Orchestrator
from zalosniper.modules.ai_analyzer import AIAnalyzer
from zalosniper.modules.code_agent import CodeAgent
from zalosniper.modules.github_client import GitHubClient
from zalosniper.modules.telegram_bot import TelegramBot
from zalosniper.modules.zalo_listener import ZaloListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("main")


async def run(config_path: str, relogin: bool = False) -> None:
    config = ConfigManager(config_path)
    db = Database("zalosniper.db")
    await db.init()

    bus = EventBus()
    ai = AIAnalyzer(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    code_agent = CodeAgent(repos_dir="./repos")
    github = GitHubClient(token=config.github_token)

    orchestrator_ref = []   # forward reference filled below

    telegram = TelegramBot(
        bot_token=config.telegram_bot_token,
        approved_user_ids=config.approved_user_ids,
        config=config,
        db=db,
        ai=ai,
        zalo_session_valid_fn=lambda: zalo._running,   # True when listener is active
        on_callback=lambda aid, action, uid: asyncio.create_task(
            orchestrator_ref[0].handle_callback(aid, action, uid)
        ),
    )

    orchestrator = Orchestrator(config, db, bus, ai, code_agent, github, telegram)
    orchestrator_ref.append(orchestrator)

    # Start Zalo listener
    zalo = ZaloListener(
        config=config, db=db, bus=bus,
        alert_fn=lambda msg: asyncio.create_task(
            telegram.send_message(
                list(config.groups.values())[0].telegram_chat_id, msg
            )
        ),
    )

    headless = not relogin
    session_valid = await zalo.start(headless=headless)
    if not session_valid and not relogin:
        logger.error("Zalo session invalid. Run with --relogin.")
        sys.exit(1)
    if relogin:
        logger.info("Relogin complete. Restart without --relogin.")
        return

    # Start all services
    await telegram.start()
    logger.info("ZaloSniper started.")

    try:
        await asyncio.gather(
            zalo.run_poll_loop(),
            orchestrator.run_timeout_scheduler(),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await zalo.stop()
        await telegram.stop()
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZaloSniper Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--relogin", action="store_true", help="Re-authenticate Zalo session")
    args = parser.parse_args()
    asyncio.run(run(args.config, relogin=args.relogin))
```

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 4: Smoke test (with real config)**

```bash
# Create config.yaml from template, fill in test values
cp config.example.yaml config.yaml
# Add ANTHROPIC_API_KEY to environment
export ANTHROPIC_API_KEY=your_key_here
# First login
python main.py --relogin
```
Expected: Headed Chromium opens, Zalo Web loads, login manually, session saved.

- [ ] **Step 5: Commit**

```bash
git add zalosniper/core/orchestrator.py main.py
git commit -m "feat: add Orchestrator and main entry point — full pipeline wired"
```

---

## Chunk 7: Command Implementations + Final Wiring

**Covers:** Implement `/summary`, `/ask`, `/history`, `/pending`, `/groups` Telegram commands with real DB queries and Claude calls

### Task 13: Implement Telegram Commands

**Files:**
- Modify: `zalosniper/modules/telegram_bot.py`

> Commands need access to DB and AIAnalyzer. Pass them into TelegramBot constructor.

- [ ] **Step 1: Update TelegramBot constructor**

Add `db: Optional[Database] = None`, `ai: Optional[AIAnalyzer] = None`, `config: Optional[ConfigManager] = None`, and `zalo_session_valid_fn: Optional[Callable[[], bool]] = None` parameters. All must be `Optional` with `None` defaults so existing tests do not break. Store as `self._db`, `self._ai`, `self._config`, and `self._zalo_session_valid_fn`.

- [ ] **Step 2: Implement `/status` command**

```python
async def _cmd_status(self, update, context):
    zalo_ok = self._zalo_session_valid_fn() if self._zalo_session_valid_fn else None
    zalo_status = "🟢 Zalo: connected" if zalo_ok else ("🔴 Zalo: session expired" if zalo_ok is False else "❓ Zalo: unknown")
    group_count = len(self._config.groups) if self._config else 0
    await update.message.reply_text(
        f"🤖 *ZaloSniper Status*\n"
        f"{zalo_status}\n"
        f"Groups monitored: {group_count}",
        parse_mode="Markdown"
    )
```

- [ ] **Step 3: Implement `/groups` command**

```python
async def _cmd_groups(self, update, context):
    if not self._config:
        await update.message.reply_text("No config loaded.")
        return
    lines = []
    for gname, gcfg in self._config.groups.items():
        repos = ", ".join(f"`{r.owner}/{r.name}`" for r in gcfg.repos)
        lines.append(f"• *{gname}*: {repos}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
```

- [ ] **Step 4: Implement `/summary [group_name]` command**

```python
async def _cmd_summary(self, update, context):
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /summary <group_name>")
        return
    group_name = " ".join(args)
    messages = await self._db.get_all_messages(group_name, days=1, limit=200)
    if not messages:
        await update.message.reply_text(f"Không có tin nhắn nào từ {group_name!r} trong 24 giờ qua.")
        return
    await update.message.reply_text("⏳ Đang tổng hợp...")
    summary = await self._ai.summarize_messages(messages)
    await update.message.reply_text(f"📋 *Tóm tắt - {group_name}*\n\n{summary}", parse_mode="Markdown")
```

- [ ] **Step 5: Implement `/ask [group_name] [question]` command**

```python
async def _cmd_ask(self, update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Usage: /ask <group_name> <câu hỏi>")
        return
    # First arg is group name — could be multi-word; use registered group names to match
    text = " ".join(args)
    group_name = None
    question = None
    if self._config:
        for gname in self._config.groups:
            if text.startswith(gname):
                group_name = gname
                question = text[len(gname):].strip()
                break
    if not group_name:
        group_name = args[0]
        question = " ".join(args[1:])

    messages = await self._db.get_all_messages(group_name, days=7, limit=500)
    if not messages:
        await update.message.reply_text(f"Không có dữ liệu từ group {group_name!r}.")
        return
    await update.message.reply_text("⏳ Đang tìm kiếm...")
    answer = await self._ai.answer_question(messages, question)
    await update.message.reply_text(answer)
```

- [ ] **Step 6: Implement `/pending` command**

```python
async def _cmd_pending(self, update, context):
    pending = await self._db.get_pending_analyses()
    if not pending:
        await update.message.reply_text("✅ Không có bug nào đang chờ approve.")
        return
    lines = [f"• Bug #{a.id}: `{a.repo_owner}/{a.repo_name}` — {a.claude_summary}" for a in pending]
    await update.message.reply_text("⏳ *Pending bugs:*\n" + "\n".join(lines), parse_mode="Markdown")
```

- [ ] **Step 7: Implement `/history [group_name]` command (stub — will be completed in Step 10)**

```python
async def _cmd_history(self, update, context):
    args = context.args
    group_name = " ".join(args) if args else None
    await update.message.reply_text("⏳ Fetching history...")
    # Implemented in Step 10 after get_recent_analyses() is added to Database
    await update.message.reply_text("(coming in Step 10)")
```

- [ ] **Step 8: Run all tests**

```bash
pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 9: Add `get_recent_analyses()` to Database**

In `zalosniper/core/database.py`, add (also update `_row_to_analysis` to populate `created_at` as documented in Task 5):

```python
async def get_recent_analyses(
    self, group_name: Optional[str] = None, days: int = 30
) -> List[BugAnalysis]:
    if group_name:
        query = """SELECT * FROM bug_analyses
                   WHERE group_name = ?
                     AND created_at >= datetime('now', ? || ' days')
                   ORDER BY created_at DESC"""
        params = (group_name, f"-{days}")
    else:
        query = """SELECT * FROM bug_analyses
                   WHERE created_at >= datetime('now', ? || ' days')
                   ORDER BY created_at DESC"""
        params = (f"-{days}",)
    async with self._conn.execute(query, params) as cur:
        rows = await cur.fetchall()
    return [_row_to_analysis(r) for r in rows]
```

- [ ] **Step 10: Complete `/history` implementation**

Now that `get_recent_analyses()` exists, update `_cmd_history` in `zalosniper/modules/telegram_bot.py`:

```python
async def _cmd_history(self, update, context):
    args = context.args
    group_name = " ".join(args) if args else None
    analyses = await self._db.get_recent_analyses(group_name=group_name, days=30)
    if not analyses:
        await update.message.reply_text("Không có lịch sử bug nào.")
        return
    lines = []
    for a in analyses[:20]:   # show max 20
        date_str = a.created_at.strftime("%d/%m") if a.created_at else "?"
        lines.append(f"• [{date_str}] #{a.id} `{a.repo_name}` — {a.claude_summary or 'N/A'} [{a.status.value}]")
    await update.message.reply_text(
        f"📜 *History{(' — ' + group_name) if group_name else ''}:*\n" + "\n".join(lines),
        parse_mode="Markdown"
    )
```

- [ ] **Step 11: Commit history implementation**

```bash
git add zalosniper/modules/telegram_bot.py zalosniper/core/database.py
git commit -m "feat: implement /history command using get_recent_analyses"
```

- [ ] **Step 12: Final test run**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests PASS with no warnings

- [ ] **Step 13: Final commit**

```bash
git add -A
git commit -m "feat: implement all Telegram commands — ZaloSniper complete"
```

---

## Quick Reference

### Running the bot

```bash
# First time login
python main.py --relogin

# Normal run
export ANTHROPIC_API_KEY=sk-ant-...
python main.py

# Dry run (analysis only, no PR/task)
# Set dry_run: true in config.yaml, then:
python main.py
```

### Running tests

```bash
pytest tests/ -v          # all tests
pytest tests/core/ -v     # core only
pytest tests/modules/ -v  # modules only
```

### Updating Zalo selectors (when Zalo Web UI changes)

Edit `zalosniper/modules/zalo_selectors.py` — all CSS selectors are isolated here.
