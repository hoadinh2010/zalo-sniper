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
                # rowcount == 0 means IGNORE fired (duplicate); lastrowid unchanged
                if cur.rowcount == 0:
                    return None
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
