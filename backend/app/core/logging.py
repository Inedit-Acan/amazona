import logging
from contextvars import ContextVar

from pythonjsonlogger import json as jsonlogger

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(correlation_id: str) -> None:
    _correlation_id_ctx.set(correlation_id)


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(CorrelationIdFilter())
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(correlation_id)s %(message)s"
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
