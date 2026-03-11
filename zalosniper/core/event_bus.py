import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List


@dataclass
class Event:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)


HandlerFn = Callable[[Event], Coroutine]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: Dict[str, List[HandlerFn]] = {}

    def subscribe(self, event_type: str, handler: HandlerFn) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def publish(self, event: Event) -> None:
        for handler in self._subscribers.get(event.type, []):
            asyncio.create_task(handler(event))
