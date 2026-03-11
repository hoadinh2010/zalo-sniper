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
                alert_fn(f"Claude API loi (lan {attempt + 1}), thu lai sau {backoff} phut.")
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
                group_config.telegram_chat_id, "Dry run — no changes made."
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

            parts = [f"Fix da duoc apply cho `{analysis.repo_owner}/{analysis.repo_name}`"]
            if pr_url:
                parts.append(f"PR: {pr_url}")
            if op_url:
                parts.append(f"OpenProject: {op_url}")
            await self._telegram.send_message(group_config.telegram_chat_id, "\n".join(parts))

        except Exception as e:
            logger.error(f"Approve handler error: {e}")
            await self._db.update_bug_analysis_status(analysis_id, BugStatus.ERROR, error_message=str(e))
            await self._telegram.send_message(
                group_config.telegram_chat_id, f"Loi khi apply fix: {e}"
            )

    async def _handle_reject(self, analysis_id: int, user_id: int) -> None:
        transitioned = await self._db.transition_status(
            analysis_id, BugStatus.PENDING, BugStatus.REJECTED, approved_by=user_id
        )
        if not transitioned:
            return
        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)
        await self._telegram.send_message(group_config.telegram_chat_id, f"Bug #{analysis_id} da bi reject.")

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
        msg = f"OpenProject task tao thanh cong: {op_url}" if op_url else "Tao task that bai."
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
                                f"Bug #{analysis.id} da het han (30 phut)."
                            )
