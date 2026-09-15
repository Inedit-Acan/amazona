class AmazonaError(Exception):
    """Base class for domain errors raised across AMAZONA services."""


class NotFoundError(AmazonaError):
    """Raised when a requested domain record does not exist."""
