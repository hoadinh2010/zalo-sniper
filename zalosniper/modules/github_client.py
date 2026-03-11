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
