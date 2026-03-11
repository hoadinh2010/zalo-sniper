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
