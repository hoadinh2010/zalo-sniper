import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from zalosniper.core.config import ConfigManager
from zalosniper.core.database import Database
from zalosniper.core.event_bus import Event, EventBus
from zalosniper.models.message import Message
from zalosniper.modules.zalo_selectors import (
    ZALO_WEB_URL, LOGIN_INDICATOR,
    GROUP_LIST_ITEM, GROUP_NAME_SELECTOR,
    MESSAGE_ITEM, MESSAGE_SENDER, MESSAGE_CONTENT,
    MESSAGE_TIME, MESSAGE_FRAME, MESSAGE_ID_ATTR, MESSAGE_ME_CLASS,
    MESSAGE_DATE_DIVIDER, MESSAGE_IMAGE,
)

logger = logging.getLogger(__name__)

AlertFn = Callable[[str], None]


def _parse_date_from_divider(divider_text: str) -> Optional[datetime]:
    """Parse date from a Zalo chat divider like 'Hôm qua', 'Hôm nay', '10/03'."""
    text = divider_text.strip()
    now = datetime.now()

    if "Hôm nay" in text:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "Hôm qua" in text:
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    # Format: "10/03" or "Thứ ..., 10/03"
    m = re.search(r"(\d{1,2})/(\d{1,2})", text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        candidate = now.replace(month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
        if candidate > now:
            candidate = candidate.replace(year=now.year - 1)
        return candidate
    return None


def parse_message_time(time_str: str, date_context: Optional[datetime] = None) -> datetime:
    """Parse Zalo Web time formats into datetime.

    Args:
        time_str: The time string from the message element (e.g. "17:30", "Hôm qua 20:01")
        date_context: Date from the nearest preceding date divider, used when
                      time_str is just "HH:MM" without a date prefix.
    """
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
        if candidate > now:
            candidate = candidate.replace(year=now.year - 1)
        return candidate

    # Format: "HH:MM" — use date_context if available, otherwise assume today
    h, m = map(int, time_str.split(":"))
    if date_context:
        return date_context.replace(hour=h, minute=m, second=0, microsecond=0)
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
        await self._dismiss_dialogs()

        if not await self._is_session_valid():
            if not headless:
                logger.info("Session invalid — browser opened, please scan QR code in Chromium.")
                logger.info("After chat loads, press ENTER here to save session and continue...")
                # Run blocking input() in executor so event loop isn't blocked
                await asyncio.get_event_loop().run_in_executor(None, input)
                await self._context.storage_state(path=str(state_file))
                logger.info(f"Session saved to {state_file}")
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
        # Wait for page to finish initial navigation
        try:
            await self._page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass
        url = self._page.url
        # Zalo redirects to a login/QR page when session is expired
        # When logged in, URL stays at chat.zalo.me without login-related paths
        if any(kw in url for kw in ("login", "signin", "qr", "auth")):
            return False
        # If still at chat.zalo.me root or deeper, session is likely valid
        return "chat.zalo.me" in url

    async def _dismiss_dialogs(self) -> None:
        """Auto-dismiss Zalo Web popups, sync banners, and notification prompts."""
        try:
            dismissed = await self._page.evaluate("""
                () => {
                    let count = 0;

                    // Generic close/dismiss buttons
                    const closeSelectors = [
                        '[class*="close-btn"]',
                        '[class*="closeBtn"]',
                        '[class*="btn-close"]',
                        '[data-id*="close"]',
                        '[class*="dismiss"]',
                        '[aria-label="Close"]',
                        '[aria-label="Đóng"]',
                    ];
                    for (const sel of closeSelectors) {
                        const btns = document.querySelectorAll(sel);
                        for (const btn of btns) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                btn.click();
                                count++;
                            }
                        }
                    }

                    // Sync / message history suggestion banner
                    const banners = document.querySelectorAll(
                        '[class*="suggestion-wrapper"], [class*="ecard-web__suggestion"]'
                    );
                    for (const b of banners) {
                        const closeBtns = b.querySelectorAll('button, [class*="close"], [class*="dismiss"]');
                        if (closeBtns.length > 0) {
                            closeBtns[0].click();
                            count++;
                        } else {
                            b.remove();
                            count++;
                        }
                    }

                    // Zalo modal overlays (zl-modal) — dismiss by clicking close or removing
                    const modals = document.querySelectorAll('[class*="zl-modal"], [id*="zl-modal"]');
                    for (const modal of modals) {
                        // Try close button inside modal first
                        const closeBtn = modal.querySelector('[class*="close"], [aria-label="Close"], [aria-label="Đóng"], button');
                        if (closeBtn) {
                            closeBtn.click();
                            count++;
                        } else {
                            // Force remove the modal overlay
                            modal.remove();
                            count++;
                        }
                    }
                    // Also remove any modal backdrop/overlay containers
                    const overlays = document.querySelectorAll('[class*="zl-modal__container"], [class*="ovf-hidden"]');
                    for (const ov of overlays) {
                        // Check if it's a modal overlay blocking interaction
                        const style = window.getComputedStyle(ov);
                        if (style.position === 'fixed' && style.zIndex > 100) {
                            ov.remove();
                            count++;
                        }
                    }

                    // Notification permission modal — click "Không" / "Từ chối" / "Bỏ qua"
                    const allButtons = Array.from(document.querySelectorAll('button'));
                    const rejectLabels = ['không', 'từ chối', 'bỏ qua', 'cancel', 'skip', 'later', 'đóng'];
                    for (const btn of allButtons) {
                        const label = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                        if (rejectLabels.some(l => label === l || label.includes(l))) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                btn.click();
                                count++;
                            }
                        }
                    }

                    return count;
                }
            """)
            if dismissed:
                logger.debug(f"Dismissed {dismissed} dialog element(s).")
        except Exception as e:
            logger.debug(f"_dismiss_dialogs: {e}")

    async def run_poll_loop(self) -> None:
        """Poll all configured groups in a loop."""
        self._running = True
        while self._running:
            await self._dismiss_dialogs()
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
        # Step 1: Type group name into the search box
        search_box = await self._page.wait_for_selector(LOGIN_INDICATOR, timeout=5_000)
        await search_box.click()
        await search_box.fill(group_name)
        await asyncio.sleep(1.5)   # wait for search results to render

        # Step 2: Find conv-item whose name matches exactly, then click it
        conv_items = await self._page.query_selector_all(GROUP_LIST_ITEM)
        target = None
        for item in conv_items:
            name_el = await item.query_selector(GROUP_NAME_SELECTOR)
            if name_el:
                name_text = (await name_el.inner_text()).strip()
                if name_text == group_name:
                    target = item
                    break

        if not target:
            logger.warning(f"Group not found in Zalo sidebar: {group_name!r}")
            await search_box.fill("")
            return

        # Dismiss any modal overlay before clicking
        await self._dismiss_dialogs()
        try:
            await target.click(timeout=10000)
        except Exception:
            # Modal might have blocked click — dismiss again and retry
            await self._dismiss_dialogs()
            await asyncio.sleep(0.5)
            await target.click(timeout=10000)
        await asyncio.sleep(1.5)   # wait for messages to load
        await self._dismiss_dialogs()

        # Step 3: Extract messages from the DOM
        raw_messages = await self._extract_messages_from_dom()

        # Step 4: Filter new messages and save
        await self._process_extracted_messages(group_name, raw_messages)

        # Step 5: Clear search box to restore full conversation list
        await search_box.fill("")
        await search_box.press("Escape")

    async def _extract_messages_from_dom(self) -> List[dict]:
        """Extract raw message data from the current group page DOM.

        Handles two Zalo Web quirks:
        1. Sender name only appears on the first message in a consecutive group
           from the same person — we track last_sender to fill gaps.
        2. Date dividers (e.g. "Hôm qua", "10/03") appear as separate elements
           between messages — we track current_date to assign correct dates.
        """
        raw = []
        last_sender = None
        current_date = None  # date context from dividers

        # Query both messages and dividers in DOM order
        children = await self._page.query_selector_all(
            f"{MESSAGE_ITEM}, {MESSAGE_DATE_DIVIDER}"
        )
        for child in children:
            try:
                classes = await child.get_attribute("class") or ""

                # Check if this is a date divider
                if "chat-divider" in classes:
                    divider_text = (await child.inner_text()).strip()
                    current_date = _parse_date_from_divider(divider_text)
                    continue

                # It's a message item
                is_me = MESSAGE_ME_CLASS in classes.split()

                sender_el = await child.query_selector(MESSAGE_SENDER)
                content_el = await child.query_selector(MESSAGE_CONTENT)
                time_el = await child.query_selector(MESSAGE_TIME)
                frame_el = await child.query_selector(MESSAGE_FRAME)
                msg_id = (await frame_el.get_attribute(MESSAGE_ID_ATTR)) if frame_el else None

                if is_me:
                    sender = "me"
                else:
                    if sender_el:
                        sender = (await sender_el.inner_text()).strip()
                        last_sender = sender
                    else:
                        sender = last_sender or "Unknown"

                content = (await content_el.inner_text()).strip() if content_el else ""
                time_str = (await time_el.inner_text()).strip() if time_el else ""

                # Check for images — use JS to find any meaningful img inside
                image_url = None
                img_info = await child.evaluate("""
                    (el) => {
                        const imgs = el.querySelectorAll('img');
                        const all = [];
                        for (const img of imgs) {
                            const src = img.src || img.getAttribute('data-src') || '';
                            const w = img.naturalWidth || img.width || 0;
                            const h = img.naturalHeight || img.height || 0;
                            const cls = (img.className || '').toLowerCase();
                            all.push({src: src.slice(0, 100), w, h, cls});
                            // Skip tiny images (emojis, icons, avatars)
                            if (cls.includes('emoji') || cls.includes('avatar') || cls.includes('icon')) continue;
                            if (w > 0 && w < 30) continue;
                            // Skip SVG placeholders
                            if (src.startsWith('data:image/svg')) continue;
                            if (src && (src.startsWith('http') || src.startsWith('blob:'))) return {found: src, all};
                        }
                        return {found: null, all};
                    }
                """)
                if img_info and img_info.get("all"):
                    logger.debug(f"Images in message: {img_info['all']}")
                image_url = img_info.get("found") if img_info else None
                if image_url:
                    logger.info(f"Found image in message: {image_url[:80]}")
                if image_url and not content:
                    content = "[Hình ảnh]"

                if content:
                    raw.append({
                        "sender": sender,
                        "content": content,
                        "time_str": time_str,
                        "date_context": current_date,
                        "zalo_message_id": msg_id,
                        "image_url": image_url,
                    })
            except Exception as e:
                logger.debug(f"Failed to extract message element: {e}")
        return raw

    async def _download_image(self, image_url: str, group_name: str, msg_id: str) -> Optional[str]:
        """Download an image from Zalo and save it locally. Returns the local file path."""
        if not image_url:
            return None
        try:
            images_dir = Path("data/images") / group_name.replace("/", "_")
            images_dir.mkdir(parents=True, exist_ok=True)
            safe_id = (msg_id or "unknown").replace("/", "_")[:50]

            if image_url.startswith("blob:"):
                # blob: URLs can't be fetched — convert via canvas in browser
                b64 = await self._page.evaluate("""
                    async (src) => {
                        const img = document.querySelector(`img[src="${src}"]`);
                        if (!img) return null;
                        // Wait for image to load
                        if (!img.complete) await new Promise(r => { img.onload = r; setTimeout(r, 3000); });
                        const canvas = document.createElement('canvas');
                        canvas.width = img.naturalWidth || img.width;
                        canvas.height = img.naturalHeight || img.height;
                        if (canvas.width === 0 || canvas.height === 0) return null;
                        canvas.getContext('2d').drawImage(img, 0, 0);
                        return canvas.toDataURL('image/png').split(',')[1];
                    }
                """, image_url)
                if not b64:
                    return None
                import base64
                body = base64.b64decode(b64)
                filepath = images_dir / f"{safe_id}.png"
                filepath.write_bytes(body)
                logger.debug(f"Image saved (blob): {filepath}")
                return str(filepath)

            if not image_url.startswith("http"):
                return None

            # Use page context to download (preserves Zalo auth cookies)
            response = await self._page.request.get(image_url)
            if response.status != 200:
                logger.debug(f"Image download failed ({response.status}): {image_url[:80]}")
                return None

            body = await response.body()
            content_type = response.headers.get("content-type", "image/jpeg")
            ext = ".jpg"
            if "png" in content_type:
                ext = ".png"
            elif "gif" in content_type:
                ext = ".gif"
            elif "webp" in content_type:
                ext = ".webp"

            filename = f"{safe_id}{ext}"
            filepath = images_dir / filename
            filepath.write_bytes(body)
            logger.debug(f"Image saved: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.debug(f"Failed to download image: {e}")
            return None

    async def _process_extracted_messages(
        self, group_name: str, raw_messages: List[dict]
    ) -> None:
        """Parse raw DOM data, save to DB (dedup via UNIQUE constraints), emit events."""
        new_count = 0
        max_ts = self._last_seen.get(group_name, datetime.min)

        for raw in raw_messages:
            try:
                ts = parse_message_time(raw["time_str"], raw.get("date_context")) if raw["time_str"] else datetime.now()
            except Exception:
                ts = datetime.now()
            # Truncate to minute precision so same message always produces the same
            # timestamp across poll cycles — this is critical for the UNIQUE constraint
            ts = ts.replace(second=0, microsecond=0)

            # Download image if present
            image_path = None
            if raw.get("image_url"):
                image_path = await self._download_image(
                    raw["image_url"], group_name,
                    raw.get("zalo_message_id") or str(ts.timestamp()),
                )

            msg = Message(
                id=None,
                group_name=group_name,
                sender=raw["sender"],
                content=raw["content"],
                timestamp=ts,
                zalo_message_id=raw.get("zalo_message_id"),
                image_path=image_path,
            )
            msg_id = await self._db.insert_message(msg)
            if msg_id:
                new_count += 1
                if ts > max_ts:
                    max_ts = ts

        if new_count > 0:
            self._last_seen[group_name] = max_ts
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
