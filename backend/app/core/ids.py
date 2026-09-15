import uuid


def new_id() -> str:
    """Generate a unique UUID4 identifier for domain records."""
    return str(uuid.uuid4())


def new_correlation_id() -> str:
    """Generate a unique UUID4 correlation id for request/event tracing."""
    return str(uuid.uuid4())
