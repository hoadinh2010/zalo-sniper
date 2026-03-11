import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from zalosniper.core.config import ConfigManager
from zalosniper.core.database import Database
from zalosniper.core.event_bus import Event, EventBus
from zalosniper.models.message import Message
from zalosniper.modules.zalo_selectors import (
    ZALO_WEB_URL, LOGIN_INDICATOR, MESSAGE_ITEM,
    MESSAGE_SENDER, MESSAGE_CONTENT, MESSAGE_TIME, MESSAGE_ID_ATTR,
)

logger = logging.getLogger(__name__)

AlertFn = Callable[[str], None]


def parse_message_time(time_str: str) -> datetime:
    """Parse Zalo Web time formats into datetime."""
    now = datetime.now()
    time_str = time_str.strip()

    if "Hôm qua" in time_str:
        t = time_str.replace("Hôm qua", "").strip()
        h, m = map(int, t.split(":"))
        return (now - timedelta(days=1)).replace(hour=h, minute=m, second=0, microsecond=0)

    if "/" in time_str:
        # Format: "10/03 08:00"
        parts = time_str.split()
        day, month = map(int, parts[0].split("/"))
        h, m = map(int, parts[1].split(":"))
        candidate = now.replace(month=month, day=day, hour=h, minute=m, second=0, microsecond=0)
        # Guard against year rollover (e.g., Dec 31 message parsed in Jan)
        if candidate > now:
            candidate = candidate.replace(year=now.year - 1)
        return candidate

    # Format: "HH:MM" (today)
    h, m = map(int, time_str.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


class ZaloListener:
    def __init__(
        self,
        config: ConfigManager,
        db: Database,
        bus: EventBus,
        alert_fn: Optional[AlertFn] = None,
    ) -> None:
        self._config = config
        self._db = db
        self._bus = bus
        self._alert_fn = alert_fn
        self._page: Optional[Page] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._pw = None
        self._running = False
        # Track last seen timestamp per group for deduplication
        self._last_seen: Dict[str, datetime] = {}

    async def start(self, headless: bool = True) -> bool:
        """Start Playwright and load existing session. Returns True if session valid."""
        session_dir = Path(self._config.zalo_session_dir)
        session_dir.mkdir(parents=True, exist_ok=True)
        state_file = session_dir / "state.json"

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=headless)

        if state_file.exists():
            self._context = await self._browser.new_context(storage_state=str(state_file))
        else:
            self._context = await self._browser.new_context()

        self._page = await self._context.new_page()
        await self._page.goto(ZALO_WEB_URL)

        if not await self._is_session_valid():
            if not headless:
                logger.info("Session invalid — waiting for manual login...")
                await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=120_000)
                await self._context.storage_state(path=str(state_file))
                logger.info("Session saved.")
                return True
            else:
                logger.warning("Zalo session expired.")
                if self._alert_fn:
                    self._alert_fn("Zalo session het han. Chay `python main.py --relogin`.")
                return False

        return True

    async def _is_session_valid(self) -> bool:
        if not self._page:
            return False
        if "login" in self._page.url:
            return False
        try:
            await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=5_000)
            return True
        except Exception:
            return False

    async def run_poll_loop(self) -> None:
        """Poll all configured groups in a loop."""
        self._running = True
        while self._running:
            for group_name in self._config.groups:
                try:
                    await self._poll_group(group_name)
                except Exception as e:
                    logger.error(f"Error polling group {group_name!r}: {e}")
                    if self._alert_fn:
                        self._alert_fn(f"Zalo: loi khi poll group {group_name!r}: {e}")
            await asyncio.sleep(self._config.zalo_poll_interval)

    async def _poll_group(self, group_name: str) -> None:
        """Navigate to a group, extract new messages, save to DB, emit event."""
        # Step 1: Search for the group in the sidebar search box
        search_box = await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=5_000)
        await search_box.click()
        await search_box.fill(group_name)
        await asyncio.sleep(1)   # wait for search results

        # Step 2: Click the first matching result
        group_items = await self._page.query_selector_all(
            f"[title='{group_name}'], .group-item:has-text('{group_name}')"
        )
        if not group_items:
            logger.warning(f"Group not found in Zalo sidebar: {group_name!r}")
            return
        await group_items[0].click()
        await asyncio.sleep(1)   # wait for messages to load

        # Step 3: Extract messages from the DOM
        raw_messages = await self._extract_messages_from_dom()

        # Step 4: Filter new messages and save
        await self._process_extracted_messages(group_name, raw_messages)

        # Step 5: Clear search box
        await search_box.fill("")

    async def _extract_messages_from_dom(self) -> List[dict]:
        """Extract raw message data from the current group page DOM."""
        raw = []
        items = await self._page.query_selector_all(MESSAGE_ITEM)
        for item in items:
            try:
                sender_el = await item.query_selector(MESSAGE_SENDER)
                content_el = await item.query_selector(MESSAGE_CONTENT)
                time_el = await item.query_selector(MESSAGE_TIME)
                msg_id = await item.get_attribute(MESSAGE_ID_ATTR)

                sender = (await sender_el.inner_text()).strip() if sender_el else "Unknown"
                content = (await content_el.inner_text()).strip() if content_el else ""
                time_str = (await time_el.inner_text()).strip() if time_el else ""

                if content:
                    raw.append({
                        "sender": sender,
                        "content": content,
                        "time_str": time_str,
                        "zalo_message_id": msg_id,
                    })
            except Exception as e:
                logger.debug(f"Failed to extract message element: {e}")
        return raw

    async def _process_extracted_messages(
        self, group_name: str, raw_messages: List[dict]
    ) -> None:
        """Parse raw DOM data, filter by last_seen timestamp, save to DB, emit events."""
        last_seen = self._last_seen.get(group_name, datetime.min)
        new_count = 0

        for raw in raw_messages:
            try:
                ts = parse_message_time(raw["time_str"]) if raw["time_str"] else datetime.now()
            except Exception:
                ts = datetime.now()

            if ts <= last_seen:
                continue   # already seen

            msg = Message(
                id=None,
                group_name=group_name,
                sender=raw["sender"],
                content=raw["content"],
                timestamp=ts,
                zalo_message_id=raw.get("zalo_message_id"),
            )
            msg_id = await self._db.insert_message(msg)
            if msg_id:
                new_count += 1

        if new_count > 0:
            self._last_seen[group_name] = datetime.now()
            await self._bus.publish(Event(
                type="NEW_MESSAGE",
                data={"group_name": group_name, "new_count": new_count}
            ))
            logger.info(f"Group {group_name!r}: {new_count} new messages saved.")

    async def stop(self) -> None:
        self._running = False
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
