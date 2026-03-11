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
        f"_Bug ID: {analysis.id}_\n\n"
        f"✅ Approve / ❌ Reject / 📋 Task Only"
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

    async def send_message(self, chat_id: int, text: str, parse_mode: Optional[str] = None) -> Optional[int]:
        """Send a plain text message. Pass parse_mode='Markdown' only for formatted content."""
        try:
            msg = await self._app.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=parse_mode
            )
            return msg.message_id
        except Exception as e:
            logger.error(f"Failed to send Telegram message to {chat_id}: {e}")
            return None

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
        try:
            action, analysis_id_str = query.data.split(":", 1)
            analysis_id = int(analysis_id_str)
        except (ValueError, AttributeError):
            logger.warning(f"Malformed callback data: {query.data!r}")
            await query.answer("Invalid callback data.")
            return

        if self._on_callback:
            task = asyncio.create_task(self._on_callback(analysis_id, action, user_id))
            task.add_done_callback(
                lambda t: logger.error(f"Callback error: {t.exception()}") if not t.cancelled() and t.exception() else None
            )

    # --- Commands ---

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        zalo_ok = self._zalo_session_valid_fn() if self._zalo_session_valid_fn else None
        zalo_status = "🟢 Zalo: connected" if zalo_ok else ("🔴 Zalo: session expired" if zalo_ok is False else "❓ Zalo: unknown")
        group_count = len(self._config.groups) if self._config else 0
        await update.message.reply_text(
            f"🤖 *ZaloSniper Status*\n"
            f"{zalo_status}\n"
            f"Groups monitored: {group_count}",
            parse_mode="Markdown"
        )

    async def _cmd_groups(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._config:
            await update.message.reply_text("No config loaded.")
            return
        lines = []
        for gname, gcfg in self._config.groups.items():
            repos = ", ".join(f"`{r.owner}/{r.name}`" for r in gcfg.repos)
            lines.append(f"• *{gname}*: {repos}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_pending(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._db:
            await update.message.reply_text("Database not configured.")
            return
        pending = await self._db.get_pending_analyses()
        if not pending:
            await update.message.reply_text("✅ Không có bug nào đang chờ approve.")
            return
        lines = [f"• Bug #{a.id}: `{a.repo_owner}/{a.repo_name}` — {a.claude_summary}" for a in pending]
        await update.message.reply_text("⏳ *Pending bugs:*\n" + "\n".join(lines), parse_mode="Markdown")

    async def _cmd_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._db or not self._ai:
            await update.message.reply_text("Service not configured.")
            return
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

    async def _cmd_ask(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._db or not self._ai:
            await update.message.reply_text("Service not configured.")
            return
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /ask <group_name> <câu hỏi>")
            return
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

    async def _cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._db:
            await update.message.reply_text("Database not configured.")
            return
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
