#!/usr/bin/env python3
import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv
load_dotenv()

from zalosniper.core.config import ConfigManager
from zalosniper.core.database import Database
from zalosniper.core.event_bus import EventBus
from zalosniper.core.orchestrator import Orchestrator

from zalosniper.modules.ai_analyzer import AIAnalyzer
from zalosniper.modules.code_agent import CodeAgent
from zalosniper.modules.github_client import GitHubClient
from zalosniper.modules.telegram_bot import TelegramBot
from zalosniper.modules.zalo_listener import ZaloListener

from zalosniper.web.app import create_app, start_web_server
from zalosniper.web.auth import AuthManager
from zalosniper.web.log_handler import ring_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("main")


async def run(
    config_path: str,
    relogin: bool = False,
    headed: bool = False,
    ai_provider: str | None = None,
    ai_model: str | None = None,
) -> None:
    # Install ring buffer log handler
    logging.getLogger().addHandler(ring_handler)

    db = Database("zalosniper.db")
    await db.init()

    # Migrate config.yaml → DB on first run
    await db.migrate_from_yaml(config_path)

    # Load config from DB
    config = await ConfigManager.from_db(db)

    # CLI overrides
    if ai_provider:
        config.ai.provider = ai_provider
        if not ai_model:
            defaults = {"gemini": "gemini-2.0-flash", "zai": "glm-4.7-flash"}
            config.ai.model = defaults.get(ai_provider, config.ai.model)
    if ai_model:
        config.ai.model = ai_model

    logger.info(f"AI provider: {config.ai.provider}, model: {config.ai.model}")

    # --relogin only needs Zalo browser
    if relogin:
        bus = EventBus()
        zalo = ZaloListener(config=config, db=db, bus=bus, alert_fn=None)
        await zalo.start(headless=False)
        logger.info("Relogin complete. Restart without --relogin.")
        await db.close()
        return

    bus = EventBus()
    ai = AIAnalyzer(config=config.ai)
    code_agent = CodeAgent(repos_dir="./repos")
    github = GitHubClient(token=config.github_token)

    # Shared state for the web dashboard
    bot_state = {"bot_running": True, "zalo_running": False, "config": config}

    orchestrator_ref = []

    telegram = TelegramBot(
        bot_token=config.telegram_bot_token,
        approved_user_ids=config.approved_user_ids,
        config=config,
        db=db,
        ai=ai,
        zalo_session_valid_fn=lambda: bot_state.get("zalo_running", False),
        on_callback=lambda aid, action, uid: orchestrator_ref[0].handle_callback(aid, action, uid),
    )

    orchestrator = Orchestrator(config, db, bus, ai, code_agent, github, telegram)
    orchestrator_ref.append(orchestrator)

    # Start Zalo listener
    zalo = ZaloListener(
        config=config, db=db, bus=bus,
        alert_fn=lambda msg: asyncio.create_task(
            telegram.send_message(
                next(iter(config.groups.values())).telegram_chat_id, msg
            )
        ) if config.groups else None,
    )

    session_valid = await zalo.start(headless=not headed)
    if not session_valid:
        logger.error("Zalo session invalid. Run with --relogin.")
        sys.exit(1)

    bot_state["zalo_running"] = True

    # Setup web dashboard
    auth = AuthManager()
    pw_hash = await db.get_setting("dashboard_password")
    if not pw_hash:
        # First run: set default password "admin" and prompt user to change it
        pw_hash = auth.hash_password("admin")
        await db.set_setting("dashboard_password", pw_hash)
        logger.warning("Dashboard password set to 'admin'. Change it at http://localhost:%d/keys", config.dashboard_port)

    web_app = create_app(db=db, auth=auth, password_hash=pw_hash, bot_state=bot_state)

    await telegram.start()
    logger.info("ZaloSniper started.")
    logger.info(f"Dashboard: http://localhost:{config.dashboard_port}")

    try:
        await asyncio.gather(
            zalo.run_poll_loop(),
            orchestrator.run_timeout_scheduler(),
            start_web_server(web_app, host="127.0.0.1", port=config.dashboard_port),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        bot_state["bot_running"] = False
        await zalo.stop()
        await telegram.stop()
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZaloSniper Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--relogin", action="store_true", help="Re-authenticate Zalo session")
    parser.add_argument("--headed", action="store_true", help="Run browser in visible mode (for debugging)")
    parser.add_argument("--ai", dest="ai_provider", metavar="PROVIDER",
                        help="Override AI provider: gemini | zai | openai_compatible")
    parser.add_argument("--model", dest="ai_model", metavar="MODEL",
                        help="Override AI model name (e.g. glm-4.7, gemini-2.0-flash)")
    args = parser.parse_args()
    asyncio.run(run(
        args.config,
        relogin=args.relogin,
        headed=args.headed,
        ai_provider=args.ai_provider,
        ai_model=args.ai_model,
    ))
