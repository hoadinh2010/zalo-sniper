#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
import sys

from zalosniper.core.config import ConfigManager
from zalosniper.core.database import Database
from zalosniper.core.event_bus import EventBus
from zalosniper.core.orchestrator import Orchestrator
from zalosniper.modules.ai_analyzer import AIAnalyzer
from zalosniper.modules.code_agent import CodeAgent
from zalosniper.modules.github_client import GitHubClient
from zalosniper.modules.telegram_bot import TelegramBot
from zalosniper.modules.zalo_listener import ZaloListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("main")


async def run(config_path: str, relogin: bool = False) -> None:
    config = ConfigManager(config_path)
    db = Database("zalosniper.db")
    await db.init()

    bus = EventBus()
    ai = AIAnalyzer(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    code_agent = CodeAgent(repos_dir="./repos")
    github = GitHubClient(token=config.github_token)

    orchestrator_ref = []   # forward reference filled below

    telegram = TelegramBot(
        bot_token=config.telegram_bot_token,
        approved_user_ids=config.approved_user_ids,
        config=config,
        db=db,
        ai=ai,
        zalo_session_valid_fn=lambda: zalo._running,   # True when listener is active
        on_callback=lambda aid, action, uid: asyncio.create_task(
            orchestrator_ref[0].handle_callback(aid, action, uid)
        ),
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

    headless = not relogin
    session_valid = await zalo.start(headless=headless)
    if not session_valid and not relogin:
        logger.error("Zalo session invalid. Run with --relogin.")
        sys.exit(1)
    if relogin:
        logger.info("Relogin complete. Restart without --relogin.")
        return

    # Start all services
    await telegram.start()
    logger.info("ZaloSniper started.")

    try:
        await asyncio.gather(
            zalo.run_poll_loop(),
            orchestrator.run_timeout_scheduler(),
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        await zalo.stop()
        await telegram.stop()
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ZaloSniper Bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--relogin", action="store_true", help="Re-authenticate Zalo session")
    args = parser.parse_args()
    asyncio.run(run(args.config, relogin=args.relogin))
