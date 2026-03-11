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
