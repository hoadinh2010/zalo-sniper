import asyncio
import pytest
from zalosniper.core.event_bus import EventBus, Event


@pytest.mark.asyncio
async def test_publish_subscribe():
    bus = EventBus()
    received = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("NEW_MESSAGE", handler)
    await bus.publish(Event(type="NEW_MESSAGE", data={"group": "abc"}))
    await asyncio.sleep(0.05)   # let handler run

    assert len(received) == 1
    assert received[0].data["group"] == "abc"


@pytest.mark.asyncio
async def test_multiple_subscribers():
    bus = EventBus()
    calls = []

    async def h1(e): calls.append("h1")
    async def h2(e): calls.append("h2")

    bus.subscribe("BUG_DETECTED", h1)
    bus.subscribe("BUG_DETECTED", h2)
    await bus.publish(Event(type="BUG_DETECTED", data={}))
    await asyncio.sleep(0.05)

    assert set(calls) == {"h1", "h2"}


@pytest.mark.asyncio
async def test_unsubscribed_type_ignored():
    bus = EventBus()
    received = []

    async def handler(e): received.append(e)
    bus.subscribe("NEW_MESSAGE", handler)

    await bus.publish(Event(type="OTHER_EVENT", data={}))
    await asyncio.sleep(0.05)

    assert received == []
