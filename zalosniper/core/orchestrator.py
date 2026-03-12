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
    """Call an async Gemini API function with up to 3 retries and exponential backoff.

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
            logger.warning(f"Gemini API error (attempt {attempt + 1}): {e}. Retrying in {backoff}m.")
            if alert_fn:
                alert_fn(
                    f"Gemini gap loi khi phan tich bug (lan thu {attempt + 1}/{len(RETRY_BACKOFF_MINUTES)}): "
                    f"{e}\nSe thu lai sau {backoff} phut."
                )
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
        new_count = event.data.get("new_count", 0)
        group_config = self._config.get_group(group_name)
        if not group_config:
            return

        messages = await self._db.get_recent_messages(group_name, limit=20, within_hours=1)
        if not messages:
            return

        # Single AI call: summarize + classify together (saves rate-limit quota)
        try:
            triage = await self._ai.triage_messages(messages)
        except Exception as e:
            logger.error(f"AI triage_messages failed for group {group_name!r}: {e}")
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"AI gap loi khi phan tich tin nhan tu nhom [{group_name}]: {e}",
            )
            return

        now_str = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
        summary = triage.get("summary", "")
        issues = triage.get("issues", [])
        is_bug = triage.get("type") == "bug_report"

        lines = [
            f"[{now_str}] Nhom: {group_name} — {new_count} tin nhan moi",
            "",
            f"Tom tat: {summary}",
        ]
        if issues:
            lines.append("")
            lines.append(f"Phat hien {len(issues)} van de:")
            for i, issue in enumerate(issues, 1):
                lines.append(f"\n#{i}. {issue.get('title', '')}")
                lines.append(f"   Mo ta: {issue.get('description', '')}")
                lines.append(f"   Huong xu ly: {issue.get('proposed_solution', '')}")
        elif not is_bug:
            lines.append("(Khong co bug report)")

        await self._telegram.send_message(
            group_config.telegram_chat_id,
            "\n".join(lines),
        )

        if not is_bug:
            return

        # Save analysis record without repo — repo selection happens when user presses "Xử lý task"
        analysis = BugAnalysis(
            id=None,
            message_ids=[m.id for m in messages],
            group_name=group_name,
            claude_summary=summary,
        )
        analysis_id = await self._db.insert_bug_analysis(analysis)
        analysis.id = analysis_id

        # Send Telegram notification with Approve / Reject buttons
        # Code analysis only happens AFTER user approves
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
        elif action == "process":
            await self._handle_process(analysis_id, user_id)

    async def _handle_approve(self, analysis_id: int, user_id: int) -> None:
        """Full approval: code analysis + OpenProject task + PR (repo must already be selected)."""
        transitioned = await self._db.transition_status(
            analysis_id, BugStatus.PENDING, BugStatus.APPROVED, approved_by=user_id
        )
        if not transitioned:
            logger.info(f"Analysis {analysis_id} already processed — skipping approve")
            return

        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)
        if not analysis.repo_name:
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"Bug #{analysis_id}: chua co repo duoc chon — hay dung 'Xu ly task' sau khi tao task.",
            )
            return
        repo_config = next(r for r in group_config.repos if r.name == analysis.repo_name)

        await self._telegram.send_message(
            group_config.telegram_chat_id,
            f"Da nhan Approve cho Bug #{analysis_id}. Dang phan tich code...",
        )

        if self._config.dry_run:
            await self._telegram.send_message(
                group_config.telegram_chat_id, "Dry run — khong thay doi code."
            )
            return

        # Step 1: Clone repo and analyze root cause
        try:
            repo_dir = await self._code_agent.clone_or_pull(
                analysis.repo_owner, analysis.repo_name,
                repo_config.branch, self._config.github_token
            )
            keywords = (analysis.claude_summary or "").split() + [analysis.repo_name]
            relevant = find_relevant_files(repo_dir, keywords)
            code_context = self._code_agent.read_files_for_context(relevant)
        except Exception as e:
            logger.error(f"CodeAgent error for analysis {analysis_id}: {e}")
            code_context = ""

        try:
            context_messages = await self._db.get_recent_messages(
                analysis.group_name, limit=20, within_hours=6
            )
            root_analysis = await _call_with_retry(
                lambda: self._ai.analyze_root_cause(context_messages, code_context),
                self._db, analysis_id,
                alert_fn=lambda msg: asyncio.create_task(
                    self._telegram.send_message(group_config.telegram_chat_id, msg)
                ),
            )
            root_cause = root_analysis.get("root_cause", "")
            proposed_fix = root_analysis.get("proposed_fix_description", "")
            await self._db.update_bug_analysis_status(
                analysis_id, BugStatus.APPROVED,
                root_cause=root_cause,
                proposed_fix=proposed_fix,
            )
            analysis.root_cause = root_cause
            analysis.proposed_fix = proposed_fix
        except Exception as e:
            logger.error(f"Root cause analysis failed for analysis {analysis_id}: {e}")
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"AI khong the phan tich root cause cho Bug #{analysis_id}: {e}",
            )
            return

        # Step 2: Create OpenProject issue
        pr_url, pr_number, op_url, op_id = None, None, None, None
        try:
            op = group_config.openproject
            op_client = OpenProjectClient(url=op.url, api_key=op.api_key)
            op_id, op_url = await op_client.create_work_package(
                project_id=op.project_id,
                title=f"Bug: {analysis.claude_summary}",
                description=(
                    f"**Tóm tắt:** {analysis.claude_summary}\n\n"
                    f"**Root cause:** {root_cause}\n\n"
                    f"**Đề xuất fix:** {proposed_fix}"
                ),
            )
        except Exception as e:
            logger.error(f"OpenProject create_work_package failed: {e}")
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"Loi khi tao OpenProject task cho Bug #{analysis_id}: {e}",
            )

        # Step 3: Generate patch and create PR (if not dry run)
        try:
            patch = await self._ai.generate_patch(root_cause, code_context)
            branch_name = f"fix/bug-{analysis_id}"
            patch_ok = await self._code_agent.apply_patch(patch, repo_dir)
            if patch_ok:
                push_ok = await self._code_agent.create_branch_and_push(
                    repo_dir, branch_name,
                    f"fix: bug-{analysis_id} from ZaloSniper",
                    self._config.github_token,
                    analysis.repo_owner, analysis.repo_name,
                )
                if push_ok:
                    pr_url, pr_number = self._github.create_pull_request(
                        owner=analysis.repo_owner,
                        repo_name=analysis.repo_name,
                        branch=branch_name,
                        base=repo_config.branch,
                        title=f"fix: {analysis.claude_summary or f'Bug {analysis_id}'}",
                        body=(
                            f"**Root cause:** {root_cause}\n\n"
                            f"**Fix:** {proposed_fix}\n\n"
                            + (f"OpenProject: {op_url}" if op_url else "")
                        ),
                        enabled=self._config.github_pr_enabled,
                    )
        except Exception as e:
            logger.error(f"Patch/PR creation failed for analysis {analysis_id}: {e}")
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"Khong the tao patch/PR tu dong cho Bug #{analysis_id}: {e}\n"
                f"Vui long fix thu cong dua tren root cause o tren.",
            )

        await self._db.update_bug_analysis_status(
            analysis_id, BugStatus.DONE,
            pr_url=pr_url, pr_number=pr_number,
            op_work_package_id=op_id, op_work_package_url=op_url,
        )

        parts = [f"Bug #{analysis_id} da duoc xu ly:"]
        parts.append(f"Root cause: {root_cause}")
        if op_url:
            parts.append(f"OpenProject task: {op_url}")
        if pr_url:
            parts.append(f"PR: {pr_url}")
        elif not pr_url:
            parts.append("(Chua tao duoc PR tu dong — vui long fix thu cong)")
        await self._telegram.send_message(group_config.telegram_chat_id, "\n".join(parts))

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
        """Create OpenProject task only — then offer 'Xử lý task' button for code fix."""
        transitioned = await self._db.transition_status(
            analysis_id, BugStatus.PENDING, BugStatus.TASK_ONLY, approved_by=user_id
        )
        if not transitioned:
            return
        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)
        try:
            op = group_config.openproject
            op_client = OpenProjectClient(url=op.url, api_key=op.api_key)
            op_id, op_url = await op_client.create_work_package(
                project_id=op.project_id,
                title=f"Bug: {analysis.claude_summary}",
                description=f"**Tóm tắt từ Zalo:** {analysis.claude_summary}",
            )
            await self._db.update_bug_analysis_status(
                analysis_id, BugStatus.TASK_ONLY,
                op_work_package_id=op_id, op_work_package_url=op_url,
            )
            task_line = f"\nOpenProject: {op_url}" if op_url else ""
            await self._telegram.send_process_button(
                chat_id=group_config.telegram_chat_id,
                analysis_id=analysis_id,
                text=f"✅ Task #{analysis_id} da tao.{task_line}\n\nNhan 'Xu ly task' de bot tu dong fix code.",
            )
        except Exception as e:
            logger.error(f"Task only failed for analysis {analysis_id}: {e}")
            await self._telegram.send_message(group_config.telegram_chat_id, f"Loi khi tao OpenProject task: {e}")

    async def _handle_process(self, analysis_id: int, user_id: int) -> None:
        """Select repo, analyze root cause, and create PR — triggered after task creation."""
        analysis = await self._db.get_bug_analysis(analysis_id)
        group_config = self._config.get_group(analysis.group_name)

        await self._telegram.send_message(
            group_config.telegram_chat_id,
            f"Dang chon repo va phan tich Bug #{analysis_id}...",
        )

        # Select repo
        repos = group_config.repos
        if not repos:
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"Bug #{analysis_id}: nhom [{analysis.group_name}] chua co repo nao duoc cau hinh.",
            )
            return

        if len(repos) == 1:
            r = repos[0]
            owner, name = r.owner, r.name
        else:
            try:
                messages = await self._db.get_recent_messages(analysis.group_name, limit=20, within_hours=6)
                owner, name, _ = await self._ai.select_repo(messages, repos)
            except Exception as e:
                logger.error(f"AI select_repo failed for analysis {analysis_id}: {e}")
                await self._telegram.send_message(
                    group_config.telegram_chat_id,
                    f"AI gap loi khi chon repo cho Bug #{analysis_id}: {e}",
                )
                return

        await self._db.update_bug_analysis_status(
            analysis_id, BugStatus.TASK_ONLY,
            repo_owner=owner, repo_name=name,
        )
        analysis.repo_owner = owner
        analysis.repo_name = name
        repo_config = next(r for r in repos if r.name == name)

        if self._config.dry_run:
            await self._telegram.send_message(
                group_config.telegram_chat_id, "Dry run — khong thay doi code."
            )
            return

        # Clone repo and analyze root cause
        try:
            repo_dir = await self._code_agent.clone_or_pull(
                owner, name, repo_config.branch, self._config.github_token
            )
            keywords = (analysis.claude_summary or "").split() + [name]
            relevant = find_relevant_files(repo_dir, keywords)
            code_context = self._code_agent.read_files_for_context(relevant)
        except Exception as e:
            logger.error(f"CodeAgent error for analysis {analysis_id}: {e}")
            code_context = ""

        try:
            context_messages = await self._db.get_recent_messages(analysis.group_name, limit=20, within_hours=6)
            root_analysis = await _call_with_retry(
                lambda: self._ai.analyze_root_cause(context_messages, code_context),
                self._db, analysis_id,
                alert_fn=lambda msg: asyncio.create_task(
                    self._telegram.send_message(group_config.telegram_chat_id, msg)
                ),
            )
            root_cause = root_analysis.get("root_cause", "")
            proposed_fix = root_analysis.get("proposed_fix_description", "")
            await self._db.update_bug_analysis_status(
                analysis_id, BugStatus.APPROVED,
                root_cause=root_cause, proposed_fix=proposed_fix,
            )
            analysis.root_cause = root_cause
            analysis.proposed_fix = proposed_fix
        except Exception as e:
            logger.error(f"Root cause analysis failed for analysis {analysis_id}: {e}")
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"AI khong the phan tich root cause cho Bug #{analysis_id}: {e}",
            )
            return

        # Generate patch and create PR
        pr_url, pr_number = None, None
        try:
            patch = await self._ai.generate_patch(root_cause, code_context)
            branch_name = f"fix/bug-{analysis_id}"
            patch_ok = await self._code_agent.apply_patch(patch, repo_dir)
            if patch_ok:
                push_ok = await self._code_agent.create_branch_and_push(
                    repo_dir, branch_name,
                    f"fix: bug-{analysis_id} from ZaloSniper",
                    self._config.github_token,
                    owner, name,
                )
                if push_ok:
                    pr_url, pr_number = self._github.create_pull_request(
                        owner=owner, repo_name=name,
                        branch=branch_name, base=repo_config.branch,
                        title=f"fix: {analysis.claude_summary or f'Bug {analysis_id}'}",
                        body=(
                            f"**Root cause:** {root_cause}\n\n"
                            f"**Fix:** {proposed_fix}\n\n"
                            + (f"OpenProject: {analysis.op_work_package_url}" if analysis.op_work_package_url else "")
                        ),
                        enabled=self._config.github_pr_enabled,
                    )
        except Exception as e:
            logger.error(f"Patch/PR creation failed for analysis {analysis_id}: {e}")
            await self._telegram.send_message(
                group_config.telegram_chat_id,
                f"Khong the tao patch/PR cho Bug #{analysis_id}: {e}\n"
                f"Vui long fix thu cong dua tren root cause o tren.",
            )

        await self._db.update_bug_analysis_status(
            analysis_id, BugStatus.DONE,
            pr_url=pr_url, pr_number=pr_number,
        )

        parts = [f"Bug #{analysis_id} da xu ly xong:"]
        parts.append(f"Root cause: {root_cause}")
        if pr_url:
            parts.append(f"PR: {pr_url}")
        else:
            parts.append("(Chua tao duoc PR tu dong — vui long fix thu cong)")
        await self._telegram.send_message(group_config.telegram_chat_id, "\n".join(parts))

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
