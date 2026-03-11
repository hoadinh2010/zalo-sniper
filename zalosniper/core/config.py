from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os
import yaml


@dataclass
class AIConfig:
    provider: str = "gemini"          # gemini | zai | openai_compatible
    model: str = "gemini-2.0-flash"
    api_key: str = ""                  # falls back to env var if empty
    base_url: str = ""                 # required for openai_compatible

    def resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        env_map = {
            "gemini": "GEMINI_API_KEY",
            "zai": "ZAI_API_KEY",
        }
        env_var = env_map.get(self.provider, "AI_API_KEY")
        return os.environ.get(env_var, os.environ.get("AI_API_KEY", ""))


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
    project_id: str   # can be numeric id or slug, e.g. "lfc-ticketing-system"


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

        ai_raw = raw.get("ai", {})
        provider = ai_raw.get("provider", "gemini")
        _default_models = {"gemini": "gemini-2.0-flash", "zai": "glm-4.7-flash"}
        self.ai = AIConfig(
            provider=provider,
            model=ai_raw.get("model", _default_models.get(provider, "gpt-4o-mini")),
            api_key=ai_raw.get("api_key", ""),
            base_url=ai_raw.get("base_url", ""),
        )

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
                project_id=str(op_raw.get("project_id", "")),
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

    @classmethod
    async def from_db(cls, db) -> "ConfigManager":
        """Load config from SQLite DB (post-migration mode)."""
        import json as _json
        instance = object.__new__(cls)
        settings = await db.get_all_settings()

        instance.dry_run = settings.get("dry_run", "0") == "1"
        instance.github_token = settings.get("github_token", "")
        instance.github_pr_enabled = settings.get("github_pr_enabled", "1") == "1"
        instance.telegram_bot_token = settings.get("telegram_bot_token", "")
        instance.zalo_session_dir = settings.get("zalo_session_dir", "./zalo_session")
        instance.zalo_poll_interval = int(settings.get("zalo_poll_interval", "30"))
        instance.dashboard_port = int(settings.get("dashboard_port", "8080"))
        instance._db = db

        approved_raw = settings.get("approved_user_ids", "[]")
        try:
            instance.approved_user_ids = _json.loads(approved_raw)
        except Exception:
            instance.approved_user_ids = []

        provider = settings.get("ai_provider", "gemini")
        _default_models = {"gemini": "gemini-2.0-flash", "zai": "glm-4.7-flash"}
        instance.ai = AIConfig(
            provider=provider,
            model=settings.get("ai_model", _default_models.get(provider, "gpt-4o-mini")),
            api_key=settings.get("gemini_api_key" if provider == "gemini" else "zai_api_key" if provider == "zai" else "ai_api_key", ""),
            base_url=settings.get("ai_base_url", ""),
        )

        groups_rows = await db.get_all_groups()
        instance._groups = {}
        for g in groups_rows:
            if not g["enabled"]:
                continue
            repos_rows = await db.get_group_repos(g["id"])
            op = await db.get_group_openproject(g["id"])
            repos = [
                RepoConfig(
                    owner=r["owner"],
                    name=r["repo_name"],
                    branch=r["branch"],
                    description=r["description"],
                )
                for r in repos_rows
            ]
            op_cfg = OpenProjectConfig(
                url=op["op_url"] if op else "",
                api_key=op["op_api_key"] if op else "",
                project_id=op["op_project_id"] if op else "",
            )
            instance._groups[g["group_name"]] = GroupConfig(
                telegram_chat_id=g["telegram_chat_id"],
                repos=repos,
                openproject=op_cfg,
            )
        return instance

    async def reload_groups(self) -> None:
        """Reload groups from DB into memory (called after enable/disable)."""
        groups_rows = await self._db.get_all_groups()
        self._groups = {}
        for g in groups_rows:
            if not g["enabled"]:
                continue
            repos_rows = await self._db.get_group_repos(g["id"])
            op = await self._db.get_group_openproject(g["id"])
            repos = [
                RepoConfig(owner=r["owner"], name=r["repo_name"], branch=r["branch"], description=r["description"])
                for r in repos_rows
            ]
            op_cfg = OpenProjectConfig(
                url=op["op_url"] if op else "",
                api_key=op["op_api_key"] if op else "",
                project_id=op["op_project_id"] if op else "",
            )
            self._groups[g["group_name"]] = GroupConfig(
                telegram_chat_id=g["telegram_chat_id"],
                repos=repos,
                openproject=op_cfg,
            )
