from app.events.bus import InProcessEventBus
from app.events.schemas import Event


def test_subscribed_handler_is_called_on_publish():
    bus = InProcessEventBus()
    received: list[Event] = []

    bus.subscribe("task.completed", received.append)
    event = Event(type="task.completed", correlation_id="corr-1", payload={"task_id": "t1"})
    bus.publish(event)

    assert received == [event]


def test_publish_does_not_trigger_handlers_for_other_event_types():
    bus = InProcessEventBus()
    received: list[Event] = []

    bus.subscribe("task.failed", received.append)
    bus.publish(Event(type="task.completed", correlation_id="corr-1"))

    assert received == []


def test_multiple_handlers_for_the_same_event_type_all_run():
    bus = InProcessEventBus()
    calls: list[str] = []

    bus.subscribe("task.completed", lambda e: calls.append("first"))
    bus.subscribe("task.completed", lambda e: calls.append("second"))
    bus.publish(Event(type="task.completed", correlation_id="corr-1"))

    assert calls == ["first", "second"]


def test_correlation_id_is_preserved_through_publish_to_handler():
    bus = InProcessEventBus()
    received: list[str] = []

    bus.subscribe("decision.made", lambda e: received.append(e.correlation_id))
    bus.publish(Event(type="decision.made", correlation_id="corr-xyz", payload={}))

    assert received == ["corr-xyz"]


def test_publish_with_no_subscribers_does_not_raise():
    bus = InProcessEventBus()

    bus.publish(Event(type="nobody.listens", correlation_id="corr-1"))
