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

SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS zalo_groups (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name       TEXT NOT NULL UNIQUE,
    telegram_chat_id INTEGER NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS group_repos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES zalo_groups(id) ON DELETE CASCADE,
    owner       TEXT NOT NULL,
    repo_name   TEXT NOT NULL,
    branch      TEXT NOT NULL DEFAULT 'main',
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS group_openproject (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id       INTEGER NOT NULL UNIQUE REFERENCES zalo_groups(id) ON DELETE CASCADE,
    op_url         TEXT NOT NULL DEFAULT '',
    op_api_key     TEXT NOT NULL DEFAULT '',
    op_project_id  TEXT NOT NULL DEFAULT ''
);

PRAGMA foreign_keys = ON;
"""

SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS notification_rules (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id            INTEGER NOT NULL UNIQUE REFERENCES zalo_groups(id) ON DELETE CASCADE,
    auto_create_op_task INTEGER NOT NULL DEFAULT 1,
    notify_telegram     INTEGER NOT NULL DEFAULT 1,
    min_severity        TEXT NOT NULL DEFAULT 'all'
);

CREATE TABLE IF NOT EXISTS assignment_rules (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id         INTEGER REFERENCES zalo_groups(id) ON DELETE CASCADE,
    keyword_pattern  TEXT NOT NULL,
    op_assignee_id   INTEGER,
    op_assignee_name TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS zalo_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    session_dir TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL DEFAULT 'inactive',
    last_login  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class Database:
    def __init__(self, path: str = "zalosniper.db") -> None:
        self._path = path
        self._conn: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.executescript(SCHEMA_V2)
        await self._conn.executescript(SCHEMA_V3)
        await self._conn.commit()
        await self._migrate_image_path()

    async def _migrate_image_path(self) -> None:
        """Add image_path column to messages table if missing."""
        try:
            await self._conn.execute("SELECT image_path FROM messages LIMIT 1")
        except Exception:
            await self._conn.execute("ALTER TABLE messages ADD COLUMN image_path TEXT")
            await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    # --- Messages ---

    async def insert_message(self, msg: Message) -> Optional[int]:
        try:
            # First check if a message with same group+sender+content exists
            # within a 10-minute window — this prevents duplicates caused by
            # Zalo Web re-rendering timestamps slightly differently each poll
            ts_iso = msg.timestamp.isoformat()
            async with self._conn.execute(
                """SELECT id FROM messages
                   WHERE group_name = ? AND sender = ? AND content = ?
                     AND abs(julianday(timestamp) - julianday(?)) < (10.0 / 1440.0)
                   LIMIT 1""",
                (msg.group_name, msg.sender, msg.content, ts_iso),
            ) as cur:
                if await cur.fetchone():
                    return None  # duplicate within 10-min window

            async with self._conn.execute(
                """INSERT OR IGNORE INTO messages
                   (zalo_message_id, group_name, sender, content, timestamp, image_path)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (msg.zalo_message_id, msg.group_name, msg.sender,
                 msg.content, ts_iso, msg.image_path),
            ) as cur:
                await self._conn.commit()
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
                 AND created_at >= datetime('now', ? || ' hours')
               ORDER BY id DESC LIMIT ?""",
            (group_name, f"-{within_hours}", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_message(r) for r in rows]

    async def get_unprocessed_messages(
        self, group_name: str, limit: int = 20, within_hours: int = 1
    ) -> List[Message]:
        """Get recent messages that haven't been sent to Telegram yet."""
        async with self._conn.execute(
            """SELECT * FROM messages
               WHERE group_name = ? AND processed = 0
                 AND created_at >= datetime('now', ? || ' hours')
               ORDER BY id DESC LIMIT ?""",
            (group_name, f"-{within_hours}", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_message(r) for r in rows]

    async def mark_messages_processed(self, message_ids: List[int]) -> None:
        """Mark messages as processed after sending Telegram notification."""
        if not message_ids:
            return
        placeholders = ",".join("?" * len(message_ids))
        await self._conn.execute(
            f"UPDATE messages SET processed = 1 WHERE id IN ({placeholders})",
            message_ids,
        )
        await self._conn.commit()

    async def mark_all_messages_processed(self) -> int:
        """Mark ALL unprocessed messages as processed.

        Used at bot startup to avoid re-processing historical messages
        that were already in Zalo before the bot started.
        """
        cur = await self._conn.execute(
            "UPDATE messages SET processed = 1 WHERE processed = 0"
        )
        await self._conn.commit()
        return cur.rowcount

    async def get_all_messages(
        self, group_name: str, days: int = 7, limit: int = 500
    ) -> List[Message]:
        async with self._conn.execute(
            """SELECT * FROM messages
               WHERE group_name = ?
                 AND created_at >= datetime('now', ? || ' days')
               ORDER BY id DESC LIMIT ?""",
            (group_name, f"-{days}", limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_message(r) for r in rows]

    # --- BugAnalyses ---

    async def insert_bug_analysis(self, analysis: BugAnalysis) -> int:
        async with self._conn.execute(
            """INSERT INTO bug_analyses
               (message_ids, group_name, repo_owner, repo_name, repo_selection_reason,
                status, claude_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (json.dumps(analysis.message_ids), analysis.group_name,
             analysis.repo_owner, analysis.repo_name,
             analysis.repo_selection_reason, analysis.status.value,
             analysis.claude_summary),
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

    async def get_recent_open_analysis(self, group_name: str, within_hours: int = 2) -> Optional[BugAnalysis]:
        """Get the most recent open (pending/task_only) bug analysis for a group."""
        async with self._conn.execute(
            """SELECT * FROM bug_analyses
               WHERE group_name = ? AND status IN ('pending', 'task_only')
                 AND created_at >= datetime('now', ? || ' hours')
               ORDER BY created_at DESC LIMIT 1""",
            (group_name, f"-{within_hours}"),
        ) as cur:
            row = await cur.fetchone()
        return _row_to_analysis(row) if row else None

    async def update_bug_analysis_context(
        self, analysis_id: int, message_ids: List[int], claude_summary: str
    ) -> bool:
        """Update an existing bug analysis with additional message IDs and refined summary."""
        analysis = await self.get_bug_analysis(analysis_id)
        if not analysis:
            return False
        merged_ids = list(set(analysis.message_ids + message_ids))
        async with self._conn.execute(
            "UPDATE bug_analyses SET message_ids = ?, claude_summary = ? WHERE id = ?",
            (json.dumps(merged_ids), claude_summary, analysis_id),
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

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

    async def delete_bug_analysis(self, analysis_id: int) -> bool:
        async with self._conn.execute(
            "DELETE FROM bug_analyses WHERE id = ?", (analysis_id,)
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

    # --- Settings ---

    async def get_setting(self, key: str) -> Optional[str]:
        async with self._conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, key: str, value: str) -> None:
        await self._conn.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value),
        )
        await self._conn.commit()

    async def get_all_settings(self) -> dict:
        async with self._conn.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def set_many_settings(self, items: dict) -> None:
        for key, value in items.items():
            await self.set_setting(key, value)

    # --- Groups ---

    async def get_all_groups(self) -> list:
        async with self._conn.execute(
            "SELECT id, group_name, telegram_chat_id, enabled, created_at FROM zalo_groups ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def create_group(self, group_name: str, telegram_chat_id: int) -> int:
        async with self._conn.execute(
            "INSERT INTO zalo_groups (group_name, telegram_chat_id) VALUES (?, ?)",
            (group_name, telegram_chat_id),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def update_group(self, group_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [group_id]
        async with self._conn.execute(
            f"UPDATE zalo_groups SET {set_clause} WHERE id = ?", values
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    async def delete_group(self, group_id: int) -> bool:
        async with self._conn.execute(
            "DELETE FROM zalo_groups WHERE id = ?", (group_id,)
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    # --- Repos ---

    async def get_group_repos(self, group_id: int) -> list:
        async with self._conn.execute(
            "SELECT id, group_id, owner, repo_name, branch, description FROM group_repos WHERE group_id = ?",
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def add_group_repo(self, group_id: int, owner: str, repo_name: str, branch: str, description: str) -> int:
        async with self._conn.execute(
            "INSERT INTO group_repos (group_id, owner, repo_name, branch, description) VALUES (?, ?, ?, ?, ?)",
            (group_id, owner, repo_name, branch, description),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def update_group_repo(self, repo_id: int, **kwargs) -> bool:
        if not kwargs:
            return False
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [repo_id]
        async with self._conn.execute(
            f"UPDATE group_repos SET {set_clause} WHERE id = ?", values
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    async def delete_group_repo(self, repo_id: int) -> bool:
        async with self._conn.execute(
            "DELETE FROM group_repos WHERE id = ?", (repo_id,)
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    # --- OpenProject ---

    async def get_group_openproject(self, group_id: int) -> Optional[dict]:
        async with self._conn.execute(
            "SELECT id, group_id, op_url, op_api_key, op_project_id FROM group_openproject WHERE group_id = ?",
            (group_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def upsert_group_openproject(self, group_id: int, op_url: str, op_api_key: str, op_project_id: str) -> None:
        await self._conn.execute(
            """INSERT INTO group_openproject (group_id, op_url, op_api_key, op_project_id)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(group_id) DO UPDATE SET
                   op_url=excluded.op_url,
                   op_api_key=excluded.op_api_key,
                   op_project_id=excluded.op_project_id""",
            (group_id, op_url, op_api_key, op_project_id),
        )
        await self._conn.commit()

    # --- Migration ---

    async def migrate_from_yaml(self, yaml_path: str) -> None:
        """One-time migration: import config.yaml into DB. Safe to call multiple times."""
        import yaml as _yaml
        import json as _json
        # Check if already migrated
        groups = await self.get_all_groups()
        if groups:
            return  # already has data — skip

        try:
            with open(yaml_path) as f:
                raw = _yaml.safe_load(f)
        except FileNotFoundError:
            return  # fresh install — no yaml to migrate

        # Migrate settings
        settings = {}
        tg = raw.get("telegram", {})
        if tg.get("bot_token"):
            settings["telegram_bot_token"] = tg["bot_token"]
        if tg.get("approved_user_ids"):
            settings["approved_user_ids"] = _json.dumps(tg["approved_user_ids"])

        zalo = raw.get("zalo", {})
        if zalo.get("session_dir"):
            settings["zalo_session_dir"] = zalo["session_dir"]
        settings["zalo_poll_interval"] = str(zalo.get("poll_interval_seconds", 30))

        gh = raw.get("github", {})
        if gh.get("token"):
            settings["github_token"] = gh["token"]
        settings["github_pr_enabled"] = "1" if gh.get("pr_enabled", True) else "0"
        settings["dry_run"] = "1" if raw.get("dry_run", False) else "0"

        ai = raw.get("ai", {})
        if ai.get("provider"):
            settings["ai_provider"] = ai["provider"]
        if ai.get("model"):
            settings["ai_model"] = ai["model"]
        if ai.get("base_url"):
            settings["ai_base_url"] = ai["base_url"]
        if ai.get("api_key"):
            # Store under the provider-specific key
            provider = settings.get("ai_provider", ai.get("provider", "gemini"))
            key_name = "gemini_api_key" if provider == "gemini" else "zai_api_key" if provider == "zai" else "ai_api_key"
            settings[key_name] = ai["api_key"]

        await self.set_many_settings(settings)

        # Migrate groups
        for group_name, g in raw.get("groups", {}).items():
            gid = await self.create_group(group_name, g["telegram_chat_id"])
            for r in g.get("repos", []):
                await self.add_group_repo(
                    gid, r["owner"], r["name"],
                    r.get("branch", "main"), r.get("description", "")
                )
            op = g.get("openproject", {})
            if op:
                await self.upsert_group_openproject(
                    gid,
                    op.get("url", ""),
                    op.get("api_key", ""),
                    str(op.get("project_id", "")),
                )

    # --- Dashboard stats ---

    async def get_dashboard_stats(self) -> dict:
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM bug_analyses WHERE status = 'done'"
        ) as cur:
            bugs_done = (await cur.fetchone())["c"]
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM zalo_groups WHERE enabled = 1"
        ) as cur:
            groups_active = (await cur.fetchone())["c"]
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM bug_analyses WHERE status = 'pending'"
        ) as cur:
            pending = (await cur.fetchone())["c"]
        async with self._conn.execute(
            "SELECT COUNT(*) as c FROM bug_analyses WHERE pr_url IS NOT NULL"
        ) as cur:
            prs_created = (await cur.fetchone())["c"]
        async with self._conn.execute(
            """SELECT id, group_name, repo_name, status, claude_summary, created_at,
                      op_work_package_id, op_work_package_url, pr_url
               FROM bug_analyses ORDER BY created_at DESC LIMIT 20"""
        ) as cur:
            recent = [dict(r) for r in await cur.fetchall()]
        return {
            "bugs_done": bugs_done,
            "groups_active": groups_active,
            "pending": pending,
            "prs_created": prs_created,
            "recent_analyses": recent,
        }


    # --- Notification Rules ---

    async def get_notification_rules(self, group_id: int) -> dict:
        async with self._conn.execute(
            "SELECT * FROM notification_rules WHERE group_id = ?", (group_id,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)
        return {"group_id": group_id, "auto_create_op_task": 1, "notify_telegram": 1, "min_severity": "all"}

    async def upsert_notification_rules(self, group_id: int, auto_create_op_task: int, notify_telegram: int, min_severity: str = "all") -> None:
        await self._conn.execute(
            """INSERT INTO notification_rules (group_id, auto_create_op_task, notify_telegram, min_severity)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(group_id) DO UPDATE SET
                   auto_create_op_task=excluded.auto_create_op_task,
                   notify_telegram=excluded.notify_telegram,
                   min_severity=excluded.min_severity""",
            (group_id, auto_create_op_task, notify_telegram, min_severity),
        )
        await self._conn.commit()

    async def get_notification_rules_by_group_name(self, group_name: str) -> dict:
        async with self._conn.execute(
            """SELECT nr.* FROM notification_rules nr
               JOIN zalo_groups zg ON nr.group_id = zg.id
               WHERE zg.group_name = ?""",
            (group_name,),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return dict(row)
        return {"auto_create_op_task": 1, "notify_telegram": 1, "min_severity": "all"}

    # --- Assignment Rules ---

    async def get_assignment_rules(self, group_id: int = None) -> list:
        if group_id:
            query = "SELECT * FROM assignment_rules WHERE group_id = ? ORDER BY id"
            params = (group_id,)
        else:
            query = "SELECT * FROM assignment_rules ORDER BY id"
            params = ()
        async with self._conn.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def add_assignment_rule(self, group_id: int, keyword_pattern: str, op_assignee_id: int, op_assignee_name: str) -> int:
        async with self._conn.execute(
            "INSERT INTO assignment_rules (group_id, keyword_pattern, op_assignee_id, op_assignee_name) VALUES (?, ?, ?, ?)",
            (group_id, keyword_pattern, op_assignee_id, op_assignee_name),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def delete_assignment_rule(self, rule_id: int) -> bool:
        async with self._conn.execute("DELETE FROM assignment_rules WHERE id = ?", (rule_id,)) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    async def match_assignment_rule(self, group_name: str, summary: str) -> Optional[dict]:
        async with self._conn.execute(
            """SELECT ar.* FROM assignment_rules ar
               JOIN zalo_groups zg ON ar.group_id = zg.id
               WHERE zg.group_name = ?""",
            (group_name,),
        ) as cur:
            rules = [dict(r) for r in await cur.fetchall()]
        summary_lower = summary.lower()
        for rule in rules:
            if rule["keyword_pattern"].lower() in summary_lower:
                return rule
        return None

    # --- Zalo Accounts ---

    async def get_all_zalo_accounts(self) -> list:
        async with self._conn.execute("SELECT * FROM zalo_accounts ORDER BY id") as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def add_zalo_account(self, name: str, session_dir: str) -> int:
        async with self._conn.execute(
            "INSERT INTO zalo_accounts (name, session_dir) VALUES (?, ?)",
            (name, session_dir),
        ) as cur:
            await self._conn.commit()
            return cur.lastrowid

    async def update_zalo_account_status(self, account_id: int, status: str) -> bool:
        async with self._conn.execute(
            "UPDATE zalo_accounts SET status = ?, last_login = datetime('now') WHERE id = ?",
            (status, account_id),
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    async def delete_zalo_account(self, account_id: int) -> bool:
        async with self._conn.execute(
            "DELETE FROM zalo_accounts WHERE id = ?", (account_id,)
        ) as cur:
            await self._conn.commit()
            return cur.rowcount > 0

    # --- Webhook lookup ---

    async def get_analysis_by_op_id(self, op_work_package_id: int) -> Optional[BugAnalysis]:
        async with self._conn.execute(
            "SELECT * FROM bug_analyses WHERE op_work_package_id = ?", (op_work_package_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_analysis(row) if row else None

    # --- Analytics ---

    async def get_analytics(self, period_days: int = 7) -> dict:
        period_param = f"-{period_days}"
        async with self._conn.execute(
            """SELECT date(created_at) as day, COUNT(*) as count
               FROM bug_analyses
               WHERE created_at >= datetime('now', ? || ' days')
               GROUP BY date(created_at) ORDER BY day""",
            (period_param,),
        ) as cur:
            bugs_by_day = [dict(r) for r in await cur.fetchall()]
        async with self._conn.execute(
            """SELECT group_name, COUNT(*) as count
               FROM bug_analyses
               WHERE created_at >= datetime('now', ? || ' days')
               GROUP BY group_name ORDER BY count DESC""",
            (period_param,),
        ) as cur:
            bugs_by_group = [dict(r) for r in await cur.fetchall()]
        async with self._conn.execute(
            """SELECT status, COUNT(*) as count
               FROM bug_analyses
               WHERE created_at >= datetime('now', ? || ' days')
               GROUP BY status ORDER BY count DESC""",
            (period_param,),
        ) as cur:
            bugs_by_status = [dict(r) for r in await cur.fetchall()]
        return {
            "bugs_by_day": bugs_by_day,
            "bugs_by_group": bugs_by_group,
            "bugs_by_status": bugs_by_status,
            "period_days": period_days,
        }


def _row_to_message(row) -> Message:
    return Message(
        id=row["id"],
        group_name=row["group_name"],
        sender=row["sender"],
        content=row["content"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        zalo_message_id=row["zalo_message_id"],
        processed=bool(row["processed"]),
        image_path=row["image_path"] if "image_path" in row.keys() else None,
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
