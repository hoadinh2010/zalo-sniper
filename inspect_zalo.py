#!/usr/bin/env python3
"""
Auto-discover Zalo Web selectors by inspecting the live DOM.
Run once after login: python inspect_zalo.py
Updates zalosniper/modules/zalo_selectors.py automatically.
"""
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from playwright.async_api import async_playwright

ZALO_WEB_URL = "https://chat.zalo.me"
SESSION_DIR = Path("./zalo_session")
STATE_FILE = SESSION_DIR / "state.json"
SELECTORS_FILE = Path("zalosniper/modules/zalo_selectors.py")


JS_DISCOVER = """
() => {
    const result = {};

    // --- Search / login indicator ---
    const inputs = Array.from(document.querySelectorAll('input'));
    for (const inp of inputs) {
        const rect = inp.getBoundingClientRect();
        if (rect.width > 100 && inp.type !== 'hidden') {
            const attrs = {};
            for (const a of inp.attributes) attrs[a.name] = a.value;
            result.search_input = {tag: 'input', attrs};
            break;
        }
    }

    // --- Conversation list items ---
    // Find the list of chats: look for repeated sibling divs containing an avatar + name
    const candidates = document.querySelectorAll('[class*="conv-item"], [class*="conversation-item"], [class*="chat-item-list"]');
    if (candidates.length > 0) {
        const el = candidates[0];
        const classNames = el.className.split(' ').filter(c => c && !c.includes('selected') && !c.includes('active'));
        result.conv_item_class = classNames[0] || null;

        // Find name element inside
        const nameEl = el.querySelector('[class*="name"], [class*="title"]');
        if (nameEl) {
            result.conv_name_selector = nameEl.className.split(' ').map(c => '.' + c).join('');
        }
    }

    // --- Message container ---
    const msgScroll = document.querySelector('#messageViewScroll') ||
                      document.querySelector('[class*="message-view"]') ||
                      document.querySelector('[class*="messageView"]');
    if (msgScroll) result.message_container = '#' + (msgScroll.id || '') || msgScroll.className;

    // --- Individual messages ---
    const chatItems = document.querySelectorAll('[class*="chat-item"]');
    if (chatItems.length > 0) {
        const item = chatItems[0];
        const cls = Array.from(item.classList).find(c => c === 'chat-item' || c.startsWith('chat-item'));
        result.message_item_class = cls;

        // Sender
        const senderEl = item.querySelector('[class*="sender-name"], [class*="senderName"]');
        if (senderEl) {
            result.sender_selector = '.' + Array.from(senderEl.classList).join('.');
        }

        // Content
        const textEl = item.querySelector('[data-component="text-container"] .text') ||
                       item.querySelector('[class*="text-message"] .text') ||
                       item.querySelector('.text');
        if (textEl) {
            result.content_selector_attrs = {
                'data-component': textEl.closest('[data-component]')?.getAttribute('data-component'),
                'class': textEl.className
            };
        }

        // Time
        const timeEl = item.querySelector('[class*="send-time"], [class*="sendTime"]');
        if (timeEl) {
            result.time_selector_class = Array.from(timeEl.classList).find(c => c.includes('time') || c.includes('Time'));
        }

        // Message ID attribute
        const frameEl = item.querySelector('[data-component="message-content-view"]') ||
                        item.querySelector('[data-qid]');
        if (frameEl) {
            result.message_id_attr = frameEl.hasAttribute('data-qid') ? 'data-qid' : frameEl.getAttribute('data-component');
            result.message_frame_component = frameEl.getAttribute('data-component');
        }

        // Is "me" class
        const meItem = document.querySelector('.chat-item.me');
        result.me_class = meItem ? 'me' : null;
    }

    return result;
}
"""


async def discover() -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        if STATE_FILE.exists():
            ctx = await browser.new_context(storage_state=str(STATE_FILE))
        else:
            ctx = await browser.new_context()

        page = await ctx.new_page()
        print("Opening Zalo Web...")
        await page.goto(ZALO_WEB_URL)

        # Wait for the page to load
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(2)

        url = page.url
        print(f"Current URL: {url}")

        if any(k in url for k in ("login", "qr", "auth")):
            print("❌ Not logged in. Run: python main.py --relogin")
            await browser.close()
            return {}

        print("✅ Logged in. Discovering selectors...")
        data = await page.evaluate(JS_DISCOVER)
        print(json.dumps(data, indent=2, ensure_ascii=False))

        await browser.close()
        return data


def build_selectors(data: dict) -> dict:
    """Map discovered DOM info to selector strings."""
    sel = {}

    # Search / login indicator
    si = data.get("search_input", {})
    attrs = si.get("attrs", {})
    if attrs.get("data-id"):
        sel["LOGIN_INDICATOR"] = f"input[data-id='{attrs['data-id']}']"
    elif attrs.get("id"):
        sel["LOGIN_INDICATOR"] = f"input#{attrs['id']}"
    elif attrs.get("placeholder"):
        sel["LOGIN_INDICATOR"] = f"input[placeholder='{attrs['placeholder']}']"
    else:
        sel["LOGIN_INDICATOR"] = "input[data-id='txt_Main_Search']"

    # Conv items
    if data.get("conv_item_class"):
        sel["GROUP_LIST_ITEM"] = f".{data['conv_item_class']}"
    else:
        sel["GROUP_LIST_ITEM"] = ".conv-item"

    if data.get("conv_name_selector"):
        sel["GROUP_NAME_SELECTOR"] = data["conv_name_selector"].rstrip(".")
    else:
        sel["GROUP_NAME_SELECTOR"] = ".conv-item-title__name .truncate"

    # Message container
    if data.get("message_container"):
        sel["MESSAGE_CONTAINER"] = data["message_container"]
    else:
        sel["MESSAGE_CONTAINER"] = "#messageViewScroll"

    # Message item
    if data.get("message_item_class"):
        sel["MESSAGE_ITEM"] = f".{data['message_item_class']}"
    else:
        sel["MESSAGE_ITEM"] = ".chat-item"

    # Sender
    if data.get("sender_selector"):
        sel["MESSAGE_SENDER"] = data["sender_selector"]
    else:
        sel["MESSAGE_SENDER"] = ".message-sender-name-content .truncate"

    # Content
    ca = data.get("content_selector_attrs", {})
    if ca.get("data-component") and ca.get("class"):
        sel["MESSAGE_CONTENT"] = f"[data-component='{ca['data-component']}'] .{ca['class']}"
    else:
        sel["MESSAGE_CONTENT"] = "[data-component='text-container'] .text"

    # Time
    if data.get("time_selector_class"):
        sel["MESSAGE_TIME"] = f".{data['time_selector_class']}"
    else:
        sel["MESSAGE_TIME"] = ".card-send-time__sendTime"

    # Frame / ID
    if data.get("message_frame_component"):
        sel["MESSAGE_FRAME"] = f"[data-component='{data['message_frame_component']}']"
    else:
        sel["MESSAGE_FRAME"] = "[data-component='message-content-view']"

    sel["MESSAGE_ID_ATTR"] = data.get("message_id_attr", "data-qid")
    sel["MESSAGE_ME_CLASS"] = data.get("me_class") or "me"

    return sel


def write_selectors_file(sel: dict) -> None:
    lines = [
        "# All Playwright selectors isolated here.",
        "# Auto-generated by inspect_zalo.py — re-run when Zalo Web updates its UI.",
        "",
        f"ZALO_WEB_URL = \"{ZALO_WEB_URL}\"",
        f"LOGIN_INDICATOR = \"{sel['LOGIN_INDICATOR']}\"   # present when logged in",
        "",
        "# Sidebar conversation list",
        f"GROUP_LIST_ITEM = \"{sel['GROUP_LIST_ITEM']}\"",
        f"GROUP_NAME_SELECTOR = \"{sel['GROUP_NAME_SELECTOR']}\"",
        "",
        "# Message area",
        f"MESSAGE_CONTAINER = \"{sel['MESSAGE_CONTAINER']}\"",
        f"MESSAGE_ITEM = \"{sel['MESSAGE_ITEM']}\"",
        f"MESSAGE_SENDER = \"{sel['MESSAGE_SENDER']}\"",
        f"MESSAGE_CONTENT = \"{sel['MESSAGE_CONTENT']}\"",
        f"MESSAGE_TIME = \"{sel['MESSAGE_TIME']}\"",
        f"MESSAGE_FRAME = \"{sel['MESSAGE_FRAME']}\"",
        f"MESSAGE_ID_ATTR = \"{sel['MESSAGE_ID_ATTR']}\"",
        f"MESSAGE_ME_CLASS = \"{sel['MESSAGE_ME_CLASS']}\"",
        "",
    ]
    SELECTORS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✅ Selectors written to {SELECTORS_FILE}")


async def main():
    data = await discover()
    if not data:
        return
    sel = build_selectors(data)
    print("\n--- Resolved selectors ---")
    for k, v in sel.items():
        print(f"  {k} = {v!r}")
    write_selectors_file(sel)
    print("\nDone. Run 'python main.py --headed' to test.")


if __name__ == "__main__":
    asyncio.run(main())
