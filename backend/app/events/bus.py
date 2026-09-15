from collections import defaultdict
from collections.abc import Callable
from typing import Protocol

from app.events.schemas import Event

EventHandler = Callable[[Event], None]


class EventBus(Protocol):
    def publish(self, event: Event) -> None: ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...


class InProcessEventBus:
    """V1 event bus: synchronous, in-process pub/sub.

    Reserved for a Redis-backed adapter later without changing the
    publish/subscribe interface consumers depend on.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get(event.type, []):
            handler(event)
